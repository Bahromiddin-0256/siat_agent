"""
SDMX Statistical Analysis Tools.

This module provides advanced statistical calculations for SDMX data including
descriptive statistics, CAGR, regional comparisons, rankings, and distributions.
"""

import statistics
from typing import Optional, List, Tuple

from langchain_core.tools import tool
from core.logger import setup_logger
from tools.file_utils import load_sdmx_data_file
from tools.constants import Units

logger = setup_logger(__name__)


def get_time_series_data(
    data_section: list[dict],
    region: Optional[str] = None
) -> Tuple[Optional[str], List[Tuple[int, float]]]:
    """
    Extract time series data for a specific region.

    Args:
        data_section: The data array from SDMX JSON
        region: Region name (if None, uses first row - typically total)

    Returns:
        Tuple of (region_name, [(year, value), ...])
    """
    target_row = None
    region_name = None

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
        return None, []

    # Extract year-value pairs
    year_data = []
    for key, value in target_row.items():
        if key.isdigit() and value is not None:
            try:
                year_data.append((int(key), float(value)))
            except (ValueError, TypeError):
                continue

    year_data.sort()
    return region_name, year_data


def get_all_regions_data(
    data_section: list[dict],
    year: str
) -> List[dict]:
    """
    Extract data for all regions for a specific year.

    Args:
        data_section: The data array from SDMX JSON
        year: Year as string

    Returns:
        List of dicts with region info and values
    """
    regions_data = []

    for row in data_section:
        if not isinstance(row, dict):
            continue

        if year in row and row[year] is not None:
            try:
                value = float(row[year])
                region_name = row.get('Klassifikator') or row.get('Klassifikator_ru') or row.get('Klassifikator_en') or "Unknown"
                regions_data.append({
                    'code': row.get('Code'),
                    'region': region_name,
                    'value': value
                })
            except (ValueError, TypeError):
                continue

    return regions_data


@tool
def calculate_statistics(
    sdmx_id: int,
    start_year: str,
    end_year: str,
    region: Optional[str] = None
) -> str:
    """
    Calculate descriptive statistics over a time period.

    Use this tool when users ask for statistical summaries, averages, minimums, maximums,
    or general statistical analysis over multiple years.

    Args:
        sdmx_id: The SDMX identifier
        start_year: Starting year (e.g., "2015")
        end_year: Ending year (e.g., "2024")
        region: Optional region name. If not specified, uses total/national level data.

    Returns:
        Formatted string with mean, median, min, max, standard deviation, and total

    Keywords: "o'rtacha", "average", "minimal", "maksimal", "statistika", "statistics"

    Example:
        calculate_statistics(sdmx_id=223, start_year="2015", end_year="2024", region="Andijon")
    """
    logger.info(f"Calculating statistics for SDMX ID {sdmx_id}, years {start_year}-{end_year}")

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

    # Extract unit and indicator name from metadata
    unit = Units.DEFAULT
    indicator_name = ""
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', Units.DEFAULT)
        elif 'indicator name' in name_en or 'dataset name' in name_en:
            indicator_name = item.get('value_uz', '')

    # Get time series data
    region_name, year_data = get_time_series_data(data_section, region)

    if not year_data:
        return f"Ma'lumot topilmadi: SDMX ID {sdmx_id}" + (f", mintaqa '{region}'" if region else "")

    # Filter by year range
    try:
        start_yr = int(start_year)
        end_yr = int(end_year)
        filtered_data = [(y, v) for y, v in year_data if start_yr <= y <= end_yr]
    except ValueError:
        return f"Noto'g'ri yil formati: '{start_year}' yoki '{end_year}'"

    if len(filtered_data) < 1:
        return f"Tanlangan davr uchun ma'lumot topilmadi: {start_year}-{end_year}"

    # Extract values for statistics
    values = [v for _, v in filtered_data]

    # Calculate statistics
    mean = statistics.mean(values)
    median = statistics.median(values)
    min_val = min(values)
    max_val = max(values)
    total = sum(values)

    # Standard deviation (only if 2+ values)
    std_dev = statistics.stdev(values) if len(values) >= 2 else 0

    # Format results
    results = []
    _name = indicator_name or "Ko'rsatkich"
    results.append(f"SDMX ID {sdmx_id}: {_name}")
    results.append(f"Mintaqa: {region_name}")
    results.append(f"Davr: {start_year}-{end_year} ({len(filtered_data)} yil)")
    results.append(f"O'lchov birligi: {unit}")
    results.append("")
    results.append("Statistik ko'rsatkichlar:")
    results.append("-" * 50)
    results.append(f"O'rtacha (Mean):           {mean:,.2f} {unit}")
    results.append(f"Mediana (Median):          {median:,.2f} {unit}")
    results.append(f"Minimal qiymat (Min):      {min_val:,.2f} {unit}")
    results.append(f"Maksimal qiymat (Max):     {max_val:,.2f} {unit}")
    if len(values) >= 2:
        results.append(f"Standart og'ish (Std Dev): {std_dev:,.2f} {unit}")
    results.append(f"Jami (Total):              {total:,.2f} {unit}")

    # Add year range details
    results.append("")
    results.append("Qiymatlar:")
    for year, value in filtered_data:
        results.append(f"  {year}: {value:,.2f} {unit}")

    logger.info(f"Calculated statistics for {len(filtered_data)} years")
    return "\n".join(results)


@tool
def calculate_cagr(
    sdmx_id: int,
    start_year: str,
    end_year: str,
    region: Optional[str] = None
) -> str:
    """
    Calculate Compound Annual Growth Rate (CAGR) between two years.

    Use this tool when users ask for average annual growth rate over a period,
    compound growth, or long-term growth trends.

    Args:
        sdmx_id: The SDMX identifier
        start_year: Starting year (e.g., "2015")
        end_year: Ending year (e.g., "2024")
        region: Optional region name. If not specified, uses total/national level data.

    Returns:
        Formatted string with CAGR percentage

    Formula: CAGR = ((End Value / Start Value)^(1/n) - 1) * 100
    where n = number of years

    Keywords: "CAGR", "yillik o'rtacha o'sish", "compound growth", "murakkab o'sish"

    Example:
        calculate_cagr(sdmx_id=223, start_year="2015", end_year="2024")
    """
    logger.info(f"Calculating CAGR for SDMX ID {sdmx_id}, years {start_year}-{end_year}")

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

    # Extract unit and indicator name from metadata
    unit = Units.DEFAULT
    indicator_name = ""
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', Units.DEFAULT)
        elif 'indicator name' in name_en or 'dataset name' in name_en:
            indicator_name = item.get('value_uz', '')

    # Get time series data
    region_name, year_data = get_time_series_data(data_section, region)

    if not year_data:
        return f"Ma'lumot topilmadi: SDMX ID {sdmx_id}" + (f", mintaqa '{region}'" if region else "")

    # Find start and end values
    try:
        start_yr = int(start_year)
        end_yr = int(end_year)
    except ValueError:
        return f"Noto'g'ri yil formati: '{start_year}' yoki '{end_year}'"

    start_value = None
    end_value = None

    for year, value in year_data:
        if year == start_yr:
            start_value = value
        if year == end_yr:
            end_value = value

    if start_value is None:
        return f"Ma'lumot topilmadi {start_year}-yil uchun"
    if end_value is None:
        return f"Ma'lumot topilmadi {end_year}-yil uchun"
    if start_value <= 0:
        return f"CAGR ni hisoblash mumkin emas: boshlang'ich qiymat nol yoki manfiy ({start_value})"

    # Calculate CAGR
    n_years = end_yr - start_yr
    if n_years <= 0:
        return "Yakuniy yil boshlang'ich yildan katta bo'lishi kerak"

    cagr = (((end_value / start_value) ** (1 / n_years)) - 1) * 100

    # Format results
    results = []
    _name = indicator_name or "Ko'rsatkich"
    results.append(f"SDMX ID {sdmx_id}: {_name}")
    results.append(f"Mintaqa: {region_name}")
    results.append(f"O'lchov birligi: {unit}")
    results.append("")
    results.append("CAGR (Compound Annual Growth Rate):")
    results.append("-" * 50)
    results.append(f"Boshlang'ich yil ({start_year}):  {start_value:,.2f} {unit}")
    results.append(f"Yakuniy yil ({end_year}):         {end_value:,.2f} {unit}")
    results.append(f"Davr:                            {n_years} yil")
    results.append(f"CAGR:                            {cagr:+.2f}%")
    results.append("")
    _trend = "o'sish" if cagr > 0 else "kamayish"
    results.append(f"Izoh: Yiliga o'rtacha {abs(cagr):.2f}% {_trend}")

    logger.info(f"Calculated CAGR: {cagr:.2f}%")
    return "\n".join(results)


@tool
def compare_regions(
    sdmx_id: int,
    year: str,
    regions: Optional[List[str]] = None
) -> str:
    """
    Compare statistical values across multiple regions for a specific year.

    Use this tool when users want to compare different regions, see regional differences,
    or analyze geographic distribution of an indicator.

    Args:
        sdmx_id: The SDMX identifier
        year: Year as string (e.g., "2023")
        regions: Optional list of specific regions to compare. If None, compares all regions.

    Returns:
        Formatted table with regions and their values, sorted by value

    Keywords: "solishtirish", "compare", "viloyatlar", "regions", "mintaqalar"

    Example:
        compare_regions(sdmx_id=223, year="2023", regions=["Andijon", "Toshkent"])
        compare_regions(sdmx_id=223, year="2023")  # Compare all regions
    """
    logger.info(f"Comparing regions for SDMX ID {sdmx_id}, year {year}")

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

    # Extract unit and indicator name from metadata
    unit = Units.DEFAULT
    indicator_name = ""
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', Units.DEFAULT)
        elif 'indicator name' in name_en or 'dataset name' in name_en:
            indicator_name = item.get('value_uz', '')

    # Get all regions data for the year
    regions_data = get_all_regions_data(data_section, year)

    if not regions_data:
        return f"Ma'lumot topilmadi {year}-yil uchun"

    # Filter by specific regions if provided
    if regions:
        regions_lower = [r.lower() for r in regions]
        filtered_data = [
            r for r in regions_data
            if any(reg in r['region'].lower() for reg in regions_lower)
        ]
        if not filtered_data:
            return f"Ko'rsatilgan mintaqalar uchun ma'lumot topilmadi: {', '.join(regions)}"
        regions_data = filtered_data

    # Sort by value (descending)
    regions_data.sort(key=lambda x: x['value'], reverse=True)

    # Calculate total
    total = sum(r['value'] for r in regions_data)

    # Format results
    results = []
    _name = indicator_name or "Ko'rsatkich"
    results.append(f"SDMX ID {sdmx_id}: {_name}")
    results.append(f"Yil: {year}")
    results.append(f"O'lchov birligi: {unit}")
    results.append("")
    results.append("Mintaqalar bo'yicha solishtirish:")
    results.append("-" * 70)
    results.append(f"{'#':<4} {'Mintaqa':<30} {'Qiymat':>15} {'Ulush %':>10}")
    results.append("-" * 70)

    for idx, region_data in enumerate(regions_data, 1):
        percentage = (region_data['value'] / total * 100) if total > 0 else 0
        results.append(
            f"{idx:<4} {region_data['region']:<30} {region_data['value']:>15,.2f} {percentage:>9.2f}%"
        )

    results.append("-" * 70)
    results.append(f"{'JAMI':<4} {'':30} {total:>15,.2f} {100.0:>9.2f}%")

    logger.info(f"Compared {len(regions_data)} regions")
    return "\n".join(results)


@tool
def rank_regions(
    sdmx_id: int,
    year: str,
    ascending: bool = False,
    top_n: Optional[int] = None
) -> str:
    """
    Rank all regions by indicator value for a specific year.

    Use this tool when users ask for rankings, top regions, highest/lowest values,
    or want to see which regions lead in a particular indicator.

    Args:
        sdmx_id: The SDMX identifier
        year: Year as string (e.g., "2023")
        ascending: If True, ranks from lowest to highest. Default is False (highest to lowest)
        top_n: Optional limit to show only top N regions

    Returns:
        Ordered list of regions ranked by value

    Keywords: "reyting", "ranking", "eng yuqori", "eng past", "top", "birinchi o'rin"

    Example:
        rank_regions(sdmx_id=223, year="2023")  # All regions, highest first
        rank_regions(sdmx_id=223, year="2023", top_n=10)  # Top 10 regions
        rank_regions(sdmx_id=223, year="2023", ascending=True)  # Lowest first
    """
    logger.info(f"Ranking regions for SDMX ID {sdmx_id}, year {year}")

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

    # Extract unit and indicator name from metadata
    unit = Units.DEFAULT
    indicator_name = ""
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', Units.DEFAULT)
        elif 'indicator name' in name_en or 'dataset name' in name_en:
            indicator_name = item.get('value_uz', '')

    # Get all regions data for the year
    regions_data = get_all_regions_data(data_section, year)

    if not regions_data:
        return f"Ma'lumot topilmadi {year}-yil uchun"

    # Sort by value
    regions_data.sort(key=lambda x: x['value'], reverse=not ascending)

    # Limit to top_n if specified
    if top_n and top_n > 0:
        regions_data = regions_data[:top_n]

    # Format results
    results = []
    _name = indicator_name or "Ko'rsatkich"
    results.append(f"SDMX ID {sdmx_id}: {_name}")
    results.append(f"Yil: {year}")
    results.append(f"O'lchov birligi: {unit}")
    results.append(f"Tartiblash: {'Eng past' if ascending else 'Eng yuqori'} → {'Eng yuqori' if ascending else 'Eng past'}")
    results.append("")
    results.append("Reyting:")
    results.append("-" * 60)
    _rank_header = "{:<6} {:<35} {:>15}".format("O'rin", "Mintaqa", "Qiymat")
    results.append(_rank_header)
    results.append("-" * 60)

    for idx, region_data in enumerate(regions_data, 1):
        results.append(
            f"{idx:<6} {region_data['region']:<35} {region_data['value']:>15,.2f}"
        )

    logger.info(f"Ranked {len(regions_data)} regions")
    return "\n".join(results)


@tool
def calculate_percentage_share(
    sdmx_id: int,
    year: str
) -> str:
    """
    Calculate each region's percentage share of the total.

    Use this tool when users ask about regional distribution, what percentage each region
    represents, or relative shares.

    Args:
        sdmx_id: The SDMX identifier
        year: Year as string (e.g., "2023")

    Returns:
        Table showing absolute values and percentage shares for all regions

    Keywords: "ulush", "foiz", "percentage share", "distribution", "taqsimot"

    Example:
        calculate_percentage_share(sdmx_id=223, year="2023")
    """
    logger.info(f"Calculating percentage shares for SDMX ID {sdmx_id}, year {year}")

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

    # Extract unit and indicator name from metadata
    unit = Units.DEFAULT
    indicator_name = ""
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', Units.DEFAULT)
        elif 'indicator name' in name_en or 'dataset name' in name_en:
            indicator_name = item.get('value_uz', '')

    # Get all regions data for the year
    regions_data = get_all_regions_data(data_section, year)

    if not regions_data:
        return f"Ma'lumot topilmadi {year}-yil uchun"

    # Calculate total
    total = sum(r['value'] for r in regions_data)

    # Sort by percentage share (descending)
    regions_data.sort(key=lambda x: x['value'], reverse=True)

    # Format results
    results = []
    _name = indicator_name or "Ko'rsatkich"
    results.append(f"SDMX ID {sdmx_id}: {_name}")
    results.append(f"Yil: {year}")
    results.append(f"O'lchov birligi: {unit}")
    results.append("")
    results.append("Mintaqalar bo'yicha taqsimot:")
    results.append("-" * 75)
    results.append(f"{'Mintaqa':<35} {'Qiymat':>15} {'Ulush %':>10} {'Grafik':>10}")
    results.append("-" * 75)

    for region_data in regions_data:
        percentage = (region_data['value'] / total * 100) if total > 0 else 0
        # Simple bar chart (each █ represents ~2%)
        bar_length = int(percentage / 2)
        bar = "█" * bar_length
        results.append(
            f"{region_data['region']:<35} {region_data['value']:>15,.2f} {percentage:>9.2f}% {bar}"
        )

    results.append("-" * 75)
    results.append(f"{'JAMI':<35} {total:>15,.2f} {100.0:>9.2f}%")

    logger.info(f"Calculated shares for {len(regions_data)} regions")
    return "\n".join(results)


@tool
def compare_years(
    sdmx_id: int,
    year1: str,
    year2: str,
    region: Optional[str] = None
) -> str:
    """
    Compare two specific years with absolute and percentage change.

    Use this tool when users want to compare two specific years, see how much changed
    between two points in time.

    Args:
        sdmx_id: The SDMX identifier
        year1: First year (e.g., "2020")
        year2: Second year (e.g., "2023")
        region: Optional region name. If not specified, uses total/national level data.

    Returns:
        Comparison showing values for both years, absolute change, and percentage change

    Keywords: "solishtir", "compare", "farq", "difference", "o'zgarish", "change"

    Example:
        compare_years(sdmx_id=223, year1="2020", year2="2023")
        compare_years(sdmx_id=223, year1="2020", year2="2023", region="Andijon")
    """
    logger.info(f"Comparing years {year1} vs {year2} for SDMX ID {sdmx_id}")

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

    # Extract unit and indicator name from metadata
    unit = Units.DEFAULT
    indicator_name = ""
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', Units.DEFAULT)
        elif 'indicator name' in name_en or 'dataset name' in name_en:
            indicator_name = item.get('value_uz', '')

    # Get time series data
    region_name, year_data = get_time_series_data(data_section, region)

    if not year_data:
        return f"Ma'lumot topilmadi: SDMX ID {sdmx_id}" + (f", mintaqa '{region}'" if region else "")

    # Find values for both years
    try:
        yr1 = int(year1)
        yr2 = int(year2)
    except ValueError:
        return f"Noto'g'ri yil formati: '{year1}' yoki '{year2}'"

    value1 = None
    value2 = None

    for year, value in year_data:
        if year == yr1:
            value1 = value
        if year == yr2:
            value2 = value

    if value1 is None:
        return f"Ma'lumot topilmadi {year1}-yil uchun"
    if value2 is None:
        return f"Ma'lumot topilmadi {year2}-yil uchun"

    # Calculate changes
    absolute_change = value2 - value1
    percentage_change = (absolute_change / value1 * 100) if value1 != 0 else 0

    # Format results
    results = []
    _name = indicator_name or "Ko'rsatkich"
    results.append(f"SDMX ID {sdmx_id}: {_name}")
    results.append(f"Mintaqa: {region_name}")
    results.append(f"O'lchov birligi: {unit}")
    results.append("")
    results.append(f"Yillar solishtirmasi: {year1} vs {year2}")
    results.append("-" * 60)
    results.append(f"{year1}-yil:                     {value1:>15,.2f} {unit}")
    results.append(f"{year2}-yil:                     {value2:>15,.2f} {unit}")
    results.append("-" * 60)
    results.append(f"Absolut o'zgarish:          {absolute_change:>+15,.2f} {unit}")
    results.append(f"Foiz o'zgarishi:            {percentage_change:>+15,.2f}%")
    results.append("")

    if absolute_change > 0:
        results.append(f"Xulosa: {year1}-yildan {year2}-yilga {abs(percentage_change):.2f}% o'sish")
    elif absolute_change < 0:
        results.append(f"Xulosa: {year1}-yildan {year2}-yilga {abs(percentage_change):.2f}% kamayish")
    else:
        results.append(f"Xulosa: {year1}-yil va {year2}-yil o'zgarish yo'q")

    logger.info(f"Compared {year1} vs {year2}: {percentage_change:+.2f}%")
    return "\n".join(results)


@tool
def calculate_period_total(
    sdmx_id: int,
    start_year: str,
    end_year: str,
    region: Optional[str] = None
) -> str:
    """
    Calculate total sum across a time period.

    Use this tool for cumulative statistics, when users want to know the total across
    multiple years (e.g., total births over 5 years).

    Args:
        sdmx_id: The SDMX identifier
        start_year: Starting year (e.g., "2015")
        end_year: Ending year (e.g., "2024")
        region: Optional region name. If not specified, uses total/national level data.

    Returns:
        Total sum for the period with year-by-year breakdown

    Keywords: "jami", "umumiy", "total", "sum", "yig'indi"

    Example:
        calculate_period_total(sdmx_id=223, start_year="2015", end_year="2024")
    """
    logger.info(f"Calculating period total for SDMX ID {sdmx_id}, years {start_year}-{end_year}")

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

    # Extract unit and indicator name from metadata
    unit = Units.DEFAULT
    indicator_name = ""
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', Units.DEFAULT)
        elif 'indicator name' in name_en or 'dataset name' in name_en:
            indicator_name = item.get('value_uz', '')

    # Get time series data
    region_name, year_data = get_time_series_data(data_section, region)

    if not year_data:
        return f"Ma'lumot topilmadi: SDMX ID {sdmx_id}" + (f", mintaqa '{region}'" if region else "")

    # Filter by year range
    try:
        start_yr = int(start_year)
        end_yr = int(end_year)
        filtered_data = [(y, v) for y, v in year_data if start_yr <= y <= end_yr]
    except ValueError:
        return f"Noto'g'ri yil formati: '{start_year}' yoki '{end_year}'"

    if len(filtered_data) < 1:
        return f"Tanlangan davr uchun ma'lumot topilmadi: {start_year}-{end_year}"

    # Calculate total
    total = sum(v for _, v in filtered_data)
    average = total / len(filtered_data)

    # Format results
    results = []
    _name = indicator_name or "Ko'rsatkich"
    results.append(f"SDMX ID {sdmx_id}: {_name}")
    results.append(f"Mintaqa: {region_name}")
    results.append(f"Davr: {start_year}-{end_year} ({len(filtered_data)} yil)")
    results.append(f"O'lchov birligi: {unit}")
    results.append("")
    results.append("Davr bo'yicha jami:")
    results.append("-" * 50)

    for year, value in filtered_data:
        results.append(f"  {year}: {value:>15,.2f} {unit}")

    results.append("-" * 50)
    results.append(f"JAMI ({start_year}-{end_year}):  {total:>15,.2f} {unit}")
    results.append(f"O'rtacha yillik:                {average:>15,.2f} {unit}")

    logger.info(f"Calculated period total: {total:,.2f}")
    return "\n".join(results)


@tool
def calculate_moving_average(
    sdmx_id: int,
    window: int = 3,
    start_year: Optional[str] = None,
    end_year: Optional[str] = None,
    region: Optional[str] = None
) -> str:
    """
    Calculate moving average (smoothed trend) over time.

    Use this tool when users want to see smoothed trends, remove short-term fluctuations,
    or analyze long-term patterns.

    Args:
        sdmx_id: The SDMX identifier
        window: Number of years for averaging window (default 3)
        start_year: Optional starting year
        end_year: Optional ending year
        region: Optional region name. If not specified, uses total/national level data.

    Returns:
        Table with actual values and moving averages

    Keywords: "trend", "silliq o'sish", "smoothed", "harakatlanuvchi o'rtacha", "moving average"

    Example:
        calculate_moving_average(sdmx_id=223, window=3)
        calculate_moving_average(sdmx_id=223, window=5, start_year="2015", end_year="2024")
    """
    logger.info(f"Calculating {window}-year moving average for SDMX ID {sdmx_id}")

    if window < 2:
        return "Oyna (window) kamida 2 bo'lishi kerak"

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

    # Extract unit and indicator name from metadata
    unit = Units.DEFAULT
    indicator_name = ""
    for item in metadata:
        name_en = item.get('name_en', '').lower()
        if 'unit of measurement' in name_en or 'unit' in name_en:
            unit = item.get('value_uz', Units.DEFAULT)
        elif 'indicator name' in name_en or 'dataset name' in name_en:
            indicator_name = item.get('value_uz', '')

    # Get time series data
    region_name, year_data = get_time_series_data(data_section, region)

    if not year_data:
        return f"Ma'lumot topilmadi: SDMX ID {sdmx_id}" + (f", mintaqa '{region}'" if region else "")

    # Filter by year range if specified
    if start_year or end_year:
        try:
            start_yr = int(start_year) if start_year else year_data[0][0]
            end_yr = int(end_year) if end_year else year_data[-1][0]
            year_data = [(y, v) for y, v in year_data if start_yr <= y <= end_yr]
        except ValueError:
            return f"Noto'g'ri yil formati"

    if len(year_data) < window:
        return f"Harakatlanuvchi o'rtachani hisoblash uchun kamida {window} yillik ma'lumot kerak. Mavjud: {len(year_data)} yil"

    # Calculate moving averages
    moving_avgs = []
    for i in range(len(year_data) - window + 1):
        window_data = year_data[i:i + window]
        avg = sum(v for _, v in window_data) / window
        center_year = window_data[window // 2][0]  # Use middle year
        moving_avgs.append((center_year, avg))

    # Format results
    results = []
    _name = indicator_name or "Ko'rsatkich"
    results.append(f"SDMX ID {sdmx_id}: {_name}")
    results.append(f"Mintaqa: {region_name}")
    results.append(f"O'lchov birligi: {unit}")
    results.append(f"Oyna: {window} yil")
    results.append("")
    results.append(f"{window}-yillik harakatlanuvchi o'rtacha:")
    results.append("-" * 60)
    results.append(f"{'Yil':<8} {'Haqiqiy qiymat':>18} {'Silliq qiymat':>18}")
    results.append("-" * 60)

    # Create a mapping of years to moving averages
    ma_dict = {year: avg for year, avg in moving_avgs}

    for year, value in year_data:
        if year in ma_dict:
            results.append(f"{year:<8} {value:>18,.2f} {ma_dict[year]:>18,.2f}")
        else:
            results.append(f"{year:<8} {value:>18,.2f} {'-':>18}")

    logger.info(f"Calculated {window}-year moving average for {len(year_data)} years")
    return "\n".join(results)
