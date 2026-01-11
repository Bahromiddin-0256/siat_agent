"""
SDMX Report Count Tool.

This module provides functionality to count the number of reports (leaf nodes)
for a given SDMX category or parent node.
"""

import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from langchain_core.tools import tool
from core.logger import setup_logger

logger = setup_logger(__name__)


def load_main_json() -> List[Dict[str, Any]]:
    """
    Load the main.json file containing SDMX hierarchy.

    Returns:
        Parsed JSON data as a list of dictionaries
    """
    json_path = Path(__file__).parent.parent / "jsons" / "main.json"

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading main.json: {e}")
        return []


def count_leaf_nodes(node: Dict[str, Any]) -> int:
    """
    Count all leaf nodes (nodes without children) recursively.

    Args:
        node: A node from the SDMX hierarchy

    Returns:
        Number of leaf nodes (actual reports/SDMX endpoints)
    """
    if 'children' not in node or not node['children']:
        # This is a leaf node (actual report)
        return 1

    # Count leaf nodes in all children
    count = 0
    for child in node['children']:
        count += count_leaf_nodes(child)

    return count


def find_node_by_name(data: List[Dict[str, Any]], search_name: str) -> Optional[Dict[str, Any]]:
    """
    Find a node by searching its name (case-insensitive, partial match).

    Args:
        data: List of SDMX nodes
        search_name: Name to search for

    Returns:
        Found node or None
    """
    search_lower = search_name.lower()

    # First, try direct match in top-level nodes
    for node in data:
        node_names = [
            node.get('name', ''),
            node.get('name_uz', ''),
            node.get('name_en', ''),
            node.get('name_ru', ''),
            node.get('name_uzc', '')
        ]

        for name in node_names:
            if name and search_lower in name.lower():
                return node

    # If not found at top level, search recursively
    def search_recursive(nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for node in nodes:
            node_names = [
                node.get('name', ''),
                node.get('name_uz', ''),
                node.get('name_en', ''),
                node.get('name_ru', ''),
                node.get('name_uzc', '')
            ]

            for name in node_names:
                if name and search_lower in name.lower():
                    return node

            # Search in children
            if 'children' in node and node['children']:
                result = search_recursive(node['children'])
                if result:
                    return result

        return None

    return search_recursive(data)


@tool
def count_reports_for_category(category_name: str) -> str:
    """
    Count the number of reports (leaf nodes) for a given SDMX category.

    Use this tool when users ask how many reports, indicators, or datasets
    are available under a specific category or statistical domain.

    Args:
        category_name: Name of the category (can be partial name in Uzbek, Russian, or English)

    Returns:
        A formatted string with the count of reports and category details

    Keywords: "nechta hisobot", "how many reports", "сколько отчетов", "nechta ko'rsatkich"

    Examples:
        count_reports_for_category("30 yillik iqtisodiy makro-ko'rsatkichlar")
        count_reports_for_category("economic macro indicators")
        count_reports_for_category("экономические макропоказатели")
    """
    logger.info(f"Counting reports for category: {category_name}")

    # Load the main JSON data
    data = load_main_json()

    if not data:
        return "Xatolik: main.json faylini yuklash mumkin emas"

    # Find the node
    node = find_node_by_name(data, category_name)

    if not node:
        return f"Kategoriya topilmadi: '{category_name}'. Iltimos, kategoriya nomini to'liqroq yoki aniqroq kiriting."

    # Count leaf nodes (reports)
    report_count = count_leaf_nodes(node)

    # Get direct children count
    direct_children_count = len(node.get('children', []))

    # Build response
    category_display_name = node.get('name_uz') or node.get('name') or category_name

    result = []
    result.append(f"Kategoriya: {category_display_name}")
    result.append(f"SDMX ID: {node.get('id')}")
    result.append(f"Kod: {node.get('code', 'N/A')}")
    result.append("")
    result.append(f"Hisobotlar soni (leaf nodes): {report_count} ta")
    result.append(f"To'g'ridan-to'g'ri bolalar soni: {direct_children_count} ta")

    # Show direct children names if there are any
    if direct_children_count > 0 and direct_children_count <= 20:
        result.append("")
        result.append("To'g'ridan-to'g'ri bolalar:")
        for i, child in enumerate(node.get('children', []), 1):
            child_name = child.get('name_uz') or child.get('name')
            child_leaf_count = count_leaf_nodes(child)
            result.append(f"  {i}. {child_name} ({child_leaf_count} hisobot)")

    logger.info(f"Found {report_count} reports for category '{category_display_name}'")
    return "\n".join(result)


@tool
def count_reports_by_id(node_id: int) -> str:
    """
    Count the number of reports (leaf nodes) for a given SDMX node ID.

    Use this tool when users provide a specific SDMX node ID and want to know
    how many reports are under that node.

    Args:
        node_id: The SDMX node ID

    Returns:
        A formatted string with the count of reports

    Example:
        count_reports_by_id(1916)  # For "30 yillik iqtisodiy makro-ko'rsatkichlar"
    """
    logger.info(f"Counting reports for node ID: {node_id}")

    # Load the main JSON data
    data = load_main_json()

    if not data:
        return "Xatolik: main.json faylini yuklash mumkin emas"

    # Find the node by ID
    def find_by_id(nodes: List[Dict[str, Any]], target_id: int) -> Optional[Dict[str, Any]]:
        for node in nodes:
            if node.get('id') == target_id:
                return node

            # Search in children
            if 'children' in node and node['children']:
                result = find_by_id(node['children'], target_id)
                if result:
                    return result

        return None

    node = find_by_id(data, node_id)

    if not node:
        return f"Node ID {node_id} topilmadi"

    # Count leaf nodes
    report_count = count_leaf_nodes(node)
    direct_children_count = len(node.get('children', []))

    # Build response
    category_name = node.get('name_uz') or node.get('name')

    result = []
    result.append(f"Node ID: {node_id}")
    result.append(f"Kategoriya: {category_name}")
    result.append(f"Kod: {node.get('code', 'N/A')}")
    result.append("")
    result.append(f"Hisobotlar soni (leaf nodes): {report_count} ta")
    result.append(f"To'g'ridan-to'g'ri bolalar soni: {direct_children_count} ta")

    logger.info(f"Found {report_count} reports for node ID {node_id}")
    return "\n".join(result)