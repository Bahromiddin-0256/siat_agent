"""Shared Qdrant client singleton.

Both rag_tool and metadata_rag_tool share one QdrantClient instance because
Qdrant's local (file-based) mode only allows a single client to hold the lock
on the storage directory at a time.
"""

import threading

from qdrant_client import QdrantClient

from core.settings import settings
from core.logger import setup_logger

logger = setup_logger(__name__)

_client: QdrantClient | None = None
_lock = threading.Lock()


def get_shared_client() -> QdrantClient:
    """Return the process-wide Qdrant client (lazy-loaded, thread-safe)."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                persist_dir = settings.qdrant_persist_dir
                persist_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Opening Qdrant local store at {persist_dir}")
                _client = QdrantClient(path=str(persist_dir))
    return _client
