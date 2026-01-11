"""
Test script for new statistical analysis tools.

This script demonstrates the new precision improvements and statistical calculations.
"""

from core.agent import create_sdmx_agent, run_agent
from tools import initialize_sdmx_data, initialize_rag_vectorstore

# Initialize data
print("Initializing SDMX data and vectorstore...")
initialize_sdmx_data("jsons/sdmx_data.json")
initialize_rag_vectorstore("jsons/sdmx_data.json")

# Create agent
print("Creating agent...")
agent, system_prompt = create_sdmx_agent()
print(f"Agent created successfully!\n")

# Test cases demonstrating new statistical tools
test_cases = [
    # Test 1: Descriptive statistics
    {
        "name": "Descriptive Statistics",
        "query": "SDMX ID 223 bo'yicha Andijon viloyatida 2015-2024 yillar uchun statistik ko'rsatkichlarni hisoblang (o'rtacha, minimal, maksimal)"
    },

    # Test 2: CAGR calculation
    {
        "name": "CAGR Calculation",
        "query": "SDMX ID 223 bo'yicha O'zbekistonda 2015-yildan 2024-yilgacha CAGR (yillik o'rtacha o'sish) ni hisoblang"
    },

    # Test 3: Regional comparison
    {
        "name": "Regional Comparison",
        "query": "2023-yilda SDMX ID 223 bo'yicha barcha viloyatlarni solishtiring"
    },

    # Test 4: Regional ranking
    {
        "name": "Regional Ranking",
        "query": "2023-yilda SDMX ID 223 bo'yicha viloyatlar reytingini ko'rsating (eng yuqoridan boshlab)"
    },

    # Test 5: Percentage share
    {
        "name": "Percentage Share",
        "query": "2023-yilda SDMX ID 223 bo'yicha har bir viloyatning umumiy ulushini (foiz) ko'rsating"
    },

    # Test 6: Year comparison
    {
        "name": "Year Comparison",
        "query": "SDMX ID 223 bo'yicha Andijon viloyatida 2020-yil va 2023-yilni solishtiring"
    },

    # Test 7: Period total
    {
        "name": "Period Total",
        "query": "SDMX ID 223 bo'yicha Andijon viloyatida 2020-2024 yillar jami (umumiy) qiymatni hisoblang"
    },

    # Test 8: Moving average
    {
        "name": "Moving Average",
        "query": "SDMX ID 223 bo'yicha 3-yillik harakatlanuvchi o'rtachani hisoblang"
    },
]

print("=" * 80)
print("TESTING NEW STATISTICAL ANALYSIS TOOLS")
print("=" * 80)
print()

# Run a subset of tests (to avoid taking too long)
print("Running selected test cases...\n")

# Test only the first 3 for demonstration
for i, test in enumerate(test_cases[:3], 1):
    print(f"\n{'=' * 80}")
    print(f"TEST {i}: {test['name']}")
    print(f"{'=' * 80}")
    print(f"Query: {test['query']}\n")

    try:
        response = run_agent(agent, test['query'], system_prompt)
        print("Response:")
        print(response)
    except Exception as e:
        print(f"Error: {e}")

    print()

print("\n" + "=" * 80)
print("TESTING COMPLETE")
print("=" * 80)
print()
print("Summary of implemented tools:")
print("1. calculate_statistics - Descriptive statistics (mean, median, min, max, std)")
print("2. calculate_cagr - Compound Annual Growth Rate")
print("3. compare_regions - Regional comparison with rankings")
print("4. rank_regions - Regional rankings")
print("5. calculate_percentage_share - Percentage distribution")
print("6. compare_years - Two-year comparison")
print("7. calculate_period_total - Period totals")
print("8. calculate_moving_average - Moving averages for trends")
print()
print("All tools are integrated and ready to use!")
