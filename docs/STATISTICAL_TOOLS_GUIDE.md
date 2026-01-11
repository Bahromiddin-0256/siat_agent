# SDMX Agent Statistical Tools Guide

## Overview

This guide covers the new statistical analysis tools and precision improvements implemented for the SDMX agent.

## Precision Improvements

### 1. Enhanced Validation Rules

The agent now includes strict validation:
- **Indicator verification**: Confirms SDMX ID matches user intent before extraction
- **Ambiguity handling**: Lists all variants when multiple similar indicators exist
- **Data availability checks**: Validates year ranges and region names before calculations
- **Unit inclusion**: Always shows measurement units in responses
- **Structured output**: Includes indicator name, SDMX ID, region, year(s), and unit

### 2. Smart Tool Selection

The agent now maps Uzbek/Russian/English keywords to appropriate tools:
- "o'rtacha" / "average" → calculate_statistics
- "eng yuqori" / "eng past" → rank_regions
- "solishtirish" / "compare" + regions → compare_regions
- "solishtirish" / "compare" + years → compare_years
- "ulush" / "share" → calculate_percentage_share
- "jami" / "total" → calculate_period_total
- "CAGR" / "yillik o'rtacha o'sish" → calculate_cagr
- "trend" / "silliq" → calculate_moving_average
- "reyting" / "ranking" → rank_regions

---

## Statistical Tools

### 1. Descriptive Statistics (`calculate_statistics`)

**Purpose**: Calculate mean, median, min, max, standard deviation, and total over a time period.

**Use when**:
- Users ask for averages, minimums, maximums
- Need statistical summary of a time series
- Want to understand data distribution

**Example queries**:
```
"SDMX ID 223 bo'yicha 2015-2024 yillar uchun statistik ko'rsatkichlar"
"Andijon viloyatida tug'ilganlar soni o'rtacha qiymati 2015-2020"
"Calculate statistics for births in 2015-2024"
```

**Output includes**:
- Mean (o'rtacha)
- Median (mediana)
- Minimum value
- Maximum value
- Standard deviation (if 2+ years)
- Total sum
- Year-by-year breakdown

---

### 2. Compound Annual Growth Rate (`calculate_cagr`)

**Purpose**: Calculate the average annual growth rate over multiple years.

**Use when**:
- Need long-term growth trends
- Comparing growth across different indicators
- Understanding compound growth effects

**Formula**: CAGR = ((End Value / Start Value)^(1/n) - 1) × 100

**Example queries**:
```
"SDMX ID 223 bo'yicha 2015-2024 CAGR"
"Yillik o'rtacha o'sish foizi 2010-2023"
"Calculate compound annual growth rate for population"
```

**Output includes**:
- Starting value and year
- Ending value and year
- Number of years
- CAGR percentage
- Interpretation (growth or decline)

---

### 3. Regional Comparison (`compare_regions`)

**Purpose**: Compare multiple regions for a specific year.

**Use when**:
- Need to compare all regions
- Want to see regional distribution
- Comparing specific regions only

**Example queries**:
```
"2023-yilda barcha viloyatlarni solishtiring"
"Compare Andijon and Toshkent regions for 2023"
"Viloyatlar bo'yicha solishtirish 2024"
```

**Output includes**:
- Ranked list of regions
- Absolute values
- Percentage shares
- Total sum

---

### 4. Regional Rankings (`rank_regions`)

**Purpose**: Rank all regions from highest to lowest (or vice versa).

**Use when**:
- Need to see which regions lead/lag
- Want top N regions
- Comparing regional performance

**Example queries**:
```
"2023-yilda eng yuqori ko'rsatkichga ega viloyatlar"
"Rank regions by births in 2024"
"Top 10 viloyatlar reytingi"
```

**Output includes**:
- Ranking position
- Region name
- Value
- Optional: limit to top N

---

### 5. Percentage Share Distribution (`calculate_percentage_share`)

**Purpose**: Calculate each region's percentage of the total.

**Use when**:
- Need relative distribution
- Want to see regional shares
- Understanding proportional representation

**Example queries**:
```
"Har bir viloyatning ulushi (foiz)"
"Percentage distribution across regions for 2023"
"Viloyatlar bo'yicha taqsimot 2024"
```

**Output includes**:
- Region names
- Absolute values
- Percentage shares
- Visual bar chart
- Total sum

---

### 6. Year-over-Year Comparison (`compare_years`)

**Purpose**: Compare two specific years with absolute and percentage change.

**Use when**:
- Need to compare exactly two years
- Want to see specific period change
- Analyzing year-to-year differences

**Example queries**:
```
"2020-yil va 2023-yilni solishtiring"
"Compare 2015 vs 2024"
"2019 va 2023 orasidagi farq"
```

**Output includes**:
- Value in year 1
- Value in year 2
- Absolute change
- Percentage change
- Summary (growth or decline)

---

### 7. Period Total (`calculate_period_total`)

**Purpose**: Calculate total sum across multiple years.

**Use when**:
- Need cumulative totals
- Summing over a period
- Understanding total impact

**Example queries**:
```
"2015-2024 yillar jami"
"Total births from 2020 to 2023"
"Umumiy qiymat 2015-2020"
```

**Output includes**:
- Year-by-year values
- Total sum for period
- Average per year

---

### 8. Moving Average (`calculate_moving_average`)

**Purpose**: Calculate smoothed trends to remove short-term fluctuations.

**Use when**:
- Need to see long-term trends
- Want to smooth noisy data
- Analyzing patterns over time

**Example queries**:
```
"3-yillik harakatlanuvchi o'rtacha"
"5-year moving average for births"
"Silliq trend ko'rsating"
```

**Output includes**:
- Actual values
- Smoothed values (moving average)
- Side-by-side comparison
- Customizable window size (default: 3 years)

---

## Usage Examples

### Example 1: Comprehensive Regional Analysis

```python
# 1. Find the indicator
"Tug'ilganlar soni ko'rsatkichini toping"

# 2. Get descriptive statistics
"SDMX ID 223 bo'yicha 2015-2024 statistik ko'rsatkichlar"

# 3. Compare all regions
"2023-yilda SDMX ID 223 bo'yicha viloyatlarni solishtiring"

# 4. Show percentage distribution
"Har bir viloyatning ulushini ko'rsating"

# 5. Rank regions
"Viloyatlar reytingi 2023"
```

### Example 2: Time Series Trend Analysis

```python
# 1. Calculate year-over-year growth
"SDMX ID 2441 yillik o'sish foizlari 2015-2024"

# 2. Calculate CAGR
"SDMX ID 2441 CAGR 2015-2024"

# 3. Show moving average for smooth trend
"3-yillik harakatlanuvchi o'rtacha"

# 4. Compare specific years
"2015 va 2024 yillarni solishtiring"
```

### Example 3: Regional Focus

```python
# 1. Get statistics for specific region
"Andijon viloyatida 2015-2024 statistika"

# 2. Calculate period total
"Andijon 2015-2024 jami"

# 3. Compare with another region
"Andijon va Toshkent solishtirmasi 2023"
```

---

## Technical Details

### File Structure

```
tools/
  ├── sdmx_tool.py                    # Search and discovery tools
  ├── sdmx_data_retrieval_tool.py     # Data extraction tools
  └── sdmx_statistics_tool.py         # NEW: Statistical analysis tools

core/
  └── agent.py                        # Agent with enhanced prompt
```

### Tool Categories

1. **Search Tools**: `search_sdmx_semantic`, `get_sdmx_id`, etc.
2. **Data Tools**: `get_sdmx_value`, `get_sdmx_metadata`
3. **Growth Tools**: `calculate_yearly_growth`, `calculate_cagr`
4. **Statistical Tools**: `calculate_statistics`, `calculate_moving_average`
5. **Regional Tools**: `compare_regions`, `rank_regions`, `calculate_percentage_share`
6. **Comparison Tools**: `compare_years`, `calculate_period_total`

### Total Tools: 16
- 5 Search and discovery tools
- 2 Data extraction tools
- 9 Statistical and analysis tools

---

## Best Practices

1. **Always specify time range**: Include start and end years for accurate calculations
2. **Be specific about regions**: Mention exact region names or "barcha viloyatlar" for all
3. **Use appropriate tool keywords**: Helps agent select the right statistical function
4. **Check units**: Verify the measurement unit matches expectations
5. **Validate results**: Agent will warn if data is missing or invalid

---

## Testing

Run the test script to verify all tools:

```bash
python test_statistics.py
```

This will demonstrate:
- Descriptive statistics calculation
- CAGR calculation
- Regional comparisons
- And more...

---

## Summary

The enhanced SDMX agent now provides:

✅ **8 new statistical tools** for comprehensive analysis
✅ **Improved precision** with validation and disambiguation
✅ **Smart keyword mapping** for Uzbek/Russian/English queries
✅ **Structured outputs** with clear formatting
✅ **Better error handling** with helpful messages

All tools are production-ready and integrated into the main agent!
