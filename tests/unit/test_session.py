"""Unit tests for core.session — UUID validation only.

The integration tests for the Redis-backed checkpointer live next to this
file as `test_redis_session.py` and skip when no Redis is reachable.
"""
import pytest

from core.session import new_chat_id, validate_chat_id, _redacted_url


def test_validate_accepts_canonical_uuid():
    canonical = "11111111-2222-3333-4444-555555555555"
    assert validate_chat_id(canonical) == canonical


def test_validate_normalises_uppercase_uuid():
    upper = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    assert validate_chat_id(upper) == upper.lower()


def test_validate_rejects_non_uuid():
    with pytest.raises(ValueError):
        validate_chat_id("not-a-uuid")


def test_validate_rejects_obvious_injection():
    # The key segment becomes part of `checkpoint:{thread_id}:…`. Anything
    # with structural characters (newlines, separators, glob wildcards) has
    # to be refused before it gets there.
    for hostile in ("*", ";FLUSHALL", "id\nDEL *", "abc:def"):
        with pytest.raises(ValueError):
            validate_chat_id(hostile)


def test_validate_rejects_non_string_types():
    with pytest.raises(ValueError):
        validate_chat_id(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        validate_chat_id(12345)  # type: ignore[arg-type]


def test_new_chat_id_round_trips_through_validate():
    for _ in range(10):
        cid = new_chat_id()
        assert validate_chat_id(cid) == cid


def test_redacted_url_strips_credentials():
    assert _redacted_url("redis://user:secret@host:6379/0") == "redis://***@host:6379/0"
    assert _redacted_url("redis://host:6379/0") == "redis://host:6379/0"
