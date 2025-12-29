#!/usr/bin/env python3
"""
Script to fetch SDMX JSON data from SIAT API.

Usage:
    python fetch_sdmx_data.py <sdmx_id1> <sdmx_id2> ...
    python fetch_sdmx_data.py --file sdmx_ids.txt
    python fetch_sdmx_data.py --output-dir ./data 12345 67890
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional

import httpx


BASE_URL = "https://api.siat.stat.uz/media/uploads/sdmx/sdmx_data_{sdmx_id}.json"


async def fetch_sdmx_data(
    sdmx_id: str,
    client: httpx.AsyncClient,
    output_dir: Optional[Path] = "jsons/sdmxs"
) -> dict:
    """
    Fetch JSON data for a single SDMX ID.

    Args:
        sdmx_id: The SDMX identifier
        client: HTTP client instance
        output_dir: Optional directory to save the JSON file

    Returns:
        The JSON data as a dictionary

    Raises:
        httpx.HTTPError: If the request fails
    """
    url = BASE_URL.format(sdmx_id=sdmx_id)

    try:
        print(f"Fetching data for SDMX ID: {sdmx_id}")
        response = await client.get(url)
        response.raise_for_status()

        data = response.json()

        # Save to file if output directory is specified
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"sdmx_data_{sdmx_id}.json"

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"✓ Saved to: {output_file}")
        else:
            print(f"✓ Successfully fetched data for SDMX ID: {sdmx_id}")

        return data

    except httpx.HTTPStatusError as e:
        print(f"✗ HTTP error for SDMX ID {sdmx_id}: {e.response.status_code}")
        raise
    except httpx.RequestError as e:
        print(f"✗ Request error for SDMX ID {sdmx_id}: {str(e)}")
        raise
    except json.JSONDecodeError as e:
        print(f"✗ JSON decode error for SDMX ID {sdmx_id}: {str(e)}")
        raise


async def fetch_multiple_sdmx_data(
    sdmx_ids: List[str],
    output_dir: Optional[Path] = None,
    max_concurrent: int = 5
) -> List[dict]:
    """
    Fetch JSON data for multiple SDMX IDs concurrently.

    Args:
        sdmx_ids: List of SDMX identifiers
        output_dir: Optional directory to save the JSON files
        max_concurrent: Maximum number of concurrent requests

    Returns:
        List of JSON data dictionaries
    """
    results = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_semaphore(sdmx_id: str):
            async with semaphore:
                try:
                    return await fetch_sdmx_data(sdmx_id, client, output_dir)
                except Exception as e:
                    print(f"Failed to fetch SDMX ID {sdmx_id}: {str(e)}")
                    return None

        tasks = [fetch_with_semaphore(sdmx_id) for sdmx_id in sdmx_ids]
        results = await asyncio.gather(*tasks)

    # Filter out None values (failed requests)
    return [r for r in results if r is not None]


def load_sdmx_ids_from_file(file_path: Path) -> List[str]:
    """
    Load SDMX IDs from a text file (one ID per line).

    Args:
        file_path: Path to the file containing SDMX IDs

    Returns:
        List of SDMX IDs
    """
    with open(file_path, 'r') as f:
        return [line.strip() for line in f if line.strip()]


def main():
    """Main function to handle CLI arguments and execute fetching."""
    parser = argparse.ArgumentParser(
        description="Fetch SDMX JSON data from SIAT API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fetch_sdmx_data.py 12345 67890
  python fetch_sdmx_data.py --file sdmx_ids.txt
  python fetch_sdmx_data.py --output-dir ./data 12345 67890
  python fetch_sdmx_data.py --output-dir ./data --file sdmx_ids.txt
        """
    )

    parser.add_argument(
        'sdmx_ids',
        nargs='*',
        help='SDMX IDs to fetch'
    )

    parser.add_argument(
        '--file', '-f',
        type=Path,
        help='File containing SDMX IDs (one per line)'
    )

    parser.add_argument(
        '--output-dir', '-o',
        type=Path,
        help='Directory to save JSON files (default: jsons/sdmxs)',
        default="jsons/sdmxs"
    )

    parser.add_argument(
        '--max-concurrent', '-m',
        type=int,
        default=5,
        help='Maximum number of concurrent requests (default: 5)'
    )

    args = parser.parse_args()

    # Collect SDMX IDs from arguments and/or file
    sdmx_ids = list(args.sdmx_ids) if args.sdmx_ids else []

    if args.file:
        if not args.file.exists():
            print(f"Error: File not found: {args.file}")
            sys.exit(1)
        sdmx_ids.extend(load_sdmx_ids_from_file(args.file))

    if not sdmx_ids:
        print("Error: No SDMX IDs provided. Use --help for usage information.")
        sys.exit(1)

    # Remove duplicates while preserving order
    sdmx_ids = list(dict.fromkeys(sdmx_ids))

    print(f"Fetching data for {len(sdmx_ids)} SDMX ID(s)...")

    # Run async fetch
    results = asyncio.run(
        fetch_multiple_sdmx_data(
            sdmx_ids,
            output_dir=args.output_dir,
            max_concurrent=args.max_concurrent
        )
    )

    print(f"\n{'='*60}")
    print(f"Successfully fetched: {len(results)}/{len(sdmx_ids)} SDMX IDs")

    if len(results) < len(sdmx_ids):
        print(f"Failed: {len(sdmx_ids) - len(results)} SDMX IDs")

    if not args.output_dir:
        print("\nNote: Data was not saved. Use --output-dir to save JSON files.")


if __name__ == "__main__":
    main()
