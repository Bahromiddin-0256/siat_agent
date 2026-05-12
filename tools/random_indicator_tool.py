"""Sample random SDMX indicators with one fresh data point each.

Triggered by questions like "menga 3 ta random statistika ber",
"give me 5 random statistics", "случайные показатели" — cases where the
user wants a curated taste of what exists in the catalog rather than
searching for a specific topic. Without this tool the agent would otherwise
fabricate plausible-looking indicators.
"""

from __future__ import annotations

import random
import re
import threading
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from core.logger import setup_logger
from tools.file_utils import load_sdmx_data_file

logger = setup_logger(__name__)

_SDMX_DIR = Path("jsons/sdmxs")
_PERIOD_RE = re.compile(r"^\d{4}(-(Q[1-4]|M\d{1,2}|\d{1,2}))?$")

_ids_cache: list[int] | None = None
_ids_lock = threading.Lock()


def _list_available_ids() -> list[int]:
    """Discover SDMX IDs that have a data file on disk. Cached for the process."""
    global _ids_cache
    if _ids_cache is not None:
        return _ids_cache
    with _ids_lock:
        if _ids_cache is not None:
            return _ids_cache
        ids: list[int] = []
        if _SDMX_DIR.exists():
            for path in _SDMX_DIR.glob("sdmx_data_*.json"):
                try:
                    ids.append(int(path.stem.replace("sdmx_data_", "")))
                except ValueError:
                    continue
        _ids_cache = ids
        logger.info(f"Indexed {len(ids)} SDMX data files for random sampling")
        return _ids_cache


def _period_sort_key(period: str) -> tuple[int, int]:
    m = re.match(r"^(\d{4})(?:-(Q([1-4])|M(\d{1,2})|(\d{1,2})))?$", period)
    if not m:
        return (0, 0)
    year = int(m.group(1))
    if m.group(3):
        return (year, int(m.group(3)))
    if m.group(4):
        return (year, int(m.group(4)))
    if m.group(5):
        return (year, int(m.group(5)))
    return (year, 0)


def _extract_meta(metadata: list[dict[str, Any]]) -> dict[str, str]:
    info: dict[str, str] = {}
    for item in metadata:
        name_en = (item.get("name_en") or "").lower()
        value_uz = item.get("value_uz") or ""
        if "indicator name" in name_en or "dataset name" in name_en:
            info["name"] = value_uz
        elif "periodicity" in name_en:
            info["period"] = value_uz
        elif "unit of measurement" in name_en:
            info["unit"] = value_uz
    return info


def _pick_sample_value(data_section: list[dict[str, Any]]) -> tuple[str, str, str] | None:
    """Return (period, region_label, value) for a sensible recent observation.

    Strategy: prefer the national-aggregate row ("O'zbekiston Respublikasi" /
    code 1700) when present, then fall back to the first row. Pick the latest
    period with a non-empty numeric value.
    """
    if not data_section:
        return None

    preferred = None
    for row in data_section:
        klass = (row.get("Klassifikator") or "").lower()
        if "o" in klass and "zbekiston" in klass and "respublika" in klass:
            preferred = row
            break
    row = preferred or data_section[0]

    period_keys = sorted(
        [k for k in row.keys() if _PERIOD_RE.match(k)],
        key=_period_sort_key,
        reverse=True,
    )
    label = (
        row.get("Klassifikator")
        or row.get("Klassifikator_ru")
        or row.get("Klassifikator_en")
        or ""
    )
    for p in period_keys:
        v = row.get(p)
        if v not in (None, "", "—", "-"):
            return p, label, str(v)
    return None


def _format_number(s: str) -> str:
    """Thousands-separate numeric strings (1234567.8 → 1 234 567.8)."""
    try:
        # Keep trailing decimals as written.
        if "." in s:
            int_part, dec_part = s.split(".", 1)
        else:
            int_part, dec_part = s, ""
        sign = ""
        if int_part.startswith("-"):
            sign = "-"
            int_part = int_part[1:]
        if not int_part.isdigit():
            return s
        grouped = " ".join(
            int_part[max(0, i - 3): i] for i in range(len(int_part), 0, -3)
        )
        grouped = " ".join(reversed(grouped.split()))
        return f"{sign}{grouped}.{dec_part}" if dec_part else f"{sign}{grouped}"
    except Exception:
        return s


@tool
def random_indicators(count: int = 3) -> str:
    """
    Return a small set of randomly sampled SDMX indicators with one fresh data point each.

    Use this when the user asks for a random/arbitrary selection of statistics
    rather than a specific topic. Triggers:
      - Uzbek: "random statistika", "tasodifiy ko'rsatkich", "N ta random", "qiziqarli statistika ber"
      - English: "random statistics", "give me N random indicators", "surprise me with stats"
      - Russian: "случайные показатели", "случайная статистика"

    Each result includes the SDMX ID, indicator name, unit, periodicity, a
    sample value (latest available period, preferring the national-aggregate
    row), and the canonical SIAT link.

    Args:
        count: How many random indicators to return (1–10; clamped to that range).

    Returns:
        A formatted multi-indicator listing in Uzbek.
    """
    n = max(1, min(int(count or 3), 10))
    ids = _list_available_ids()
    if not ids:
        return "SDMX ma'lumot fayllari topilmadi."

    # Oversample so we can skip indicators that have no usable data point.
    pool = random.sample(ids, k=min(n * 4, len(ids)))

    picked: list[tuple[int, dict, tuple[str, str, str] | None]] = []
    for sdmx_id in pool:
        if len(picked) >= n:
            break
        data = load_sdmx_data_file(sdmx_id)
        if not isinstance(data, list) or not data:
            continue
        metadata = data[0].get("metadata") or []
        info = _extract_meta(metadata)
        if not info.get("name"):
            continue
        sample = _pick_sample_value(data[0].get("data") or [])
        picked.append((sdmx_id, info, sample))

    if not picked:
        return "Tasodifiy statistika tanlash muvaffaqiyatsiz tugadi."

    out: list[str] = [f"{len(picked)} ta tasodifiy ko'rsatkich:\n"]
    for idx, (sdmx_id, info, sample) in enumerate(picked, 1):
        out.append(f"{idx}. **SDMX ID {sdmx_id}** — {info['name']}")
        if info.get("unit"):
            out.append(f"   O'lchov: {info['unit']}")
        if info.get("period"):
            out.append(f"   Davriylik: {info['period']}")
        if sample:
            period, label, value = sample
            value_fmt = _format_number(value)
            location = f" ({label})" if label else ""
            out.append(f"   Namuna: {period} — {value_fmt} {info.get('unit', '')}{location}".rstrip())
        out.append(f"   https://siat.stat.uz/reports-filed/{sdmx_id}/table-data")
        out.append("")

    return "\n".join(out).rstrip()
