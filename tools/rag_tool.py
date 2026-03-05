"""
RAG-based SDMX ID Retriever Tool.

Uses BGE-M3 (dense + sparse) with Qdrant for hybrid semantic search
via Reciprocal Rank Fusion (RRF).
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FusionQuery,
    Fusion,
    PointStruct,
    Prefetch,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from core.settings import settings
from core.logger import setup_logger
from tools.embedder import encode_dense_sparse, encode_query
from tools.qdrant_shared_client import get_shared_client

logger = setup_logger(__name__)

_COLLECTION = "sdmx_rag"

# Simple TTL cache for semantic search results
_query_cache: dict[str, tuple[str, datetime]] = {}
_CACHE_TTL = timedelta(hours=1)


def _cache_get(key: str) -> str | None:
    """Return cached result if still fresh, else None."""
    entry = _query_cache.get(key)
    if entry and datetime.now() - entry[1] < _CACHE_TTL:
        return entry[0]
    return None


def _cache_set(key: str, value: str) -> None:
    """Store result in cache, evicting oldest entry when over 512 items."""
    if len(_query_cache) >= 512:
        oldest = min(_query_cache, key=lambda k: _query_cache[k][1])
        del _query_cache[oldest]
    _query_cache[key] = (value, datetime.now())


def _get_client() -> QdrantClient:
    return get_shared_client()


def initialize_rag_vectorstore(
    json_data: list[dict[str, Any]],
    persist_directory: str = None,  # kept for API compatibility, unused
    embedding_model: str = None,    # kept for API compatibility, unused
) -> QdrantClient:
    """
    Initialize the RAG vector store from JSON data.

    On restart, loads from the persisted Qdrant collection if it already
    contains data. Otherwise encodes all documents with BGE-M3 and indexes
    them with both dense and sparse vectors for hybrid search.
    """
    client = _get_client()

    # Skip re-indexing if the collection already has points
    try:
        info = client.get_collection(_COLLECTION)
        if info.points_count > 0:
            logger.info(
                f"Loaded existing Qdrant collection '{_COLLECTION}' "
                f"({info.points_count} points)"
            )
            return client
    except Exception:
        pass  # Collection does not exist yet

    logger.info(f"Creating Qdrant collection '{_COLLECTION}'...")
    try:
        client.delete_collection(_COLLECTION)
    except Exception:
        pass

    client.create_collection(
        collection_name=_COLLECTION,
        vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
        sparse_vectors_config={
            "sparse": SparseVectorParams(index=SparseIndexParams())
        },
    )

    # Extract documents from nested SDMX hierarchy
    texts: list[str] = []
    payloads: list[dict] = []
    seen_ids: set = set()

    def extract(items: list[dict[str, Any]], path: list[str] | None = None) -> None:
        if path is None:
            path = []
        for item in items:
            if not item.get("code"):
                continue
            item_id = item.get("id")
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)

            parts = []
            for field, label in [
                ("name", "Name"),
                ("name_en", "English"),
                ("name_ru", "Russian"),
                ("name_uz", "Uzbek"),
            ]:
                if item.get(field):
                    parts.append(f"{label}: {item[field]}")
            tags = item.get("tags", [])
            if tags:
                parts.append(f"Tags: {', '.join(tags)}")
            if item.get("period"):
                parts.append(f"Period: {item['period']}")
            if item.get("department"):
                parts.append(f"Department: {item['department']}")

            texts.append("\n".join(parts))
            payloads.append(
                {
                    "id": str(item_id) if item_id else item.get("code"),
                    "code": item.get("code"),
                    "name": item.get("name"),
                    "name_en": item.get("name_en"),
                    "name_ru": item.get("name_ru"),
                    "period": item.get("period"),
                    "department": item.get("department"),
                    "status": item.get("status"),
                    "path": " > ".join(path + [item.get("name", "")]),
                }
            )

            children = item.get("children", [])
            if children:
                extract(children, path + [item.get("name", "Unknown")])

    extract(json_data)
    logger.info(f"Extracted {len(texts)} documents from SDMX data")

    # Encode with BGE-M3 (dense + sparse)
    logger.info("Encoding documents with BGE-M3 (this may take a while)...")
    dense_vecs, sparse_weights = encode_dense_sparse(texts)

    # Build Qdrant points
    points = [
        PointStruct(
            id=i,
            vector={
                "dense": dense,
                "sparse": SparseVector(
                    indices=list(sparse.keys()),
                    values=list(sparse.values()),
                ),
            },
            payload={"text": text, **payload},
        )
        for i, (text, payload, dense, sparse) in enumerate(
            zip(texts, payloads, dense_vecs, sparse_weights)
        )
    ]

    # Upsert in batches of 100
    batch_size = 100
    for i in range(0, len(points), batch_size):
        client.upsert(collection_name=_COLLECTION, points=points[i : i + batch_size])

    logger.info(
        f"Qdrant collection '{_COLLECTION}' created and indexed with {len(points)} points"
    )
    return client


def get_vectorstore() -> QdrantClient | None:
    """Get the initialized Qdrant client."""
    return get_shared_client()


def rebuild_vectorstore(
    json_data: list[dict[str, Any]],
    persist_directory: str = None,
    embedding_model: str = None,
) -> QdrantClient:
    """Force rebuild the vector store (use when JSON data has changed)."""
    client = _get_client()
    try:
        client.delete_collection(_COLLECTION)
        logger.info(f"Deleted existing collection '{_COLLECTION}'")
    except Exception:
        pass
    return initialize_rag_vectorstore(json_data, persist_directory, embedding_model)


# --- Tool argument schemas ---
try:
    from pydantic import BaseModel, Field
    from typing import Union

    class _SemanticSearchArgs(BaseModel):
        question: str = Field(..., description="A question about statistics")
        k: Union[int, str] = Field(
            10,
            description="Number of results to return (int or a digit-string, e.g. 10 or '10')",
        )

    class _SearchWithScoreArgs(BaseModel):
        question: str = Field(..., description="A question about statistics")
        k: Union[int, str] = Field(
            10,
            description="Number of results to return (int or a digit-string)",
        )
        score_threshold: Union[float, str] = Field(
            0.7,
            description="Minimum similarity score (0-1). May be a float or a numeric string.",
        )

except (ImportError, AttributeError) as e:
    logger.warning(f"Failed to create Pydantic argument schemas: {e}")
    _SemanticSearchArgs = None
    _SearchWithScoreArgs = None


@tool(args_schema=_SemanticSearchArgs) if _SemanticSearchArgs else tool
def search_sdmx_semantic(question: str, k: int = 10) -> str:
    """
    Search for SDMX IDs using semantic similarity (RAG-based).

    This tool uses BGE-M3 hybrid search (dense + sparse vectors with RRF fusion)
    to find statistically relevant indicators based on semantic meaning.
    Best for complex or nuanced questions about statistics.

    Args:
        question: A question about statistics
        k: Number of results to return (default: 10)

    Returns:
        Formatted string with matching SDMX IDs and their details
    """
    if get_shared_client() is None:
        return "Error: RAG vector store not initialized. Call initialize_rag_vectorstore first."

    try:
        if isinstance(k, str):
            k = int(k)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid k parameter '{k}', defaulting to 10: {e}")
        k = 10

    k = max(1, min(k, 50))

    cache_key = f"{question}:{k}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug(f"Cache hit for semantic search: '{question[:50]}'")
        return cached

    dense, sparse = encode_query(question)

    results = _get_client().query_points(
        collection_name=_COLLECTION,
        prefetch=[
            Prefetch(query=dense, using="dense", limit=k * 2),
            Prefetch(
                query=SparseVector(
                    indices=list(sparse.keys()),
                    values=list(sparse.values()),
                ),
                using="sparse",
                limit=k * 2,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=k,
    ).points

    if not results:
        return f"No matching SDMX IDs found for: '{question}'"

    output_lines = [f"Found {len(results)} semantically similar indicator(s):\n"]

    for idx, point in enumerate(results, 1):
        p = point.payload
        output_lines.append(f"{idx}. **ID**: {p.get('id')}")
        output_lines.append(f"   **Code**: {p.get('code')}")
        output_lines.append(f"   **Name**: {p.get('name')}")
        if p.get("name_en"):
            output_lines.append(f"   **English**: {p.get('name_en')}")
        if p.get("period"):
            output_lines.append(f"   **Period**: {p.get('period')}")
        if p.get("status"):
            output_lines.append(f"   **Status**: {p.get('status')}")
        if p.get("path"):
            output_lines.append(f"   **Category Path**: {p.get('path')}")
        output_lines.append("")

    result = "\n".join(output_lines)
    _cache_set(cache_key, result)
    return result


@tool(args_schema=_SearchWithScoreArgs) if _SearchWithScoreArgs else tool
def search_sdmx_with_score(question: str, k: int = 10, score_threshold: float = 0.7) -> str:
    """Search for SDMX IDs with similarity scores."""
    if get_shared_client() is None:
        return "Error: RAG vector store not initialized. Call initialize_rag_vectorstore first."

    try:
        if isinstance(k, str):
            k = int(k)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid k parameter '{k}', defaulting to 10: {e}")
        k = 10

    try:
        if isinstance(score_threshold, str):
            score_threshold = float(score_threshold)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid score_threshold '{score_threshold}', defaulting to 0.7: {e}")
        score_threshold = 0.7

    k = max(1, min(k, 50))
    if score_threshold <= 0 or score_threshold > 1:
        score_threshold = 0.7

    dense, _ = encode_query(question)

    # Dense-only search with score threshold (Qdrant cosine scores are directly 0-1)
    results = _get_client().search(
        collection_name=_COLLECTION,
        query_vector=("dense", dense),
        limit=k,
        score_threshold=score_threshold,
    )

    if not results:
        return f"No matching SDMX IDs found above threshold {score_threshold} for: '{question}'"

    output_lines = [
        f"Found {len(results)} indicator(s) above similarity threshold {score_threshold}:\n"
    ]

    for idx, point in enumerate(results, 1):
        p = point.payload
        output_lines.append(f"{idx}. **Relevance**: {point.score:.2%}")
        output_lines.append(f"   **ID**: {p.get('id')}")
        output_lines.append(f"   **Code**: {p.get('code')}")
        output_lines.append(f"   **Name**: {p.get('name')}")
        if p.get("name_en"):
            output_lines.append(f"   **English**: {p.get('name_en')}")
        if p.get("period"):
            output_lines.append(f"   **Period**: {p.get('period')}")
        output_lines.append("")

    return "\n".join(output_lines)
