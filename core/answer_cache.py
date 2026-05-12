"""TTL cache for full agent answers, keyed on the normalized first-turn question.

Why answer-level (not just retrieval-level): the search cache already lives in
`tools/rag_tool.py`, but a single user question still triggers ~5–10 LLM calls
(ReAct loop + tool calls). For repeat questions like
"2022-yil Toshkent shahri aholisi" the resolved indicator + value never change
within the TTL, so we skip the whole agent run.

Only caches first-turn answers — follow-ups like "endi Samarqand-chi?" depend
on conversation state and would be incorrect under a naive cache lookup.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta

from .logger import setup_logger

logger = setup_logger(__name__)

_TTL = timedelta(hours=1)
_MAX_ENTRIES = 256

_cache: dict[str, tuple[str, datetime]] = {}
_lock = threading.Lock()

_NORMALIZE_RE = re.compile(r"\s+")


def _normalize(question: str) -> str:
    """Lowercase, strip, collapse internal whitespace. Punctuation kept — "2013-yil"
    and "2013 yil" should not collide."""
    return _NORMALIZE_RE.sub(" ", question.strip().lower())


def get(question: str) -> str | None:
    """Return cached answer if fresh, else None."""
    key = _normalize(question)
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        answer, ts = entry
        if datetime.now() - ts >= _TTL:
            _cache.pop(key, None)
            return None
    logger.info(f"Answer cache HIT for: '{question[:60]}'")
    return answer


def put(question: str, answer: str) -> None:
    """Store an answer for this question. Evicts oldest entry past the cap."""
    if not answer or "no response generated" in answer.lower():
        return
    key = _normalize(question)
    with _lock:
        if len(_cache) >= _MAX_ENTRIES:
            oldest = min(_cache, key=lambda k: _cache[k][1])
            _cache.pop(oldest, None)
        _cache[key] = (answer, datetime.now())
    logger.info(f"Answer cache STORE for: '{question[:60]}'")


def clear() -> None:
    with _lock:
        _cache.clear()
