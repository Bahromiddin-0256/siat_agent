#!/usr/bin/env python3
"""Cron-friendly CLI entry point for SDMX catalog sync.

Exit codes:
  0 — success or skipped (already running)
  1 — fatal error (catalog fetch failed)
  2 — partial success (some sdmx file fetches failed)

Usage:
  python scripts/sync_sdmx.py            # incremental
  python scripts/sync_sdmx.py --force    # force full rebuild
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on the path so `core` / `tools` imports work.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.sdmx_sync import sync_sdmx  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="SDMX catalog incremental sync")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip diff and rebuild the full index (use sparingly).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    report = sync_sdmx(force_full=args.force, trigger="cron")

    summary = {
        "trigger": report.trigger,
        "skipped": report.skipped,
        "reason": report.reason,
        "added": len(report.added),
        "data_only": len(report.data_only),
        "metadata": len(report.metadata),
        "removed": len(report.removed),
        "inactive": len(report.inactive),
        "unchanged": report.unchanged,
        "failed": len(report.failed_ids),
        "duration_s": round(report.duration_s, 2),
    }
    print(json.dumps(summary, ensure_ascii=False))

    if report.reason == "catalog_fetch_failed":
        return 1
    if report.failed_ids:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
