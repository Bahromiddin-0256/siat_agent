"""Shared file loading utilities for SDMX tools."""

import json
import threading
from pathlib import Path
from typing import Any, Optional

from core.logger import setup_logger

logger = setup_logger(__name__)

# Resolved base directory for SDMX data files — used for path traversal checks
_SDMX_BASE_DIR = Path("jsons/sdmxs").resolve()

# In-memory cache of loaded SDMX files. The catalog has ~3000 indicators but
# realistically only a few dozen are touched per session, so the cache stays
# small. Files are static during process lifetime, so no invalidation needed.
_SDMX_CACHE: dict[int, Any] = {}
_SDMX_CACHE_LOCK = threading.Lock()


def clear_sdmx_cache() -> None:
    """Clear the in-memory SDMX file cache (mainly for tests)."""
    with _SDMX_CACHE_LOCK:
        _SDMX_CACHE.clear()


def load_json_safe(file_path: Path, default: Any = None) -> Any:
    """
    Load JSON from a file with full error handling.

    Args:
        file_path: Path to the JSON file
        default: Value to return on failure (defaults to empty list)

    Returns:
        Parsed JSON data or default value on any error
    """
    if default is None:
        default = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return default
    except json.JSONDecodeError as e:
        logger.error(f"Malformed JSON in {file_path}: {e}")
        return default
    except IOError as e:
        logger.error(f"I/O error reading {file_path}: {e}")
        return default


def load_sdmx_data_file(sdmx_id: int, base_dir: str = "jsons/sdmxs") -> Optional[Any]:
    """
    Load an SDMX data file safely, with path-traversal protection.

    Args:
        sdmx_id: The SDMX identifier (must be a positive integer)
        base_dir: Base directory containing SDMX data files

    Returns:
        Parsed JSON data or None if not found / path is unsafe
    """
    if sdmx_id <= 0:
        logger.warning(f"Invalid sdmx_id: {sdmx_id}")
        return None

    # Resolve the requested base directory and verify it stays inside the
    # expected SDMX data root to prevent path traversal attacks.
    try:
        resolved_base = Path(base_dir).resolve()
    except Exception as e:
        logger.error(f"Cannot resolve base_dir '{base_dir}': {e}")
        return None

    expected_base = _SDMX_BASE_DIR
    if not str(resolved_base).startswith(str(expected_base)):
        logger.error(
            f"Path traversal attempt blocked — base_dir '{base_dir}' "
            f"resolves outside allowed root '{expected_base}'"
        )
        return None

    file_path = resolved_base / f"sdmx_data_{sdmx_id}.json"

    # Double-check the final file path is still inside the allowed base
    if not str(file_path.resolve()).startswith(str(expected_base)):
        logger.error(f"Path traversal attempt blocked for file: {file_path}")
        return None

    if not file_path.exists():
        return None

    # Cache by sdmx_id only — base_dir is locked to one root above, so the id
    # uniquely identifies a file. Concurrent first-loads of the same id may
    # race and parse twice; that's harmless (deterministic result) and faster
    # than a per-id lock.
    cached = _SDMX_CACHE.get(sdmx_id)
    if cached is not None:
        return cached

    data = load_json_safe(file_path, default=None)
    if data is not None:
        with _SDMX_CACHE_LOCK:
            _SDMX_CACHE[sdmx_id] = data
    return data
