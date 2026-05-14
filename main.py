"""
FastAPI Chat Interface for SDMX Agent.

This module provides a web-based chat interface for the SDMX ID retriever agent
with both REST API and WebSocket support for real-time streaming.
"""

import asyncio
import time
import uuid
from collections import deque
from pathlib import Path
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from enum import Enum
from datetime import datetime
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

from core.agent import create_sdmx_agent, run_agent_async, run_agent_async_stream
from core.settings import settings
from core.logger import setup_logger
from tools import (
    initialize_sdmx_data,
    initialize_rag_vectorstore,
    initialize_metadata_vectorstore,
    ensure_main_json,
)
from tools import sdmx_tool
from tools.rag_tool import get_vectorstore
from tools.metadata_rag_tool import get_metadata_vectorstore

logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Application state — encapsulated in a plain namespace to avoid bare globals
# ---------------------------------------------------------------------------

class _AppState:
    agent = None
    system_prompt: Optional[str] = None
    tools_map: Dict[str, Any] = {}


_state = _AppState()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

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
    CHART = "chart"
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


# ---------------------------------------------------------------------------
# WebSocket connection manager with per-connection rate limiting
# ---------------------------------------------------------------------------

_RATE_LIMIT_MESSAGES = 10   # max messages
_RATE_LIMIT_WINDOW = 1.0    # per second
_MAX_MESSAGE_BYTES = 64_000  # 64 KB per message


class ConnectionManager:
    """Manages WebSocket connections with per-connection rate limiting."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        # Maps websocket id -> deque of message timestamps
        self._rate_windows: Dict[int, deque] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self._rate_windows[id(websocket)] = deque()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self._rate_windows.pop(id(websocket), None)

    def check_rate_limit(self, websocket: WebSocket) -> bool:
        """Return True if the connection is within the rate limit."""
        window = self._rate_windows.get(id(websocket))
        if window is None:
            return True
        now = time.monotonic()
        # Evict timestamps older than the window
        while window and window[0] < now - _RATE_LIMIT_WINDOW:
            window.popleft()
        if len(window) >= _RATE_LIMIT_MESSAGES:
            return False
        window.append(now)
        return True

    async def send_message(self, message: str, websocket: WebSocket) -> bool:
        """Send text to a WebSocket; return False if the connection is closed.

        Wrapping the send keeps the streaming loop resilient — a client tab
        closed mid-response or a network blip shouldn't propagate as a 500
        error or kill the rest of the request handling.
        """
        try:
            await websocket.send_text(message)
            return True
        except (WebSocketDisconnect, RuntimeError) as e:
            # RuntimeError fires when starlette's WS is already in CLOSED state.
            logger.info("WebSocket send skipped — client gone (%s)", e)
            self.disconnect(websocket)
            return False


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Audit logging middleware
# ---------------------------------------------------------------------------

class AuditMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status, and duration."""

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "AUDIT | %s %s | status=%d | %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate config, initialise data and the agent on startup."""

    # --- Fail fast on bad config ---
    config_errors = settings.validate_config()
    if config_errors:
        for err in config_errors:
            logger.error("Config error: %s", err)
        raise RuntimeError("Invalid configuration — see logs above")

    try:
        json_path = Path(__file__).parent / "jsons" / "main.json"

        # Run blocking I/O in the default thread-pool executor so we don't
        # stall the event loop.
        loop = asyncio.get_event_loop()

        # First-boot fetch: if main.json is missing, download it from the
        # configured SDMX catalog URL before initialising anything that
        # depends on it.
        if not json_path.exists():
            logger.info(
                "main.json not found at %s — fetching from %s",
                json_path, settings.sdmx_catalog_url,
            )
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    ensure_main_json,
                    json_path,
                    settings.sdmx_catalog_url,
                ),
                timeout=90.0,
            )

        logger.info("Loading SDMX data from: %s", json_path)
        await asyncio.wait_for(
            loop.run_in_executor(None, initialize_sdmx_data, json_path),
            timeout=120.0,
        )
        logger.info("SDMX data loaded successfully!")

        logger.info("Initializing RAG vector store with embeddings...")
        await asyncio.wait_for(
            loop.run_in_executor(
                None, initialize_rag_vectorstore, sdmx_tool._json_data
            ),
            timeout=180.0,
        )
        logger.info("RAG vector store initialized successfully!")

        logger.info("Initializing metadata RAG vector store...")
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                initialize_metadata_vectorstore,
            ),
            timeout=180.0,
        )
        logger.info("Metadata RAG vector store initialized successfully!")

        logger.info("Creating SDMX agent...")
        _state.agent, _state.system_prompt, _state.tools_map = create_sdmx_agent()
        logger.info("Application startup complete!")

        yield

    except asyncio.TimeoutError as exc:
        logger.error("Startup timed out during initialisation: %s", exc)
        raise
    except Exception as exc:
        logger.error("Error during startup: %s", exc, exc_info=True)
        raise
    finally:
        logger.info("Shutting down application...")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SDMX ID Retriever Chat API",
    description="Chat interface for finding statistical indicator IDs",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(AuditMiddleware)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

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
    if not message.message.strip():
        logger.warning("Empty message received")
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    logger.info("Received chat message: %s...", message.message[:100])

    try:
        if _state.agent is None:
            logger.warning("Agent not available, using fallback semantic search")
            from tools import search_sdmx_semantic
            result = search_sdmx_semantic.invoke({"question": message.message})
            return ChatResponse(response=result)

        # Each /chat request is independent — give it its own thread id so
        # concurrent users never share checkpointer state.
        response = await run_agent_async(
            _state.agent,
            message.message,
            _state.system_prompt,
            _state.tools_map,
            thread_id=f"chat-{uuid.uuid4()}",
        )
        logger.info("Chat response generated successfully")
        return ChatResponse(response=response)

    except Exception as e:
        logger.error("Error processing chat message: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time chat streaming.

    Connects to the agent and streams responses token by token.
    Enforces per-connection rate limiting and message size limits.
    """
    await manager.connect(websocket)
    # Stable per-connection thread id — keeps follow-ups in the same conversation
    # but isolates this socket from every other client.
    ws_thread_id = f"ws-{uuid.uuid4()}"
    logger.info("WebSocket client connected (thread_id=%s)", ws_thread_id)

    try:
        while True:
            data = await websocket.receive_text()

            if not data.strip():
                continue

            # Enforce message size limit
            if len(data.encode()) > _MAX_MESSAGE_BYTES:
                await manager.send_message(
                    json.dumps({"type": "error", "content": "Message too large (max 64 KB)"}),
                    websocket,
                )
                continue

            # Enforce rate limit
            if not manager.check_rate_limit(websocket):
                await manager.send_message(
                    json.dumps({"type": "error", "content": "Rate limit exceeded — slow down"}),
                    websocket,
                )
                continue

            logger.info("Received WebSocket message: %s...", data[:100])

            try:
                if _state.agent is None:
                    await manager.send_message(
                        json.dumps({"type": "error", "content": "Agent not available"}),
                        websocket,
                    )
                else:
                    async for message in run_agent_async_stream(
                        _state.agent,
                        data,
                        _state.system_prompt,
                        _state.tools_map,
                        thread_id=ws_thread_id,
                    ):
                        try:
                            json_message = json.dumps(
                                message,
                                ensure_ascii=False,
                                default=str,
                            )
                            await manager.send_message(json_message, websocket)
                        except (TypeError, ValueError) as e:
                            logger.error(
                                "JSON serialization error for message type %s: %s",
                                message.get("type", "unknown"),
                                e,
                                exc_info=True,
                            )
                            error_message = json.dumps(
                                {
                                    "type": "error",
                                    "content": f"Failed to serialize message: {str(e)}",
                                    "timestamp": datetime.now().isoformat(),
                                },
                                ensure_ascii=False,
                            )
                            await manager.send_message(error_message, websocket)
                    logger.info("WebSocket streaming completed")

            except Exception as e:
                logger.error("Error processing WebSocket message: %s", e, exc_info=True)
                # send_message returns False if the socket is already gone — in
                # that case stop the receive loop, otherwise we just keep
                # raising on every iteration.
                delivered = await manager.send_message(
                    json.dumps({"type": "error", "content": str(e)}),
                    websocket,
                )
                if not delivered:
                    break

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
        manager.disconnect(websocket)
    except Exception as e:
        # Catch-all so a bug in the streaming path doesn't bubble up as a
        # FastAPI 500 (which only shows in server logs, not to the user).
        logger.error("Unhandled WebSocket error: %s", e, exc_info=True)
        manager.disconnect(websocket)


@app.get("/health")
async def health_check():
    """
    Detailed health check endpoint.

    Verifies that all subsystems are operational and reports their status.
    """
    checks = {
        "agent": _state.agent is not None,
        "vector_store": get_vectorstore() is not None,
        "metadata_store": get_metadata_vectorstore() is not None,
        "json_data": bool(sdmx_tool._json_data),
    }

    # Only probe the LLM provider that's actually configured.
    if settings.llm_provider == "ollama":
        ollama_ok = False
        try:
            import httpx
            async with httpx.AsyncClient(timeout=0.5) as client:
                resp = await client.get(f"{settings.ollama_base_url}/api/tags")
                ollama_ok = resp.status_code == 200
        except Exception:
            pass
        checks["ollama"] = ollama_ok
        active_model = settings.ollama_model
    elif settings.llm_provider == "groq":
        checks["groq_api_key"] = bool(settings.groq_api_key.strip())
        active_model = settings.groq_model
    elif settings.llm_provider == "deepinfra":
        checks["deepinfra_api_key"] = bool(settings.deepinfra_api_key.strip())
        active_model = settings.deepinfra_model
    elif settings.llm_provider == "open_router":
        checks["open_router_api_key"] = bool(settings.open_router_api_key.strip())
        active_model = "meta-llama/llama-3.3-70b-instruct:free"
    elif settings.llm_provider == "openai":
        checks["openai_api_key"] = bool(settings.openai_api_key.strip())
        active_model = settings.openai_model
    elif settings.llm_provider == "vllm":
        checks["vllm_base_url"] = bool(settings.vllm_base_url.strip())
        active_model = settings.vllm_model
    else:
        active_model = "unknown"

    all_ok = all(checks.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "model": active_model,
        "provider": settings.llm_provider,
        "checks": checks,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(settings.port)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,   # Never use reload=True in production
    )
