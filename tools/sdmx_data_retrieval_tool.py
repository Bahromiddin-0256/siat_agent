"""
SDMX Data Retrieval Tool for extracting actual statistical values.

This tool reads local SDMX data files and extracts specific values
based on SDMX ID, year, and region/classifier to minimize LLM context.
"""

import re
from pathlib import Path
from typing import Optional, List

from langchain_core.tools import tool
from core.logger import setup_logger
from tools.file_utils import load_sdmx_data_file  # noqa: F401 — re-exported for callers
from tools.constants import Units, Messages
from tools.chart_utils import push_chart

logger = setup_logger(__name__)

# Period column keys come in several shapes:
#   "2013"           — yearly
#   "2025-Q1"        — quarterly
#   "2025-M01"       — monthly (FlagEmbedding-style)
#   "2025-01"        — monthly (ISO-style)
# Anything matching this pattern is treated as a data period.
_PERIOD_RE = re.compile(r"^\d{4}(-(Q[1-4]|M\d{1,2}|\d{1,2}))?$")

# Non-period fields that appear alongside period columns in each data row.
_NON_PERIOD_KEYS = {
    "Code",
    "Klassifikator",
    "Klassifikator_ru",
    "Klassifikator_en",
    "Klassifikator_uzc",
}


def _is_period_key(key: str) -> bool:
    """True if `key` looks like a data period column (year/quarter/month)."""
    return isinstance(key, str) and bool(_PERIOD_RE.match(key))


def _period_sort_key(period: str) -> tuple[int, int]:
    """Sort key for period strings: (year, sub-period). Q1<Q2<...; M01<M02<..."""
    m = re.match(r"^(\d{4})(?:-(Q([1-4])|M(\d{1,2})|(\d{1,2})))?$", period)
    if not m:
        return (0, 0)
    year = int(m.group(1))
    if m.group(3):  # Qn
        return (year, int(m.group(3)))
    if m.group(4):  # Mnn
        return (year, int(m.group(4)))
    if m.group(5):  # nn
        return (year, int(m.group(5)))
    return (year, 0)


def _matching_periods(all_periods: list[str], requested: str) -> list[str]:
    """Return periods matching a user-supplied year/period string.

    - Exact match (e.g. "2025-Q1") wins if present.
    - Otherwise prefix match on the year (e.g. "2025" → ["2025-Q1", "2025-Q2", ...]).
    """
    if requested in all_periods:
        return [requested]
    return [p for p in all_periods if p == requested or p.startswith(f"{requested}-")]


def extract_value_from_data(
    data: list[dict],
    year: str,
    region: Optional[str] = None,
    region_code: Optional[str] = None
) -> Optional[dict]:
    """
    Extract specific value from SDMX data array.

    Args:
        data: The data array from SDMX JSON
        year: Year as string (e.g., "2013")
        region: Region name to search for (searches all name variants)
        region_code: Specific region code (e.g., "1703")

    Returns:
        Dict with region info and value, or None if not found
    """
    if not data or not isinstance(data, list):
        return None

    # Get the actual data array (skip metadata if present)
    data_array = data[0].get('data', []) if len(data) > 0 and 'data' in data[0] else data

    for row in data_array:
        if not isinstance(row, dict):
            continue

        # Check if this row matches the region criteria
        region_match = False

        if region_code and row.get('Code') == region_code:
            region_match = True
        elif region:
            # Search in all classifier name variants
            region_lower = region.lower()
            klassifikator = str(row.get('Klassifikator', '')).lower()
            klassifikator_ru = str(row.get('Klassifikator_ru', '')).lower()
            klassifikator_en = str(row.get('Klassifikator_en', '')).lower()
            klassifikator_uzc = str(row.get('Klassifikator_uzc', '')).lower()

            if (region_lower in klassifikator or
                region_lower in klassifikator_ru or
                region_lower in klassifikator_en or
                region_lower in klassifikator_uzc):
                region_match = True
        else:
            # If no region specified, match first row (usually total)
            region_match = True

        if region_match:
            # Try exact key first, then year-prefix (e.g. "2025" → "2025-Q1").
            if year in row:
                matched_key = year
            else:
                period_keys = [k for k in row.keys() if _is_period_key(k)]
                candidates = _matching_periods(period_keys, year)
                if not candidates:
                    continue
                # If the user gave a bare year and data is sub-annual, return
                # the first matching period; aggregation is the caller's job.
                matched_key = sorted(candidates, key=_period_sort_key)[0]

            return {
                'code': row.get('Code'),
                'region_uz': row.get('Klassifikator'),
                'region_ru': row.get('Klassifikator_ru'),
                'region_en': row.get('Klassifikator_en'),
                'year': matched_key,
                'value': row.get(matched_key),
            }

    return None


@tool
def get_sdmx_value(sdmx_id: int, year: Optional[str] = None, region: Optional[str] = None) -> str:
    """
    Extract statistical value(s) from SDMX data file with unit.

    Use this tool when you need to get actual statistical numbers from a known SDMX ID.
    This tool reads local data files and extracts values based on the parameters provided.

    Args:
        sdmx_id: The SDMX identifier (e.g., 223 for birth statistics).
        year: Optional period as a string. Accepts:
              - bare year:    "2013", "2020"
              - quarter:      "2025-Q1"
              - month:        "2025-M03" or "2025-03"
              A bare year against quarterly/monthly data matches all sub-periods
              of that year. If None, behaviour depends on `region` (see below).
        region: Optional region or category name in any language
                ("Andijon", "Андижан", "Andijan", "infek..."). If None,
                behaviour depends on `year` (see below).

    Returns:
        A formatted string with the extracted value(s), unit, and context.

    Behaviour matrix:
        year=set,    region=set    → single value for that region+period
        year=set,    region=None   → all rows (regions/categories) for that period
        year=None,   region=set    → all periods for that region
        year=None,   region=None   → snapshot of all rows for the LATEST period
                                     (use this to discover what's in a dataset)

    Examples:
        get_sdmx_value(223, "2013", "Andijon")  → "Andijon ... 2013: 64239.0 kishi"
        get_sdmx_value(4530, "2025-Q3")         → all categories for 2025-Q3
        get_sdmx_value(4530, "2025")            → all categories × Q1..Q4 of 2025
        get_sdmx_value(4530)                    → all categories for the latest quarter
    """
    # Load the data file
    data = load_sdmx_data_file(sdmx_id)

    if data is None:
        return f"Error: SDMX data file for ID {sdmx_id} not found in local storage (jsons/sdmxs/sdmx_data_{sdmx_id}.json)"

    # Extract the data section and metadata
    if isinstance(data, list) and len(data) > 0:
        data_section = data[0].get('data', [])
        metadata = data[0].get('metadata', [])
    else:
        return f"Error: Invalid data format in SDMX file {sdmx_id}"

    if not data_section:
        return f"Error: No data found in SDMX file {sdmx_id}"

    # Extract unit from metadata
    unit = Units.DEFAULT
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', 'kishi')
            break

    # Collect all period columns (yearly, quarterly, or monthly).
    all_years: list[str] = []
    if data_section and len(data_section) > 0:
        first_row = data_section[0]
        all_years = sorted(
            [k for k in first_row.keys() if _is_period_key(k)],
            key=_period_sort_key,
        )

    # Case 1: Both year and region are None.
    # Return an overview of ALL rows (regions/categories) for the LATEST period.
    # This gives a useful snapshot regardless of whether row 0 happens to be
    # "national total" or just the first category in a breakdown.
    if year is None and region is None:
        if not all_years:
            return f"SDMX ID {sdmx_id}: davr ustunlari topilmadi"

        latest = all_years[-1]
        result_lines = [f"SDMX ID {sdmx_id} — {latest} (eng so'nggi davr)"]
        result_lines.append(f"O'lchov: {unit}")
        result_lines.append("")

        for row in data_section:
            row_name = (
                row.get('Klassifikator')
                or row.get('Klassifikator_ru')
                or row.get('Klassifikator_en')
                or "Ma'lum emas"
            )
            value = row.get(latest, 'N/A')
            result_lines.append(f"{row_name}: {value} {unit}")

        if len(all_years) > 1:
            result_lines.append("")
            result_lines.append(
                f"Boshqa davrlar uchun `year` bering. Mavjud: {', '.join(all_years)}"
            )
        return "\n".join(result_lines)

    # Case 2: year is None, but region is specified - return all years for that region
    if year is None and region is not None:
        # Find the matching region row
        matching_row = None
        region_lower = region.lower()

        for row in data_section:
            klassifikator = str(row.get('Klassifikator', '')).lower()
            klassifikator_ru = str(row.get('Klassifikator_ru', '')).lower()
            klassifikator_en = str(row.get('Klassifikator_en', '')).lower()
            klassifikator_uzc = str(row.get('Klassifikator_uzc', '')).lower()

            if (region_lower in klassifikator or
                region_lower in klassifikator_ru or
                region_lower in klassifikator_en or
                region_lower in klassifikator_uzc):
                matching_row = row
                break

        if not matching_row:
            return f"Mintaqa topilmadi: '{region}' uchun SDMX ID {sdmx_id}"

        region_name = matching_row.get('Klassifikator') or matching_row.get('Klassifikator_ru') or matching_row.get('Klassifikator_en') or region

        result_lines = [f"SDMX ID {sdmx_id}: {region_name}"]
        result_lines.append(f"O'lchov: {unit}")
        result_lines.append("")

        chart_data = []
        for yr in all_years:
            value = matching_row.get(yr, 'N/A')
            result_lines.append(f"{yr}: {value} {unit}")
            if value != 'N/A' and value is not None:
                try:
                    chart_data.append({"label": yr, "value": float(value)})
                except (ValueError, TypeError):
                    pass

        if chart_data:
            push_chart({
                "chart_type": "line",
                "title": f"SDMX ID {sdmx_id}: {region_name}",
                "unit": unit,
                "data": chart_data,
            })

        return "\n".join(result_lines)

    # Case 3: region is None, but year/period is specified - return all regions for that period(s)
    if year is not None and region is None:
        matched_periods = _matching_periods(all_years, year)
        if not matched_periods:
            years_str = ', '.join(all_years) if all_years else "noma'lum"
            return f"Davr topilmadi: '{year}'. Mavjud davrlar: {years_str}"

        result_lines = [f"SDMX ID {sdmx_id}: {', '.join(matched_periods)}"]
        result_lines.append(f"O'lchov: {unit}")
        result_lines.append("")

        chart_data = []
        for row in data_section:
            region_name = row.get('Klassifikator') or row.get('Klassifikator_ru') or row.get('Klassifikator_en') or "Ma'lum emas"
            if len(matched_periods) == 1:
                # Single period: one row per region
                period = matched_periods[0]
                value = row.get(period, 'N/A')
                result_lines.append(f"{region_name}: {value} {unit}")
                if value != 'N/A' and value is not None:
                    try:
                        chart_data.append({"label": region_name, "value": float(value)})
                    except (ValueError, TypeError):
                        pass
            else:
                # Year prefix matched multiple sub-periods (e.g. quarters): show each
                result_lines.append(f"{region_name}:")
                for period in matched_periods:
                    value = row.get(period, 'N/A')
                    result_lines.append(f"  {period}: {value} {unit}")

        if chart_data:
            push_chart({
                "chart_type": "bar",
                "title": f"SDMX ID {sdmx_id}: {matched_periods[0]}",
                "unit": unit,
                "data": chart_data,
            })

        return "\n".join(result_lines)

    # Case 4: Both year and region are specified - return single value (original behavior)
    result = extract_value_from_data(data_section, year, region=region)

    if result is None:
        years_str = ', '.join(all_years) if all_years else "noma'lum"
        return f"Ma'lumot topilmadi: SDMX ID {sdmx_id}, davr '{year}', mintaqa '{region}'. Mavjud davrlar: {years_str}"

    region_name = result['region_uz'] or result['region_ru'] or result['region_en'] or "Ma'lum emas"
    matched_period = result['year']  # may differ from `year` if user gave a year prefix
    value = result['value']

    return f"{region_name} {matched_period}: {value} {unit}"


@tool
def get_sdmx_metadata(sdmx_id: int) -> str:
    """
    Get minimal metadata about an SDMX indicator (unit, periodicity, department).

    Use this tool to understand what an SDMX indicator measures before extracting values.
    Returns only essential metadata to minimize context.

    Args:
        sdmx_id: The SDMX identifier

    Returns:
        Essential metadata as a formatted string
    """
    data = load_sdmx_data_file(sdmx_id)

    if data is None:
        return f"Error: SDMX data file for ID {sdmx_id} not found"

    if not isinstance(data, list) or len(data) == 0:
        return f"Error: Invalid data format in SDMX file {sdmx_id}"

    metadata = data[0].get('metadata', [])

    # Extract key metadata fields
    info = {}
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        value_uz = item.get('value_uz', '')

        if 'indicator name' in name_en or 'dataset name' in name_en:
            info['name'] = value_uz
        elif 'periodicity' in name_en:
            info['period'] = value_uz
        elif 'unit of measurement' in name_en:
            info['unit'] = value_uz
        elif 'department' in name_en and 'name of' in name_en:
            info['department'] = value_uz

    # Format minimal response
    lines = [f"SDMX ID {sdmx_id}:"]
    if 'name' in info:
        lines.append(f"  Ko'rsatkich: {info['name']}")
    if 'unit' in info:
        lines.append(f"  O'lchov: {info['unit']}")
    if 'period' in info:
        lines.append(f"  Davr: {info['period']}")

    return "\n".join(lines)


@tool
def calculate_yearly_growth(
    sdmx_id: int,
    start_year: Optional[str] = None,
    end_year: Optional[str] = None,
    region: Optional[str] = None
) -> str:
    """
    Calculate year-over-year growth percentages for an SDMX indicator across multiple years.

    Use this tool when users ask for growth rates, percentage changes, or trends over time.
    Calculates the percentage change from one year to the next.

    Args:
        sdmx_id: The SDMX identifier (e.g., 2441 for population)
        start_year: Optional starting year (e.g., "2020"). If not specified, uses earliest available year.
        end_year: Optional ending year (e.g., "2023"). If not specified, uses latest available year.
        region: Optional region name. If not specified, uses total/national level data.

    Returns:
        Formatted string with year-over-year growth percentages

    Example:
        calculate_yearly_growth(sdmx_id=2441, start_year="2020", end_year="2023")
        Returns table with years and their growth rates
    """
    logger.info(f"Calculating yearly growth for SDMX ID {sdmx_id}")

    # Load the data file
    data = load_sdmx_data_file(sdmx_id)

    if data is None:
        return f"Error: SDMX data file for ID {sdmx_id} not found"

    # Extract the data section and metadata
    if isinstance(data, list) and len(data) > 0:
        data_section = data[0].get('data', [])
        metadata = data[0].get('metadata', [])
    else:
        return f"Error: Invalid data format in SDMX file {sdmx_id}"

    # Extract unit from metadata
    unit = Units.DEFAULT
    indicator_name = ""
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', 'kishi')
        elif 'indicator name' in name_en or 'dataset name' in name_en:
            indicator_name = item.get('value_uz', '')

    # Find the appropriate data row (for region or total)
    target_row = None
    region_name = "O'zbekiston Respublikasi"

    for row in data_section:
        if not isinstance(row, dict):
            continue

        if region:
            # Search for specific region
            region_lower = region.lower()
            klassifikator = str(row.get('Klassifikator', '')).lower()
            klassifikator_ru = str(row.get('Klassifikator_ru', '')).lower()
            klassifikator_en = str(row.get('Klassifikator_en', '')).lower()

            if (region_lower in klassifikator or
                region_lower in klassifikator_ru or
                region_lower in klassifikator_en):
                target_row = row
                region_name = row.get('Klassifikator') or row.get('Klassifikator_ru') or region
                break
        else:
            # Use first row (usually total/national)
            target_row = row
            region_name = row.get('Klassifikator') or row.get('Klassifikator_ru') or "O'zbekiston Respublikasi"
            break

    if target_row is None:
        return f"Ma'lumot topilmadi: SDMX ID {sdmx_id}" + (f", mintaqa '{region}'" if region else "")

    # Extract all available periods and values. Periods may be yearly ("2025"),
    # quarterly ("2025-Q1") or monthly ("2025-M03"); we sort them chronologically.
    period_data: list[tuple[str, float]] = []
    for key, value in target_row.items():
        if _is_period_key(key) and value is not None:
            try:
                period_data.append((key, float(value)))
            except (ValueError, TypeError):
                continue

    period_data.sort(key=lambda p: _period_sort_key(p[0]))

    if len(period_data) < 2:
        return f"Kamida 2 davrlik ma'lumot kerak o'sish foizini hisoblash uchun. Mavjud: {len(period_data)} davr"

    # Filter by start/end. Accept either a bare year ("2020") which becomes a
    # prefix filter, or a full period spec ("2025-Q1") for exact bounds.
    def _bound_year(spec: str) -> int | None:
        m = re.match(r"^(\d{4})", spec)
        return int(m.group(1)) if m else None

    if start_year:
        sy = _bound_year(start_year)
        if sy is not None:
            period_data = [(p, v) for p, v in period_data if _period_sort_key(p)[0] >= sy]
    if end_year:
        ey = _bound_year(end_year)
        if ey is not None:
            period_data = [(p, v) for p, v in period_data if _period_sort_key(p)[0] <= ey]

    if len(period_data) < 2:
        return f"Tanlangan davr uchun kamida 2 ta nuqta kerak. Filtr: {start_year}–{end_year}"

    # Decide the column header based on period granularity
    is_subannual = any("-" in p for p, _ in period_data)
    period_header = "Davr" if is_subannual else "Yil"
    growth_header = "O'sish %" if not is_subannual else "Davr-o'sish %"

    results = []
    _name = indicator_name or "Ko'rsatkich"
    results.append(f"SDMX ID {sdmx_id}: {_name}")
    results.append(f"Mintaqa: {region_name}")
    results.append(f"O'lchov birligi: {unit}")
    results.append("")
    results.append(f"{'Yillik' if not is_subannual else 'Davriy'} o'sish foizlari:")
    results.append("")

    _header = "{:<10} {:<15} {:<14}".format(period_header, "Qiymat", growth_header)
    results.append(_header)
    results.append("-" * 42)

    first_period, first_value = period_data[0]
    results.append(f"{first_period:<10} {first_value:<15.1f} {'-':<14}")

    for i in range(1, len(period_data)):
        period, value = period_data[i]
        _, prev_value = period_data[i - 1]
        if prev_value != 0:
            growth_rate = ((value - prev_value) / prev_value) * 100
            results.append(f"{period:<10} {value:<15.1f} {growth_rate:>+13.2f}%")
        else:
            results.append(f"{period:<10} {value:<15.1f} {'N/A':<14}")

    push_chart({
        "chart_type": "line",
        "title": f"{_name} — {region_name}",
        "unit": unit,
        "data": [{"label": p, "value": v} for p, v in period_data],
    })

    logger.info(f"Calculated growth rates for {len(period_data)} periods")
    return "\n".join(results)
