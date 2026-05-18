"""Data freshness check for an SDMX indicator.

Reads the indicator's local data file and reports the period coverage
(earliest, latest, granularity, and how many rows actually have a value
for the latest period). The agent should call this BEFORE answering
"current year" / "joriy yil" / "за этот год" style questions so it can
either pick the most recent year with data or honestly tell the user
the data is N years behind.

The catalog-level freshness signals (`status`, `updated_xlsx`) live in
`main.json` and are already exposed via `get_sdmx_metadata`. This tool
deliberately reports only what's in the data file itself, because that's
what determines whether a number can actually be returned.
"""
from __future__ import annotations

from datetime import date
from typing import Union

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from core.logger import setup_logger
from tools.file_utils import load_sdmx_data_file
from tools.sdmx_data_retrieval_tool import (
    _is_period_key,
    _period_sort_key,
)

logger = setup_logger(__name__)


class _FreshnessArgs(BaseModel):
    sdmx_id: Union[int, str] = Field(
        ...,
        description="SDMX indicator ID (int, or a digit-string)",
    )


@tool(args_schema=_FreshnessArgs)
def check_data_freshness(sdmx_id: int) -> str:
    """
    Report period coverage and the latest period with actual data for an SDMX indicator.

    Use this BEFORE answering "current year" / "joriy yil" / "за текущий год"
    questions, or when the user asks for "the latest" / "so'nggi" without
    naming a year. The result tells you:
      - The newest period that has any data row reported.
      - How many rows reported a value for that period (rough completeness).
      - The granularity (annual / quarterly / monthly).
      - How many years behind today's date the data is.

    Args:
        sdmx_id: The SDMX indicator ID.

    Returns:
        A multi-line summary string, or an error message if the data file
        is missing or contains no period columns.
    """
    try:
        sdmx_id = int(sdmx_id)
    except (TypeError, ValueError):
        return f"Error: sdmx_id must be an integer, got {sdmx_id!r}"

    data = load_sdmx_data_file(sdmx_id)
    if data is None:
        return f"SDMX ID {sdmx_id}: data file not found"

    if not isinstance(data, list) or not data:
        return f"SDMX ID {sdmx_id}: unexpected data file shape (empty or not a list)"

    rows = data[0].get("data") if isinstance(data[0], dict) else None
    if not isinstance(rows, list) or not rows:
        return f"SDMX ID {sdmx_id}: data file has no rows"

    # Periods can in principle differ per row (rare but possible) — take the
    # union so we don't miss a period that's only present on some breakdowns.
    period_set: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for k in row:
            if _is_period_key(k):
                period_set.add(k)
    if not period_set:
        return f"SDMX ID {sdmx_id}: no period columns found in data"

    periods = sorted(period_set, key=_period_sort_key)
    earliest, latest = periods[0], periods[-1]

    # Rows reporting a non-null, non-empty value for the latest period.
    # Empty-string and "-" are treated as "no value" — SIAT uses both for
    # missing data in the source xlsx exports.
    def _has_value(v) -> bool:
        if v is None:
            return False
        if isinstance(v, str) and v.strip() in ("", "-", "–", "—"):
            return False
        return True

    total_rows = sum(1 for r in rows if isinstance(r, dict))
    reported_latest = sum(
        1
        for r in rows
        if isinstance(r, dict) and _has_value(r.get(latest))
    )

    granularity = _granularity_of(latest)
    latest_year = _year_of(latest)
    today = date.today()
    years_behind = today.year - latest_year if latest_year else None

    lines = [
        f"SDMX ID {sdmx_id} data freshness:",
        f"- Period coverage: {earliest}..{latest} "
        f"({_distinct_years(periods)} distinct year(s))",
        f"- Granularity: {granularity}",
        f"- Latest period: {latest} "
        f"({reported_latest}/{total_rows} row(s) reported a value)",
    ]
    if years_behind is not None:
        if years_behind <= 0:
            lines.append(
                f"- Currency: data reaches the current year ({today.year})."
            )
        elif years_behind == 1:
            lines.append(
                f"- Currency: data is 1 year behind today ({today.year}); "
                f"do NOT claim a value for {today.year} unless asked for {latest}."
            )
        else:
            lines.append(
                f"- Currency: data is {years_behind} years behind today "
                f"({today.year}); the newest available year is {latest_year}."
            )
    if reported_latest == 0:
        lines.append(
            "- WARNING: the latest period column exists but no row has a "
            "value yet. Fall back to the previous period when answering."
        )
    elif reported_latest < total_rows:
        lines.append(
            f"- Note: only {reported_latest}/{total_rows} rows have a value "
            f"for {latest}; some regions/categories may not have reported."
        )

    return "\n".join(lines)


def _granularity_of(period: str) -> str:
    """Classify a period key as annual / quarterly / monthly / unknown."""
    if "-Q" in period:
        return "quarterly"
    if "-M" in period or (len(period) == 7 and "-" in period):
        return "monthly"
    if period.isdigit() and len(period) == 4:
        return "annual"
    return "unknown"


def _year_of(period: str) -> int | None:
    """Extract the 4-digit year prefix from any period key shape."""
    head = period.split("-", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def _distinct_years(periods: list[str]) -> int:
    """How many distinct years are represented across the period list."""
    return len({_year_of(p) for p in periods} - {None})
