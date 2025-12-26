"""
SDMX Data Retrieval Tool for extracting actual statistical values.

This tool reads local SDMX data files and extracts specific values
based on SDMX ID, year, and region/classifier to minimize LLM context.
"""

import json
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool


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
def get_sdmx_value(sdmx_id: int, year: str, region: Optional[str] = None) -> str:
    """
    Extract specific statistical value from SDMX data file with unit.

    Use this tool when you need to get actual statistical numbers from a known SDMX ID.
    This tool reads local data files and extracts the exact value for a given year and region,
    along with the correct unit of measurement from metadata.

    Args:
        sdmx_id: The SDMX identifier (e.g., 223 for birth statistics)
        year: Year as string (e.g., "2013", "2020")
        region: Optional region name in any language (e.g., "Andijon", "Андижан", "Andijan")
                If not specified, returns total/national level data

    Returns:
        A minimal string with the extracted value, unit, and context

    Example:
        get_sdmx_value(sdmx_id=223, year="2013", region="Andijon")
        Returns: "Andijon viloyati 2013-yilda 64239.0 kishi"
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

    # Extract unit from metadata
    unit = "kishi"  # default
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', 'kishi')
            break

    # Extract the specific value
    result = extract_value_from_data(data_section, year, region=region)

    if result is None:
        available_years = []
        if data_section and len(data_section) > 0:
            first_row = data_section[0]
            available_years = [k for k in first_row.keys() if k.isdigit()]

        years_str = ', '.join(sorted(available_years)) if available_years else "noma'lum"

        if region:
            return f"Ma'lumot topilmadi: SDMX ID {sdmx_id}, yil '{year}', mintaqa '{region}'. Mavjud yillar: {years_str}"
        else:
            return f"Ma'lumot topilmadi: SDMX ID {sdmx_id}, yil '{year}'. Mavjud yillar: {years_str}"

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
