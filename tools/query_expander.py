"""Light-weight query expansion using a domain glossary.

Why this exists: BGE-M3 is multilingual but its semantic neighbourhood for
Uzbek statistical jargon is uneven. A user query like "tug'ilish" may not
fire on an indicator named only "Live births (annual)" in English. We append
known synonyms so the *sparse* (lexical) half of the hybrid retriever has
extra terms to match while the dense vector still drives the main score.

The expansion is conservative — only canonical keys whose tokens actually
appear in the query get expanded — so unrelated synonyms aren't injected.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from core.logger import setup_logger

logger = setup_logger(__name__)

_GLOSSARY_PATH = Path(__file__).parent / "glossary.json"
_glossary: dict[str, list[str]] | None = None
_lock = threading.Lock()


def _load() -> dict[str, list[str]]:
    global _glossary
    if _glossary is None:
        with _lock:
            if _glossary is None:
                try:
                    raw = json.loads(_GLOSSARY_PATH.read_text(encoding="utf-8"))
                    _glossary = {
                        k.lower(): [s.lower() for s in v]
                        for k, v in raw.items()
                        if not k.startswith("_") and isinstance(v, list)
                    }
                    logger.info(f"Glossary loaded: {len(_glossary)} canonical terms")
                except (FileNotFoundError, json.JSONDecodeError) as e:
                    logger.warning(f"Glossary unavailable: {e}")
                    _glossary = {}
    return _glossary


def expand_query(question: str, max_extra_terms: int = 8) -> str:
    """Return the original query with up to N synonym terms appended.

    Triggering rule: a glossary entry contributes its synonyms only if the
    *canonical key* appears as a substring of the lower-cased query, OR if
    any of its synonyms appears (so EN/RU queries also pull in UZ terms).
    """
    if not question or not question.strip():
        return question

    glossary = _load()
    if not glossary:
        return question

    q_lower = question.lower()
    extras: list[str] = []
    for key, synonyms in glossary.items():
        # Trigger if either the canonical key or any synonym is in the query.
        triggered = key in q_lower or any(s in q_lower for s in synonyms)
        if not triggered:
            continue
        # Add the canonical key + the synonyms not already present.
        candidates = [key] + synonyms
        for term in candidates:
            if term in q_lower or term in extras:
                continue
            extras.append(term)
            if len(extras) >= max_extra_terms:
                break
        if len(extras) >= max_extra_terms:
            break

    if not extras:
        return question

    expanded = f"{question} | {' '.join(extras)}"
    logger.debug(f"Query expanded: '{question}' → '{expanded}'")
    return expanded
