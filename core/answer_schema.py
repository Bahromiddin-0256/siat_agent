"""Structured representation of an agent answer.

The agent itself still emits markdown (the UX requirement: language-matched,
human-readable). This module *extracts* a typed schema from that markdown so:

  - frontends can render side-cards / verification buttons without re-parsing
  - the critic can validate concrete fields (IDs present, periods match the
    question, unit looks plausible) instead of doing string heuristics
  - telemetry has stable keys to slice on ("which indicators are queried most?")

Why post-hoc extraction instead of asking the LLM for JSON: forcing JSON breaks
streaming UX, hurts multilingual quality (models drift to English inside JSON
strings), and would require rewriting the system prompt. The reference list
at the bottom of every answer is already structured enough to parse reliably.
"""
from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field


# Reference-list line, the format the system prompt mandates:
#   - SDMX ID 223: Tug'ilganlar soni — https://siat.stat.uz/reports-filed/223/table-data
_REFERENCE_LINE_RE = re.compile(
    r"SDMX\s*ID\s*(?P<id>\d+)\s*:\s*(?P<name>[^—\-\n]+?)\s*[—\-]\s*"
    r"(?P<link>https?://siat\.stat\.uz/[^\s\)]+)",
    re.IGNORECASE,
)
_SDMX_ID_ANY_RE = re.compile(r"SDMX\s*ID\s*(\d+)", re.IGNORECASE)
_PERIOD_RE = re.compile(r"\b(20\d{2}(?:-(?:Q[1-4]|M\d{1,2}|\d{2}))?)\b")
_SIAT_LINK_RE = re.compile(r"https?://siat\.stat\.uz/reports-filed/(\d+)/[^\s\)]+")

# Units we expect to see in SIAT data. Order matters — the longest-match-first
# scan below relies on multi-word units (e.g. "mlrd. so'm") being tried before
# their substrings.
_UNIT_PATTERNS: list[str] = [
    "mlrd. so'm", "mln. so'm", "mlrd so'm", "mln so'm",
    "mlrd. soum", "mln. soum", "ming so'm", "ming soum",
    "млрд. сум", "млн. сум", "млрд сум", "млн сум", "тыс. сум",
    "billion soum", "million soum", "thousand soum",
    "kishi", "ming kishi", "человек", "тыс. человек", "people", "persons",
    "%", "foiz", "процент", "percent",
    "ta",
    "tonna", "ming tonna", "тонн", "тыс. тонн", "tons",
    "km2", "ming gektar", "гектар",
]


class AnswerSchema(BaseModel):
    """Structured representation of an agent answer."""

    sdmx_ids: List[int] = Field(default_factory=list)
    periods: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    units: List[str] = Field(default_factory=list)
    siat_links: List[str] = Field(default_factory=list)
    indicator_names: List[str] = Field(default_factory=list)
    confidence: float = 1.0  # heuristic — drops when fields are missing
    tools_used: List[str] = Field(default_factory=list)

    def is_empty_data_answer(self) -> bool:
        """True if there's no concrete data signal (no IDs, no periods, no values).

        Useful for the critic — an answer that's just text with zero
        extractable structure for a data question is almost always wrong.
        """
        return not (self.sdmx_ids or self.periods or self.units)


def _scan_units(text: str) -> list[str]:
    """Find units present in the text, longest-first to avoid double-counting."""
    found: list[str] = []
    remaining = text
    for unit in sorted(_UNIT_PATTERNS, key=len, reverse=True):
        if unit.lower() in remaining.lower() and unit not in found:
            found.append(unit)
    return found


def _scan_regions(text: str, candidate_regions: Optional[list[str]] = None) -> list[str]:
    """Find region mentions. Without an authoritative list, fall back to a
    minimal set of high-frequency labels — this is best-effort metadata, not
    validation. Callers can pass `candidate_regions` to scope the scan.
    """
    if candidate_regions is None:
        candidate_regions = [
            "Toshkent shahri", "Toshkent viloyati", "Andijon viloyati", "Buxoro viloyati",
            "Farg'ona viloyati", "Jizzax viloyati", "Xorazm viloyati", "Namangan viloyati",
            "Navoiy viloyati", "Qashqadaryo viloyati", "Samarqand viloyati",
            "Sirdaryo viloyati", "Surxondaryo viloyati", "Qoraqalpog'iston",
            # Russian forms
            "г. Ташкент", "Ташкентская область", "Андижанская область",
            "Бухарская область", "Ферганская область",
        ]
    lower = text.lower()
    return [r for r in candidate_regions if r.lower() in lower]


def extract_schema(text: str, tools_used: Optional[list[str]] = None) -> AnswerSchema:
    """Parse the agent's markdown response into an AnswerSchema. Best-effort."""
    if not text:
        return AnswerSchema(confidence=0.0, tools_used=tools_used or [])

    ids: set[int] = set()
    names: list[str] = []
    links: set[str] = set()

    # Preferred path: the reference list at the bottom has every field on one line.
    for m in _REFERENCE_LINE_RE.finditer(text):
        ids.add(int(m.group("id")))
        names.append(m.group("name").strip())
        links.add(m.group("link").strip())

    # Fallback: any SDMX ID mention + any siat.stat.uz link.
    if not ids:
        for m in _SDMX_ID_ANY_RE.finditer(text):
            ids.add(int(m.group(1)))
    for m in _SIAT_LINK_RE.finditer(text):
        links.add(m.group(0))
        ids.add(int(m.group(1)))

    periods = sorted(set(_PERIOD_RE.findall(text)))[:12]
    units = _scan_units(text)
    regions = _scan_regions(text)

    # Confidence — start at 1.0, dock for each missing structural field.
    confidence = 1.0
    if not ids:
        confidence -= 0.4
    if not links:
        confidence -= 0.2
    if not periods:
        confidence -= 0.1
    if not units:
        confidence -= 0.1
    confidence = max(0.0, round(confidence, 2))

    return AnswerSchema(
        sdmx_ids=sorted(ids),
        periods=periods,
        regions=regions,
        units=units,
        siat_links=sorted(links),
        indicator_names=names,
        confidence=confidence,
        tools_used=list(dict.fromkeys(tools_used or [])),
    )


def validate_against_question(question: str, schema: AnswerSchema) -> list[str]:
    """Return a list of issue strings (empty when the schema looks consistent
    with the question). Schema-level analogue of `critic._structural_check` —
    operates on typed fields so it's robust to formatting changes in the answer.
    """
    issues: list[str] = []

    # A question that mentions a year/quarter must produce at least one matching
    # period in the answer. (Same logic as the regex critic, but on parsed fields.)
    question_periods = set(_PERIOD_RE.findall(question))
    if question_periods and not (question_periods & set(schema.periods)):
        issues.append(
            f"answer periods {schema.periods} don't include any of the "
            f"question's periods {sorted(question_periods)}"
        )

    if schema.is_empty_data_answer() and _PERIOD_RE.search(question):
        issues.append("question is data-shaped but answer has no SDMX ID, period, or unit")

    if schema.sdmx_ids and not schema.siat_links:
        issues.append("answer cites SDMX IDs but no SIAT verification link")

    return issues
