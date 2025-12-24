"""
FastAPI Chat Interface for SDMX Agent.

This module provides a web-based chat interface for the SDMX ID retriever agent
with both REST API and WebSocket support for real-time streaming.
"""

import os
from pathlib import Path
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from agent import create_sdmx_agent, run_agent_async
from tools import initialize_sdmx_data, initialize_rag_vectorstore
from tools import sdmx_tool

# Load environment variables
load_dotenv()

# Global agent instance
agent = None


class ChatMessage(BaseModel):
    """Chat message model."""
    message: str


class ChatResponse(BaseModel):
    """Chat response model."""
    response: str
    status: str = "success"


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the agent on startup."""
    global agent

    # Initialize SDMX data and RAG vector store
    json_path = Path(__file__).parent / "jsons" / "main.json"
    print(f"Loading SDMX data from: {json_path}")

    # Initialize keyword-based search
    initialize_sdmx_data(json_path)
    print("SDMX data loaded successfully!")

    # Initialize RAG vector store
    print("Initializing RAG vector store with embeddings...")
    initialize_rag_vectorstore(sdmx_tool._json_data)
    print("RAG vector store initialized successfully!")

    # Create the agent
    print("Creating SDMX agent...")
    try:
        agent = create_sdmx_agent()
        print("Agent created successfully!")
        print(f"Using model: {os.getenv('OLLAMA_MODEL', 'llama3.2')}")
    except Exception as e:
        print(f"Warning: Could not create agent: {e}")
        print("The API will still work with direct search methods")

    yield

    # Cleanup
    print("Shutting down...")


app = FastAPI(
    title="SDMX ID Retriever Chat API",
    description="Chat interface for finding statistical indicator IDs",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/", response_class=HTMLResponse)
async def get_chat_interface():
    """Serve the chat interface HTML."""
    html_file = Path(__file__).parent / "static" / "chat.html"

    if html_file.exists():
        return html_file.read_text()

    # Return a simple inline HTML if static file doesn't exist
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SDMX Chat</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
            }
            #chat-box {
                border: 1px solid #ccc;
                height: 400px;
                overflow-y: auto;
                padding: 10px;
                margin-bottom: 10px;
                background-color: #f9f9f9;
            }
            .message {
                margin: 10px 0;
                padding: 8px;
                border-radius: 5px;
            }
            .user {
                background-color: #e3f2fd;
                text-align: right;
            }
            .bot {
                background-color: #f1f8e9;
            }
            #input-container {
                display: flex;
                gap: 10px;
            }
            #message-input {
                flex-grow: 1;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 5px;
            }
            button {
                padding: 10px 20px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
            }
            button:hover {
                background-color: #45a049;
            }
        </style>
    </head>
    <body>
        <h1>SDMX ID Retriever Chat</h1>
        <div id="chat-box"></div>
        <div id="input-container">
            <input type="text" id="message-input" placeholder="Type your question..." />
            <button onclick="sendMessage()">Send</button>
        </div>

        <script>
            const chatBox = document.getElementById('chat-box');
            const messageInput = document.getElementById('message-input');

            function addMessage(text, isUser) {
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message ' + (isUser ? 'user' : 'bot');
                messageDiv.textContent = text;
                chatBox.appendChild(messageDiv);
                chatBox.scrollTop = chatBox.scrollHeight;
            }

            async function sendMessage() {
                const message = messageInput.value.trim();
                if (!message) return;

                addMessage(message, true);
                messageInput.value = '';

                try {
                    const response = await fetch('/chat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ message: message }),
                    });

                    const data = await response.json();
                    addMessage(data.response, false);
                } catch (error) {
                    addMessage('Error: ' + error.message, false);
                }
            }

            messageInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });
        </script>
    </body>
    </html>
    """


@app.post("/chat", response_model=ChatResponse)
async def chat(message: ChatMessage):
    """
    Chat endpoint for sending messages to the agent.

    Args:
        message: The user's message

    Returns:
        The agent's response
    """
    global agent

    if not message.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        if agent is None:
            # Fallback to semantic search if agent is not available
            from tools import search_sdmx_semantic
            result = search_sdmx_semantic.invoke({"question": message.message})
            return ChatResponse(response=result)

        # Use the agent
        response = await run_agent_async(agent, message.message)
        return ChatResponse(response=response)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time chat streaming.

    Connects to the agent and streams responses token by token.
    """
    await manager.connect(websocket)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            if not data.strip():
                continue

            try:
                global agent

                if agent is None:
                    # Fallback to semantic search
                    from tools import search_sdmx_semantic
                    result = search_sdmx_semantic.invoke({"question": data})
                    await manager.send_message(result, websocket)
                else:
                    # Use the agent
                    response = await run_agent_async(agent, data)
                    await manager.send_message(response, websocket)

            except Exception as e:
                await manager.send_message(f"Error: {str(e)}", websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "agent_available": agent is not None,
        "model": os.getenv("OLLAMA_MODEL", "llama3.2")
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )
