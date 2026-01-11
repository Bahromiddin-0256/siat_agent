"""
FastAPI Chat Interface for SDMX Agent.

This module provides a web-based chat interface for the SDMX ID retriever agent
with both REST API and WebSocket support for real-time streaming.
"""

from pathlib import Path
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from enum import Enum
from datetime import datetime
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.agent import create_sdmx_agent, run_agent_async, run_agent_async_stream
from core.settings import settings
from core.logger import setup_logger
from tools import initialize_sdmx_data, initialize_rag_vectorstore, initialize_metadata_vectorstore
from tools import sdmx_tool

logger = setup_logger(__name__)

# Load environment variables

# Global agent instance and system prompt
agent = None
system_prompt = None


class ChatMessage(BaseModel):
    """Chat message model."""
    message: str


class ChatResponse(BaseModel):
    """Chat response model."""
    response: str
    status: str = "success"


class MessageType(str, Enum):
    """Message types for streaming responses."""
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    RESPONSE = "response"
    ERROR = "error"


class ToolCallMessage(BaseModel):
    """Tool call message for streaming."""
    type: MessageType
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[str] = None


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
    global agent, system_prompt, tools_map

    try:
        # Initialize SDMX data and RAG vector store
        json_path = Path(__file__).parent / "jsons" / "main.json"
        logger.info(f"Loading SDMX data from: {json_path}")

        # Initialize keyword-based search
        initialize_sdmx_data(json_path)
        logger.info("SDMX data loaded successfully!")

        # Initialize RAG vector store
        logger.info("Initializing RAG vector store with embeddings...")
        initialize_rag_vectorstore(sdmx_tool._json_data)
        logger.info("RAG vector store initialized successfully!")

        # Initialize metadata RAG vector store
        logger.info("Initializing metadata RAG vector store...")
        initialize_metadata_vectorstore()
        logger.info("Metadata RAG vector store initialized successfully!")

        # Create the agent
        logger.info("Creating SDMX agent...")
        agent, system_prompt, tools_map = create_sdmx_agent()
        logger.info("Application startup complete!")

        yield

    except Exception as e:
        logger.error(f"Error during startup: {e}", exc_info=True)
        raise
    finally:
        # Cleanup
        logger.info("Shutting down application...")


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
    global agent, system_prompt

    if not message.message.strip():
        logger.warning("Empty message received")
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    logger.info(f"Received chat message: {message.message[:100]}...")

    try:
        if agent is None:
            # Fallback to semantic search if agent is not available
            logger.warning("Agent not available, using fallback semantic search")
            from tools import search_sdmx_semantic
            result = search_sdmx_semantic.invoke({"question": message.message})
            return ChatResponse(response=result)

        # Use the agent with system prompt
        response = await run_agent_async(agent, message.message, system_prompt)
        logger.info("Chat response generated successfully")
        return ChatResponse(response=response)

    except Exception as e:
        logger.error(f"Error processing chat message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time chat streaming.

    Connects to the agent and streams responses token by token.
    """
    await manager.connect(websocket)
    logger.info("WebSocket client connected")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            if not data.strip():
                continue

            logger.info(f"Received WebSocket message: {data[:100]}...")

            try:
                global agent, system_prompt

                if agent is None:
                    # Fallback error message
                    await manager.send_message(
                        json.dumps({"type": "error", "content": "Agent not available"}),
                        websocket
                    )
                else:
                    # Stream tool steps and final response
                    async for message in run_agent_async_stream(agent, data, system_prompt, tools_map):
                        try:
                            # Serialize with Unicode support and fallback
                            json_message = json.dumps(
                                message,
                                ensure_ascii=False,  # Preserve Unicode (Uzbek/Cyrillic)
                                default=str           # Fallback: convert any non-serializable to string
                            )
                            await manager.send_message(json_message, websocket)
                        except (TypeError, ValueError) as e:
                            # Log serialization error
                            logger.error(f"JSON serialization error for message type {message.get('type', 'unknown')}: {e}", exc_info=True)

                            # Send error message to client
                            error_message = json.dumps({
                                "type": "error",
                                "content": f"Failed to serialize message: {str(e)}",
                                "timestamp": datetime.now().isoformat()
                            }, ensure_ascii=False)
                            await manager.send_message(error_message, websocket)
                    logger.info("WebSocket streaming completed")

            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}", exc_info=True)
                await manager.send_message(
                    json.dumps({"type": "error", "content": str(e)}),
                    websocket
                )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
        manager.disconnect(websocket)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "agent_available": agent is not None,
        "model": settings.ollama_model,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(settings.port)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )
