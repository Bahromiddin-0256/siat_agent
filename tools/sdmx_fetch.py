"""
First-boot fetcher for the SDMX indicator catalog (jsons/main.json).

The chart-agent ships without `jsons/main.json` so that fresh checkouts
and clean Docker images stay small. On the very first run, we pull the
catalog from `settings.sdmx_catalog_url` and persist it next to the
per-indicator data files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from core.logger import setup_logger

logger = setup_logger(__name__)


def ensure_main_json(
    dest_path: Path,
    url: str,
    timeout_seconds: float = 60.0,
) -> Path:
    """Ensure `dest_path` exists, fetching it from `url` if missing.

    Writes atomically via a `.tmp` sibling so a crashed fetch never leaves
    a half-written catalog in place.

    Raises:
        RuntimeError: if the download fails or the response is not a
            non-empty JSON array (the expected SDMX catalog shape).
    """
    dest_path = Path(dest_path)
    if dest_path.exists() and dest_path.stat().st_size > 0:
        logger.info("SDMX catalog already present at %s", dest_path)
        return dest_path

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("SDMX catalog missing — fetching from %s", url)

    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPError as e:
        raise RuntimeError(
            f"Failed to download SDMX catalog from {url}: {e}"
        ) from e
    except ValueError as e:
        raise RuntimeError(
            f"SDMX catalog at {url} did not return valid JSON: {e}"
        ) from e

    if not isinstance(payload, list) or not payload:
        raise RuntimeError(
            f"SDMX catalog at {url} returned unexpected shape "
            f"(expected non-empty list, got {type(payload).__name__})"
        )

    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, dest_path)
    logger.info(
        "SDMX catalog saved to %s (%d top-level entries)",
        dest_path,
        len(payload),
    )
    return dest_path
