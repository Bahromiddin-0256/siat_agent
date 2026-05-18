"""Redis-backed checkpointer lifecycle for chat sessions.

The chat agent keeps conversation state in LangGraph's checkpointer. We use
`AsyncRedisSaver` from `langgraph-checkpoint-redis` so a chat's history
survives HTTP requests, WebSocket reconnects, and server restarts — each
chat is keyed by a UUID `chat_id` the client owns (stored in
`localStorage`).

This module owns:
  * `init_checkpointer()`  — open one process-wide saver during FastAPI
    startup. Fails fast if Redis is unreachable.
  * `close_checkpointer()` — tear it down on shutdown.
  * `get_checkpointer()`   — accessor for the active saver.
  * `validate_chat_id()`   — reject non-UUID ids before they reach Redis,
    to prevent key-injection-style abuse from hostile clients.

TTL: the saver is configured with `ttl={"default_ttl": <minutes>,
"refresh_on_read": True}`. The library applies `EXPIRE` to every key it
writes and refreshes it on reads — both happen for every chat turn (the
agent reads state to decide first-turn vs. follow-up, then writes the new
checkpoint), so idle chats expire `redis_session_ttl_seconds` after the
last interaction.
"""
from __future__ import annotations

import uuid

from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from redis.asyncio import Redis as AsyncRedis

from .logger import setup_logger
from .settings import settings

logger = setup_logger(__name__)


_saver: AsyncRedisSaver | None = None


async def init_checkpointer() -> AsyncRedisSaver:
    """Open the process-wide Redis checkpointer.

    Called once from the FastAPI lifespan. Raises on connection failure so a
    misconfigured deploy fails loud at startup, not silently mid-chat.
    """
    global _saver
    if _saver is not None:
        return _saver

    ttl_minutes = settings.redis_session_ttl_seconds / 60.0
    saver = AsyncRedisSaver(
        redis_url=settings.redis_url,
        ttl={
            "default_ttl": ttl_minutes,
            "refresh_on_read": True,
        },
    )
    # asetup() creates the RediSearch indices and detects cluster mode.
    # PING'ing the server here surfaces unreachable-Redis as a clear error
    # before we touch the index machinery.
    await saver._redis.ping()
    await saver.asetup()
    await saver.aset_client_info()
    _saver = saver
    logger.info(
        "Redis checkpointer ready (url=%s, ttl=%ss, refresh_on_read=True)",
        _redacted_url(settings.redis_url),
        settings.redis_session_ttl_seconds,
    )
    return saver


async def close_checkpointer() -> None:
    """Close the active checkpointer and its underlying Redis client."""
    global _saver
    if _saver is None:
        return
    try:
        if getattr(_saver, "_owns_its_client", True):
            client: AsyncRedis = _saver._redis
            await client.aclose()
            pool = getattr(client, "connection_pool", None)
            if pool is not None:
                disconnect = pool.disconnect()
                if disconnect is not None:
                    await disconnect
    except Exception:
        logger.exception("Error while closing Redis checkpointer")
    finally:
        _saver = None


def get_checkpointer() -> AsyncRedisSaver:
    """Return the active checkpointer. Raises if it hasn't been initialised."""
    if _saver is None:
        raise RuntimeError(
            "Redis checkpointer not initialised — call init_checkpointer() first"
        )
    return _saver


async def ping() -> bool:
    """Lightweight health probe — True if the saver's Redis answers PING."""
    if _saver is None:
        return False
    try:
        return bool(await _saver._redis.ping())
    except Exception:
        return False


def validate_chat_id(value: str) -> str:
    """Return the canonical UUID string form, or raise ValueError.

    `chat_id` becomes a Redis key segment and a LangGraph thread_id. Anything
    that isn't a UUID is rejected to keep the keyspace tidy and to block
    obvious abuse (`*`, `;FLUSHALL`, embedded newlines, etc.).
    """
    if not isinstance(value, str):
        raise ValueError("chat_id must be a string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"chat_id is not a valid UUID: {value!r}") from exc
    return str(parsed)


def new_chat_id() -> str:
    """Mint a fresh UUIDv4 chat id."""
    return str(uuid.uuid4())


def _redacted_url(url: str) -> str:
    """Strip credentials from a redis URL for logging."""
    if "@" not in url:
        return url
    scheme_sep = url.find("://")
    if scheme_sep == -1:
        return url
    head = url[: scheme_sep + 3]
    tail = url[url.find("@", scheme_sep + 3) + 1 :]
    return f"{head}***@{tail}"
