# get_sdmx_value Update

## Summary

The `get_sdmx_value` tool has been enhanced to support flexible data retrieval based on optional year and region parameters.

## Changes

### Before (Original Behavior)
```python
get_sdmx_value(sdmx_id: int, year: str, region: Optional[str] = None) -> str
```
- Required: `sdmx_id`, `year`
- Optional: `region`
- Returns: Single value

### After (Enhanced Behavior)
```python
get_sdmx_value(sdmx_id: int, year: Optional[str] = None, region: Optional[str] = None) -> str
```
- Required: `sdmx_id`
- Optional: `year`, `region`
- Returns: Single value, row, column, or entire dataset based on parameters

## Usage Patterns

### 1. Specific Value (year + region)
**Use Case**: Get a single data point

```python
get_sdmx_value(sdmx_id=223, year="2013", region="Andijon")
```

**Returns**:
```
Andijon viloyati 2013-yilda 64239.0 kishi
```

---

### 2. All Regions for a Year (year only)
**Use Case**: Compare all regions for a specific year

```python
get_sdmx_value(sdmx_id=223, year="2013")
# or
get_sdmx_value(sdmx_id=223, year="2013", region=None)
```

**Returns**:
```
SDMX ID 223: 2013-yil
O'lchov: kishi

O'zbekiston Respublikasi: 679519.0 kishi
Qoraqalpog'iston Respublikasi: 39100.0 kishi
Andijon viloyati: 64239.0 kishi
Buxoro viloyati: 36743.0 kishi
...
```

---

### 3. All Years for a Region (region only)
**Use Case**: Show time series for a specific region

```python
get_sdmx_value(sdmx_id=223, region="Andijon")
# or
get_sdmx_value(sdmx_id=223, year=None, region="Andijon")
```

**Returns**:
```
SDMX ID 223: Andijon viloyati
O'lchov: kishi

2010: 59953.0 kishi
2011: 56662.0 kishi
2012: 58277.0 kishi
2013: 64239.0 kishi
2014: 67905.0 kishi
...
2024: 86305.0 kishi
```

---

### 4. First Row, All Years (no year, no region)
**Use Case**: Get national/total data over time

```python
get_sdmx_value(sdmx_id=223)
# or
get_sdmx_value(sdmx_id=223, year=None, region=None)
```

**Returns**:
```
SDMX ID 223: O'zbekiston Respublikasi
O'lchov: kishi

2010: 634810.0 kishi
2011: 622835.0 kishi
2012: 625106.0 kishi
...
2024: 926422.0 kishi
```

## User Query Examples

### Before
❌ User: "Andijon viloyatida 2010-2024 yillarda tug'ilganlar soni"
- Had to manually call get_sdmx_value 15 times (once for each year)
- Or use calculate_statistics (but doesn't show year-by-year data)

### After
✅ User: "Andijon viloyatida 2010-2024 yillarda tug'ilganlar soni"
```python
get_sdmx_value(sdmx_id=223, region="Andijon")
```
- Returns all years in one call!

---

### Before
❌ User: "2023-yilda barcha viloyatlarda tug'ilganlar soni"
- Had to enumerate all regions manually

### After
✅ User: "2023-yilda barcha viloyatlarda tug'ilganlar soni"
```python
get_sdmx_value(sdmx_id=223, year="2023")
```
- Returns all regions in one call!

## System Prompt Update

Updated in `core/agent.py`:

```
9. **get_sdmx_value**: Use this to extract ACTUAL DATA VALUES after finding the SDMX ID.
   Flexible usage:
   - get_sdmx_value(sdmx_id, year, region) → single value
   - get_sdmx_value(sdmx_id, year) → all regions for that year
   - get_sdmx_value(sdmx_id, region=region) → all years for that region
   - get_sdmx_value(sdmx_id) → first row with all years
   Required when user asks "how many", "what is the value", specific numbers, trends over time, etc.
```

## Implementation Details

### File Modified
- `tools/sdmx_data_retrieval_tool.py`

### Logic Flow
```python
if year is None and region is None:
    # Return first row with all years
    return format_row_with_all_years(first_row)

elif year is None and region is not None:
    # Find matching region, return all years
    return format_region_all_years(matching_row)

elif year is not None and region is None:
    # Return all regions for specified year
    return format_all_regions_for_year(year)

else:
    # Both specified - original behavior
    return format_single_value(year, region)
```

## Benefits

1. **Fewer Tool Calls**: Get entire time series or regional comparison in one call
2. **Better UX**: More natural responses to user queries
3. **Backward Compatible**: Original usage (year + region) still works
4. **Flexible**: Supports various data exploration patterns

## Testing

Run the test script:
```bash
python3 test_get_sdmx_value.py
```

All 4 test cases pass successfully!

## Migration Notes

**Existing Code**: No changes needed. The function is backward compatible.

**New Usage**: Can now omit `year` and/or `region` parameters to get aggregated data.
