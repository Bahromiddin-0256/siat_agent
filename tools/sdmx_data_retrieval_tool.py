"""
SDMX Data Retrieval Tool for extracting actual statistical values.

This tool reads local SDMX data files and extracts specific values
based on SDMX ID, year, and region/classifier to minimize LLM context.
"""

import json
from pathlib import Path
from typing import Optional, List

from langchain_core.tools import tool
from core.logger import setup_logger

logger = setup_logger(__name__)


def load_sdmx_data_file(sdmx_id: int, base_dir: str = "jsons/sdmxs") -> Optional[dict]:
    """
    Load SDMX data file from local storage.

    Args:
        sdmx_id: The SDMX identifier
        base_dir: Base directory containing SDMX data files

    Returns:
        Parsed JSON data or None if file not found
    """
    file_path = Path(base_dir) / f"sdmx_data_{sdmx_id}.json"

    if not file_path.exists():
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return None


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

        if region_match and year in row:
            return {
                'code': row.get('Code'),
                'region_uz': row.get('Klassifikator'),
                'region_ru': row.get('Klassifikator_ru'),
                'region_en': row.get('Klassifikator_en'),
                'year': year,
                'value': row.get(year)
            }

    return None


@tool
def get_sdmx_value(sdmx_id: int, year: Optional[str] = None, region: Optional[str] = None) -> str:
    """
    Extract statistical value(s) from SDMX data file with unit.

    Use this tool when you need to get actual statistical numbers from a known SDMX ID.
    This tool reads local data files and extracts values based on the parameters provided.

    Args:
        sdmx_id: The SDMX identifier (e.g., 223 for birth statistics)
        year: Optional year as string (e.g., "2013", "2020")
              - If None: returns all years for the specified region (or first region if region also None)
        region: Optional region name in any language (e.g., "Andijon", "Андижан", "Andijan")
                - If None: returns all regions for the specified year (or first row if year also None)

    Returns:
        A formatted string with the extracted value(s), unit, and context

    Examples:
        get_sdmx_value(sdmx_id=223, year="2013", region="Andijon")
        Returns: "Andijon viloyati 2013-yilda 64239.0 kishi"

        get_sdmx_value(sdmx_id=223, year="2013", region=None)
        Returns: All regions for 2013

        get_sdmx_value(sdmx_id=223, year=None, region="Andijon")
        Returns: Andijon data for all available years

        get_sdmx_value(sdmx_id=223, year=None, region=None)
        Returns: First row with all years
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
    unit = "kishi"  # default
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', 'kishi')
            break

    # Get all year columns
    all_years = []
    if data_section and len(data_section) > 0:
        first_row = data_section[0]
        all_years = sorted([k for k in first_row.keys() if k.isdigit()])

    # Case 1: Both year and region are None - return first row with all years
    if year is None and region is None:
        first_row = data_section[0]
        region_name = first_row.get('Klassifikator') or first_row.get('Klassifikator_ru') or first_row.get('Klassifikator_en') or "Ma'lum emas"

        result_lines = [f"SDMX ID {sdmx_id}: {region_name}"]
        result_lines.append(f"O'lchov: {unit}")
        result_lines.append("")

        for yr in all_years:
            value = first_row.get(yr, 'N/A')
            result_lines.append(f"{yr}: {value} {unit}")

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

        for yr in all_years:
            value = matching_row.get(yr, 'N/A')
            result_lines.append(f"{yr}: {value} {unit}")

        return "\n".join(result_lines)

    # Case 3: region is None, but year is specified - return all regions for that year
    if year is not None and region is None:
        if year not in all_years:
            years_str = ', '.join(all_years) if all_years else "noma'lum"
            return f"Yil topilmadi: '{year}'. Mavjud yillar: {years_str}"

        result_lines = [f"SDMX ID {sdmx_id}: {year}-yil"]
        result_lines.append(f"O'lchov: {unit}")
        result_lines.append("")

        for row in data_section:
            region_name = row.get('Klassifikator') or row.get('Klassifikator_ru') or row.get('Klassifikator_en') or "Ma'lum emas"
            value = row.get(year, 'N/A')
            result_lines.append(f"{region_name}: {value} {unit}")

        return "\n".join(result_lines)

    # Case 4: Both year and region are specified - return single value (original behavior)
    result = extract_value_from_data(data_section, year, region=region)

    if result is None:
        years_str = ', '.join(all_years) if all_years else "noma'lum"
        return f"Ma'lumot topilmadi: SDMX ID {sdmx_id}, yil '{year}', mintaqa '{region}'. Mavjud yillar: {years_str}"

    # Format minimal response with unit
    region_name = result['region_uz'] or result['region_ru'] or result['region_en'] or "Ma'lum emas"
    value = result['value']

    # Return minimal context to LLM with proper unit
    return f"{region_name} {year}-yilda {value} {unit}"


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
    unit = "kishi"  # default
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

    # Extract all available years and values
    year_data = []
    for key, value in target_row.items():
        if key.isdigit() and value is not None:
            try:
                year_data.append((int(key), float(value)))
            except (ValueError, TypeError):
                continue

    # Sort by year
    year_data.sort()

    if len(year_data) < 2:
        return f"Kamida 2 yillik ma'lumot kerak o'sish foizini hisoblash uchun. Mavjud: {len(year_data)} yil"

    # Filter by start_year and end_year if specified
    if start_year:
        try:
            start_yr = int(start_year)
            year_data = [(y, v) for y, v in year_data if y >= start_yr]
        except ValueError:
            pass

    if end_year:
        try:
            end_yr = int(end_year)
            year_data = [(y, v) for y, v in year_data if y <= end_yr]
        except ValueError:
            pass

    if len(year_data) < 2:
        return f"Tanlangan davr uchun kamida 2 yillik ma'lumot kerak. Mavjud yillar: {start_year}-{end_year}"

    # Calculate year-over-year growth rates
    results = []
    results.append(f"SDMX ID {sdmx_id}: {indicator_name or 'Ko\'rsatkich'}")
    results.append(f"Mintaqa: {region_name}")
    results.append(f"O'lchov birligi: {unit}")
    results.append("")
    results.append("Yillik o'sish foizlari:")
    results.append("")

    # Header
    results.append(f"{'Yil':<8} {'Qiymat':<15} {'O\'sish %':<12}")
    results.append("-" * 40)

    # First year (no growth to calculate)
    first_year, first_value = year_data[0]
    results.append(f"{first_year:<8} {first_value:<15.1f} {'-':<12}")

    # Subsequent years with growth rates
    for i in range(1, len(year_data)):
        year, value = year_data[i]
        prev_year, prev_value = year_data[i-1]

        if prev_value != 0:
            growth_rate = ((value - prev_value) / prev_value) * 100
            results.append(f"{year:<8} {value:<15.1f} {growth_rate:>+11.2f}%")
        else:
            results.append(f"{year:<8} {value:<15.1f} {'N/A':<12}")

    logger.info(f"Calculated growth rates for {len(year_data)} years")
    return "\n".join(results)
