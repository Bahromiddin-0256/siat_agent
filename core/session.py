"""Chat-session id helpers.

A chat's conversation state lives in LangGraph's checkpointer (see
`core.session_store` for the Redis-or-MemorySaver lifecycle). Each chat is
keyed by a UUID `chat_id` the client owns and stores in `localStorage`,
which doubles as the LangGraph `thread_id`.

This module owns only the id helpers:
  * `validate_chat_id()` — reject non-UUID ids before they become a Redis
    key segment / thread_id, to prevent key-injection-style abuse from
    hostile clients (`*`, `;FLUSHALL`, embedded newlines, etc.).
  * `new_chat_id()`      — mint a fresh UUIDv4 chat id.
"""
from __future__ import annotations

import uuid


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
