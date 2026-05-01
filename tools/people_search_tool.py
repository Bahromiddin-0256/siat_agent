"""Search SDMX indicators by the *responsible person* / *department* in metadata.

Why this exists: previous agent runs hallucinated which indicators a given
official is responsible for, because no tool actually inspected the
"Mas'ul hodim FIO" / "Mas'ul boshqarma" metadata fields. Asking the LLM to
guess from a name yielded confidently-wrong topical associations.

This tool builds a lazy in-memory index from the SDMX data files (one row
per indicator → dict with mas'ul, boshqarma, name) and answers prefix /
substring lookups against it.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from core.logger import setup_logger
from tools.file_utils import load_json_safe
from tools.sdmx_data_retrieval_tool import _normalize_apostrophes

logger = setup_logger(__name__)

_SDMX_DIR = Path("jsons/sdmxs")

# Cached index: list of dicts. Built once on first call.
_index: list[dict] | None = None
_index_lock = threading.Lock()


def _build_index() -> list[dict]:
    """Walk every sdmx_data_*.json once, extract the responsible-person fields."""
    rows: list[dict] = []
    if not _SDMX_DIR.exists():
        logger.warning(f"SDMX dir not found: {_SDMX_DIR}")
        return rows

    files = sorted(_SDMX_DIR.glob("sdmx_data_*.json"))
    logger.info(f"Building responsible-person index from {len(files)} SDMX files...")

    for path in files:
        try:
            sdmx_id = int(path.stem.replace("sdmx_data_", ""))
        except ValueError:
            continue
        data = load_json_safe(path, default=None)
        if not isinstance(data, list) or not data:
            continue
        meta = data[0].get("metadata") or []

        person = ""
        department = ""
        name = ""
        for item in meta:
            field = (item.get("name_uz") or "").lower()
            value = item.get("value_uz") or ""
            if "mas'ul hodim" in field or "fio" in field:
                person = value
            elif "mas'ul boshqarma" in field or "department" in field:
                department = value
            elif "to'plami nomi" in field or "indicator name" in (item.get("name_en") or "").lower():
                name = value

        if person or department:
            rows.append({
                "sdmx_id": sdmx_id,
                "person": person,
                "department": department,
                "name": name,
            })

    logger.info(f"Built index: {len(rows)} indicators with assigned person/department")
    return rows


def _get_index() -> list[dict]:
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = _build_index()
    return _index


def _norm(s: str) -> str:
    """Lowercase + apostrophe-fold so 'Mas'ul' / 'Mexmonov' / 'Meҳmonov' all align."""
    return _normalize_apostrophes(s or "").lower()


@tool
def find_indicators_by_person(query: str, limit: int = 25) -> str:
    """
    List SDMX indicators where the given person OR department appears in the
    "Mas'ul hodim FIO" / "Mas'ul boshqarma" metadata fields.

    Use this WHENEVER the user asks "qaysi ko'rsatkichlar uchun X mas'ul",
    "X ma'sul bo'lgan ko'rsatkichlar", "indicators X is responsible for",
    "за какие индикаторы отвечает X". DO NOT guess by topic — guesses based
    on the person's title (e.g. "head of tourism committee") have produced
    confidently wrong answers in the past. Always call this tool.

    Matching is case-insensitive substring on the normalized name. A surname
    alone usually finds the right person; full FIO is most precise.

    Args:
        query: A person's surname / full name OR a department name.
        limit: Max indicators to return (default 25).

    Returns:
        A formatted list: SDMX ID + indicator name + responsible person.
        If nothing matches, suggests the closest spellings.

    Examples:
        find_indicators_by_person("Mexmonov Jahongir")
        find_indicators_by_person("Begmatov Sardor")
        find_indicators_by_person("Demografiya bo'limi")
    """
    if not query or not query.strip():
        return "So'rov bo'sh — shaxs yoki bo'lim nomini bering."

    index = _get_index()
    if not index:
        return "Indeks bo'sh yoki SDMX data topilmadi"

    needle = _norm(query)

    matches = [
        row for row in index
        if needle in _norm(row["person"]) or needle in _norm(row["department"])
    ]

    if not matches:
        # Suggest near-misses by sampling unique person names that share any token.
        tokens = [t for t in needle.split() if len(t) >= 3]
        suggestions: set[str] = set()
        if tokens:
            for row in index:
                p_norm = _norm(row["person"])
                if any(t in p_norm for t in tokens) and row["person"]:
                    suggestions.add(row["person"])
                if len(suggestions) >= 5:
                    break
        out = [f"'{query}' bo'yicha mas'ul shaxs/bo'lim topilmadi."]
        if suggestions:
            out.append("Yaqin nomlar:")
            for s in sorted(suggestions):
                out.append(f"  - {s}")
        return "\n".join(out)

    # Group by person (a query like "demografiya" can match many people in same dept)
    persons = sorted({m["person"] for m in matches if m["person"]})
    departments = sorted({m["department"] for m in matches if m["department"]})

    out = [
        f"'{query}' so'roviga {len(matches)} ta indikator topildi.",
    ]
    if persons:
        out.append(f"Mas'ul shaxs(lar): {', '.join(persons[:3])}{'...' if len(persons) > 3 else ''}")
    if departments:
        out.append(f"Bo'lim(lar): {', '.join(departments[:3])}{'...' if len(departments) > 3 else ''}")
    out.append("")

    no_name = "(nom yo'q)"
    shown = matches[:limit]
    for row in shown:
        out.append(f"- SDMX ID {row['sdmx_id']}: {row['name'] or no_name}")
    if len(matches) > limit:
        out.append(f"... va yana {len(matches) - limit} ta indikator (limit={limit})")
    return "\n".join(out)
