"""
SDMX ID Retriever Tool for LangChain.

This tool searches through hierarchical statistical data and returns
relevant SDMX IDs based on user questions.
"""

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


def load_json_data(json_file_path: str | Path) -> list[dict[str, Any]]:
    """Load JSON data from file."""
    with open(json_file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def search_recursive(
    items: list[dict[str, Any]],
    query_terms: list[str]
) -> list[dict[str, Any]]:
    """
    Recursively search through nested structure for matching items.

    Args:
        items: List of items to search through
        query_terms: List of search terms to match against

    Returns:
        List of matching items with their details
    """
    results = []

    for item in items:
        # Collect all name fields for searching
        name_fields = [
            str(item.get('name', '')).lower(),
            str(item.get('name_uz', '')).lower(),
            str(item.get('name_en', '')).lower(),
            str(item.get('name_ru', '')).lower(),
            str(item.get('name_uzc', '')).lower(),
        ]

        # Also search in tags if available
        tags = item.get('tags') or []
        if isinstance(tags, list):
            name_fields.extend([str(tag).lower() for tag in tags])

        # Check if any query term matches any name field
        matches = any(
            term in field
            for term in query_terms
            for field in name_fields
            if field  # Skip empty fields
        )

        if matches:
            # Only include items that have a code (leaf nodes with actual data)
            result_item = {
                'id': item.get('id'),
                'code': item.get('code'),
                'name': item.get('name'),
                'name_en': item.get('name_en'),
                'name_ru': item.get('name_ru'),
                'period': item.get('period'),
                'department': item.get('department'),
                'status': item.get('status'),
                'updated_at': item.get('updated_at'),
            }
            results.append(result_item)

        # Recursively search in children
        children = item.get('children')
        if children and isinstance(children, list):
            results.extend(search_recursive(children, query_terms))

    return results


# Global variable to store loaded data
_json_data: list[dict[str, Any]] = []


def initialize_sdmx_data(json_file_path: str | Path) -> None:
    """
    Initialize the SDMX data from JSON file.

    Args:
        json_file_path: Path to the JSON file containing SDMX data
    """
    global _json_data
    _json_data = load_json_data(json_file_path)


def _get_sdmx_id(question: str) -> str:
    if not _json_data:
        return "Error: SDMX data not initialized. Call initialize_sdmx_data first."

    # Extract meaningful keywords from the question (words with 2+ characters)
    query_terms = [
        term.lower().strip('?,.:;!')
        for term in question.split()
        if len(term) > 2
    ]

    if not query_terms:
        return "Please provide a more specific question with meaningful keywords."

    # Search through the data
    results = search_recursive(_json_data, query_terms)

    if not results:
        return f"No matching SDMX IDs found for: '{question}'. Try different keywords."

    # Remove duplicates based on ID
    seen_ids = set()
    unique_results = []
    for r in results:
        if r['id'] not in seen_ids:
            seen_ids.add(r['id'])
            unique_results.append(r)

    # Format output
    output_lines = [f"Found {len(unique_results)} matching indicator(s):\n"]

    # Limit to top 15 results for readability
    for idx, result in enumerate(unique_results[:15], 1):
        output_lines.append(f"{idx}. **ID**: {result['id']}")
        output_lines.append(f"   **Code**: {result['code']}")
        output_lines.append(f"   **Name**: {result['name']}")
        if result['name_en']:
            output_lines.append(f"   **English**: {result['name_en']}")
        if result['period']:
            output_lines.append(f"   **Period**: {result['period']}")
        if result['status']:
            output_lines.append(f"   **Status**: {result['status']}")
        output_lines.append("")

    if len(unique_results) > 15:
        output_lines.append(f"... and {len(unique_results) - 15} more results.")

    return "\n".join(output_lines)


@tool
def get_sdmx_id(question: str) -> str:
    """
        Search for SDMX IDs in statistical data based on a question.

        Use this tool when you need to find statistical indicators or datasets.
        The tool searches through economic, social, and demographic statistics
        to find relevant SDMX identifiers.

        Args:
            question: A question or query about statistics (e.g., "GDP quarterly",
                      "population", "inflation", "export import")

        Returns:
            A formatted string with matching SDMX IDs and their details
    """
    return _get_sdmx_id(question)


@tool
def get_sdmx_by_code(code: str) -> str:
    """
    Get detailed information about a specific SDMX indicator by its code.

    Use this tool when you have a specific code and need full details.

    Args:
        code: The SDMX code (e.g., "1.01.01.0001")

    Returns:
        Detailed information about the indicator
    """
    if not _json_data:
        return "Error: SDMX data not initialized. Call initialize_sdmx_data first."

    def find_by_code(items: list[dict], target_code: str) -> dict | None:
        for item in items:
            if item.get('code') == target_code:
                return item
            children = item.get('children')
            if children:
                result = find_by_code(children, target_code)
                if result:
                    return result
        return None

    result = find_by_code(_json_data, code)

    if not result:
        return f"No indicator found with code: {code}\n" + get_sdmx_id(code)

    output_lines = [
        f"**Indicator Details**\n",
        f"**ID**: {result.get('id')}",
        f"**Code**: {result.get('code')}",
        f"**Name (UZ)**: {result.get('name')}",
        f"**Name (EN)**: {result.get('name_en')}",
        f"**Name (RU)**: {result.get('name_ru')}",
        f"**Period**: {result.get('period')}",
        f"**Department**: {result.get('department')}",
        f"**Status**: {result.get('status')}",
        f"**Last Updated**: {result.get('updated_at')}",
        f"**Is Active**: {result.get('is_active')}",
    ]

    return "\n".join(output_lines)


@tool
def list_sdmx_categories() -> str:
    """
    List all top-level SDMX statistical categories.

    Use this tool to get an overview of available statistical domains.

    Returns:
        List of main statistical categories with their codes
    """
    if not _json_data:
        return "Error: SDMX data not initialized. Call initialize_sdmx_data first."

    output_lines = ["**Available Statistical Categories:**\n"]

    for idx, category in enumerate(_json_data, 1):
        output_lines.append(f"{idx}. **{category.get('code')}** - {category.get('name')}")
        output_lines.append(f"   English: {category.get('name_en')}")

        # Show subcategories
        children = category.get('children', [])
        if children:
            output_lines.append(f"   Subcategories: {len(children)}")
        output_lines.append("")

    return "\n".join(output_lines)

