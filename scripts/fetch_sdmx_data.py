#!/usr/bin/env python3
"""
Fetch SDMX per-indicator data files from the SIAT API.

Three ways to pick which IDs to fetch:

    # 1. Explicit IDs on the command line
    python scripts/fetch_sdmx_data.py 12345 67890

    # 2. From a text file (one ID per line)
    python scripts/fetch_sdmx_data.py --file sdmx_ids.txt

    # 3. Walk jsons/main.json and grab every id (RECOMMENDED for first boot)
    python scripts/fetch_sdmx_data.py --from-main-json

By default the script skips IDs whose data file already exists on disk so
re-runs resume a partial download. Pass `--force` to re-fetch everything.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Set

import httpx


BASE_URL = "https://api.siat.stat.uz/media/uploads/sdmx/sdmx_data_{sdmx_id}.json"
DEFAULT_MAIN_JSON = Path(__file__).resolve().parents[1] / "jsons" / "main.json"


# ---------------------------------------------------------------------------
# ID extraction
# ---------------------------------------------------------------------------

def extract_ids_from_main_json(main_json_path: Path) -> List[str]:
    """Walk the hierarchical catalog and return every `id` as a string.

    The catalog mixes categories and leaf indicators in the same `id` space;
    we don't try to filter — the API responds with 404 for entries that have
    no data file, and the fetcher already handles that gracefully.
    """
    if not main_json_path.exists():
        raise FileNotFoundError(
            f"main.json not found at {main_json_path}. "
            "Start the app once to fetch it, or pass --main-json <path>."
        )

    catalog = json.loads(main_json_path.read_text(encoding="utf-8"))

    ids: List[str] = []
    seen: Set[str] = set()

    def walk(nodes: Iterable[dict]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            if node_id is not None:
                key = str(node_id)
                if key not in seen:
                    seen.add(key)
                    ids.append(key)
            children = node.get("children")
            if isinstance(children, list):
                walk(children)

    walk(catalog if isinstance(catalog, list) else [catalog])
    return ids


def filter_unfetched(
    sdmx_ids: Iterable[str],
    output_dir: Path,
    force: bool = False,
) -> List[str]:
    """Drop IDs whose `sdmx_data_<id>.json` already exists, unless force=True."""
    if force:
        return list(sdmx_ids)
    missing: List[str] = []
    for sid in sdmx_ids:
        if not (output_dir / f"sdmx_data_{sid}.json").exists():
            missing.append(sid)
    return missing


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

async def fetch_sdmx_data(
    sdmx_id: str,
    client: httpx.AsyncClient,
    output_dir: Optional[Path] = None,
) -> Optional[dict]:
    """Fetch one indicator's data file. Returns None on failure."""
    url = BASE_URL.format(sdmx_id=sdmx_id)

    try:
        response = await client.get(url)
        if response.status_code == 404:
            # Categories and non-data nodes don't have files — that's fine.
            return None
        response.raise_for_status()
        data = response.json()

        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"sdmx_data_{sdmx_id}.json"
            tmp = output_file.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(output_file)

        return data

    except httpx.HTTPStatusError as e:
        print(f"  ✗ HTTP {e.response.status_code} for ID {sdmx_id}")
    except httpx.RequestError as e:
        print(f"  ✗ Request error for ID {sdmx_id}: {e}")
    except json.JSONDecodeError as e:
        print(f"  ✗ JSON decode error for ID {sdmx_id}: {e}")
    return None


async def fetch_multiple_sdmx_data(
    sdmx_ids: List[str],
    output_dir: Optional[Path] = None,
    max_concurrent: int = 5,
    progress_every: int = 50,
) -> tuple[int, int, int]:
    """Fetch many IDs concurrently. Returns (saved, not_found, failed)."""
    saved = 0
    not_found = 0
    failed = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        semaphore = asyncio.Semaphore(max_concurrent)
        done = 0
        lock = asyncio.Lock()

        async def fetch_with_semaphore(sdmx_id: str):
            nonlocal saved, not_found, failed, done
            async with semaphore:
                try:
                    result = await fetch_sdmx_data(sdmx_id, client, output_dir)
                except Exception as e:  # noqa: BLE001 — keep the batch going
                    print(f"  ✗ Unexpected error for ID {sdmx_id}: {e}")
                    async with lock:
                        failed += 1
                    return
                async with lock:
                    if result is None:
                        # 404s and request errors both land here; HTTPStatusError
                        # logs above so we don't double-count, but for a 404 the
                        # API simply has no file — treat as not_found.
                        not_found += 1
                    else:
                        saved += 1
                    done += 1
                    if done % progress_every == 0 or done == len(sdmx_ids):
                        print(
                            f"  ...{done}/{len(sdmx_ids)} "
                            f"(saved={saved}, missing={not_found}, failed={failed})"
                        )

        await asyncio.gather(*(fetch_with_semaphore(sid) for sid in sdmx_ids))

    return saved, not_found, failed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_sdmx_ids_from_file(file_path: Path) -> List[str]:
    return [line.strip() for line in file_path.read_text().splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(
        description="Fetch SDMX per-indicator data files from the SIAT API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch everything referenced in jsons/main.json, skipping files we already have
  python scripts/fetch_sdmx_data.py --from-main-json

  # Force re-fetch every indicator (overwrite existing files)
  python scripts/fetch_sdmx_data.py --from-main-json --force

  # Fetch a handful of specific IDs
  python scripts/fetch_sdmx_data.py 12345 67890

  # Fetch from a text file
  python scripts/fetch_sdmx_data.py --file sdmx_ids.txt
""",
    )

    parser.add_argument("sdmx_ids", nargs="*", help="Explicit SDMX IDs to fetch")
    parser.add_argument(
        "--file", "-f", type=Path,
        help="Text file with one SDMX ID per line",
    )
    parser.add_argument(
        "--from-main-json", action="store_true",
        help=f"Extract every id from main.json (default: {DEFAULT_MAIN_JSON})",
    )
    parser.add_argument(
        "--main-json", type=Path, default=DEFAULT_MAIN_JSON,
        help=f"Path to main.json (default: {DEFAULT_MAIN_JSON})",
    )
    parser.add_argument(
        "--output-dir", "-o", type=Path,
        default=Path("jsons/sdmxs"),
        help="Where to save data files (default: jsons/sdmxs)",
    )
    parser.add_argument(
        "--max-concurrent", "-m", type=int, default=5,
        help="Max concurrent requests (default: 5)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-fetch files that already exist on disk",
    )

    args = parser.parse_args()

    # ---- Collect IDs -----------------------------------------------------
    sdmx_ids: List[str] = list(args.sdmx_ids)

    if args.file:
        if not args.file.exists():
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        sdmx_ids.extend(load_sdmx_ids_from_file(args.file))

    if args.from_main_json:
        try:
            sdmx_ids.extend(extract_ids_from_main_json(args.main_json))
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    if not sdmx_ids:
        parser.error(
            "no IDs supplied — pass IDs as arguments, --file, or --from-main-json"
        )

    # De-dup while preserving order
    sdmx_ids = list(dict.fromkeys(sdmx_ids))
    total = len(sdmx_ids)

    # ---- Skip already-fetched -------------------------------------------
    pending = filter_unfetched(sdmx_ids, args.output_dir, force=args.force)
    skipped = total - len(pending)

    print(f"Total IDs: {total}")
    if skipped:
        print(f"Already on disk (skipped): {skipped}")
    print(f"To fetch: {len(pending)}  (concurrency={args.max_concurrent})")

    if not pending:
        print("Nothing to do.")
        return

    # ---- Fetch ----------------------------------------------------------
    saved, not_found, failed = asyncio.run(
        fetch_multiple_sdmx_data(
            pending,
            output_dir=args.output_dir,
            max_concurrent=args.max_concurrent,
        )
    )

    print("=" * 60)
    print(f"Saved:     {saved}")
    print(f"No data (404 / non-leaf): {not_found}")
    print(f"Failed:    {failed}")
    print(f"On-disk total: {len(list(args.output_dir.glob('sdmx_data_*.json')))}")


if __name__ == "__main__":
    main()
