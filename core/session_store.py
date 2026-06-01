"""Session checkpointer factory.

When ``REDIS_URL`` is set, conversation state is persisted to Redis via
``langgraph-checkpoint-redis`` so it survives restarts and can be shared
across replicas. When unset, an in-process ``MemorySaver`` is used — fine
for local development and tests.

The async path is the production path (FastAPI ``/chat`` and ``/ws`` both
hit ``run_agent_async*``), so we wire ``AsyncRedisSaver``.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)


class SessionStore:
    """Holds the checkpointer and any async resources that need teardown."""

    def __init__(self, checkpointer: Any, exit_stack: AsyncExitStack | None) -> None:
        self.checkpointer = checkpointer
        self._exit_stack = exit_stack

    async def aclose(self) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.aclose()

    async def ping(self) -> bool:
        """Health probe for the backing store.

        Returns True for the in-process MemorySaver (always available), or the
        result of a Redis PING when backed by ``AsyncRedisSaver``.
        """
        redis = getattr(self.checkpointer, "_redis", None)
        if redis is None:
            # MemorySaver (or any non-Redis saver) — in-process, always up.
            return True
        try:
            return bool(await redis.ping())
        except Exception:  # noqa: BLE001
            return False


async def build_session_store(redis_url: str, ttl_seconds: int) -> SessionStore:
    """Build the checkpointer that backs LangGraph thread state.

    With a Redis URL, the returned store holds an ``AsyncExitStack`` that
    owns the Redis connection — call ``await store.aclose()`` on shutdown.
    Without one, returns a plain ``MemorySaver`` and a ``None`` stack.
    """
    if not redis_url:
        logger.info("Session store: in-process MemorySaver (REDIS_URL unset)")
        return SessionStore(MemorySaver(), None)

    # Import lazily so the package is only required when actually using Redis.
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver

    stack = AsyncExitStack()
    ttl_config = {"default_ttl": ttl_seconds // 60, "refresh_on_read": True}
    cm = AsyncRedisSaver.from_conn_string(redis_url, ttl=ttl_config)
    checkpointer = await stack.enter_async_context(cm)
    await checkpointer.asetup()
    logger.info(
        "Session store: AsyncRedisSaver at %s (ttl=%ss)", redis_url, ttl_seconds
    )
    return SessionStore(checkpointer, stack)
