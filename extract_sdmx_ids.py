#!/usr/bin/env python3
"""
Extract SDMX IDs from jsons/main.json file.

This script recursively extracts all IDs from the nested JSON structure
and saves them to a text file.
"""

import json
from pathlib import Path
from typing import List


def extract_ids_recursive(data: dict | list, ids: List[int] = None) -> List[int]:
    """
    Recursively extract all 'id' values from nested JSON structure.

    Args:
        data: JSON data (dict or list)
        ids: Accumulator list for IDs

    Returns:
        List of all extracted IDs
    """
    if ids is None:
        ids = []

    if isinstance(data, dict):
        # Extract ID if present
        if 'id' in data:
            ids.append(data['id'])

        # Recursively process children
        if 'children' in data and data['children']:
            for child in data['children']:
                extract_ids_recursive(child, ids)

        # Process all other dict values
        for value in data.values():
            if isinstance(value, (dict, list)):
                extract_ids_recursive(value, ids)

    elif isinstance(data, list):
        for item in data:
            extract_ids_recursive(item, ids)

    return ids


def main():
    """Main function to extract IDs from main.json."""
    # Load main.json
    main_json_path = Path(__file__).parent / "jsons" / "main.json"

    if not main_json_path.exists():
        print(f"Error: {main_json_path} not found")
        return

    print(f"Loading SDMX data from: {main_json_path}")

    with open(main_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Extract all IDs
    ids = extract_ids_recursive(data)

    # Remove duplicates and sort
    unique_ids = sorted(set(ids))

    print(f"Found {len(unique_ids)} unique SDMX IDs")

    # Save to file
    output_file = Path(__file__).parent / "sdmx_ids.txt"

    with open(output_file, 'w') as f:
        for sdmx_id in unique_ids:
            f.write(f"{sdmx_id}\n")

    print(f"Saved IDs to: {output_file}")
    print(f"\nFirst 10 IDs: {unique_ids[:10]}")
    print(f"Last 10 IDs: {unique_ids[-10:]}")

    return unique_ids


if __name__ == "__main__":
    main()
