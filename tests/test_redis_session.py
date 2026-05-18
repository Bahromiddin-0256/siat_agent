"""Integration tests for the Redis-backed session checkpointer.

Skips automatically when REDIS_URL isn't reachable (e.g. CI without the
docker-compose Redis Stack service) so contributors aren't blocked.

The full agent loop is too heavy to spin up here (BGE-M3 embeddings + LLM
provider) — these tests exercise the checkpointer directly. They prove the
load-bearing claim: a given `chat_id` resumes the same state, different
`chat_id`s are isolated.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

pytestmark = pytest.mark.asyncio


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


async def _redis_reachable(url: str) -> bool:
    try:
        from redis.asyncio import Redis
        client = Redis.from_url(url)
        try:
            await client.ping()
            return True
        finally:
            await client.aclose()
    except Exception:
        return False


@pytest.fixture
async def saver():
    url = _redis_url()
    if not await _redis_reachable(url):
        pytest.skip(f"Redis not reachable at {url}")

    # Import here so the unit test module can be collected even when
    # langgraph-checkpoint-redis is missing locally (it's listed in
    # pyproject but a contributor might run `pytest` before `uv sync`).
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver

    instance = AsyncRedisSaver(
        redis_url=url,
        ttl={"default_ttl": 1, "refresh_on_read": True},  # 1 minute is plenty for the test
    )
    await instance.asetup()
    try:
        yield instance
    finally:
        client = instance._redis
        await client.aclose()
        pool = getattr(client, "connection_pool", None)
        if pool is not None:
            disconnect = pool.disconnect()
            if disconnect is not None:
                await disconnect


def _make_checkpoint(message: str) -> dict:
    """Minimal valid LangGraph checkpoint shape."""
    return {
        "v": 1,
        "id": str(uuid.uuid4()),
        "ts": "2026-05-18T12:00:00+00:00",
        "channel_values": {"messages": [message]},
        "channel_versions": {"messages": "1"},
        "versions_seen": {},
        "pending_sends": [],
    }


async def test_session_continuity_per_chat_id(saver):
    """Same chat_id → second read sees the first write."""
    chat_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": chat_id, "checkpoint_ns": ""}}

    await saver.aput(config, _make_checkpoint("first turn"), {"source": "input"}, {})
    tup = await saver.aget_tuple(config)

    assert tup is not None, "checkpoint should be readable for the same chat_id"
    assert "first turn" in str(tup.checkpoint.get("channel_values", {}))


async def test_session_isolation_across_chat_ids(saver):
    """Different chat_ids must not see each other's state."""
    a = str(uuid.uuid4())
    b = str(uuid.uuid4())
    cfg_a = {"configurable": {"thread_id": a, "checkpoint_ns": ""}}
    cfg_b = {"configurable": {"thread_id": b, "checkpoint_ns": ""}}

    await saver.aput(cfg_a, _make_checkpoint("alpha only"), {"source": "input"}, {})

    tup_b = await saver.aget_tuple(cfg_b)
    assert tup_b is None, "chat B must not see chat A's history"

    tup_a = await saver.aget_tuple(cfg_a)
    assert tup_a is not None
    assert "alpha only" in str(tup_a.checkpoint.get("channel_values", {}))


async def test_ttl_applied_on_write(saver):
    """The checkpointer attaches an EXPIRE to keys it writes."""
    chat_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": chat_id, "checkpoint_ns": ""}}
    await saver.aput(config, _make_checkpoint("ttl test"), {"source": "input"}, {})

    # Find at least one checkpoint key for this thread and check it has a TTL.
    client = saver._redis
    keys = []
    async for key in client.scan_iter(match=f"checkpoint:{chat_id}*"):
        keys.append(key)
        if len(keys) >= 1:
            break

    assert keys, "expected at least one checkpoint key for the thread"
    ttl = await client.ttl(keys[0])
    # 1-minute TTL was configured; allow any positive value (refresh_on_read
    # may have bumped it). -1 = no expiry (bad), -2 = missing (bad).
    assert ttl > 0, f"expected positive TTL, got {ttl}"
