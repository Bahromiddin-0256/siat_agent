"""
Metadata RAG-based SDMX Search Tool.

Uses BGE-M3 (dense + sparse) with Qdrant for hybrid semantic search
over methodology, classifiers, legal references, and definitions.
"""

import json
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

from core.settings import settings, BASE_DIR
from core.logger import setup_logger
from tools.embedder import encode_dense_sparse, encode_query
from tools.qdrant_shared_client import get_shared_client

logger = setup_logger(__name__)

_COLLECTION = "sdmx_metadata"


def extract_metadata_from_sdmx_files(base_dir: str = "jsons/sdmxs") -> list[dict]:
    """
    Extract metadata from all SDMX data files.

    Returns:
        List of dicts with keys 'text' (page content) and 'metadata' (payload fields).
    """
    logger.info(f"Extracting metadata from SDMX files in {base_dir}")

    base_path = Path(base_dir)
    if not base_path.exists():
        logger.error(f"Directory {base_dir} does not exist")
        return []

    records = []
    file_count = 0
    error_count = 0

    for file_path in sorted(base_path.glob("sdmx_data_*.json")):
        try:
            filename = file_path.stem  # e.g. "sdmx_data_225"
            sdmx_id = int(filename.split("_")[-1])

            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not data or not isinstance(data, list) or len(data) == 0:
                logger.warning(f"Invalid data structure in {file_path}")
                error_count += 1
                continue

            metadata_array = data[0].get("metadata", [])
            if not metadata_array:
                logger.warning(f"No metadata found in {file_path}")
                error_count += 1
                continue

            def get_metadata_value(field_name: str, lang: str = "uz") -> str:
                for item in metadata_array:
                    name_en = item.get("name_en", "").lower()
                    if field_name.lower() in name_en:
                        return item.get(f"value_{lang}", "") or ""
                return ""

            dataset_name_uz = get_metadata_value("data set name", "uz") or get_metadata_value("dataset name", "uz")
            dataset_name_ru = get_metadata_value("data set name", "ru") or get_metadata_value("dataset name", "ru")
            dataset_name_en = get_metadata_value("data set name", "en") or get_metadata_value("dataset name", "en")

            methodology_uz = get_metadata_value("calculation methodology", "uz")
            methodology_ru = get_metadata_value("calculation methodology", "ru")
            methodology_en = get_metadata_value("calculation methodology", "en")

            classifiers_uz = get_metadata_value("classifiers", "uz")
            classifiers_ru = get_metadata_value("classifiers", "ru")
            classifiers_en = get_metadata_value("classifiers", "en")

            note_uz = get_metadata_value("note", "uz")
            note_ru = get_metadata_value("note", "ru")
            note_en = get_metadata_value("note", "en")

            source_uz = get_metadata_value("primary", "uz")
            source_ru = get_metadata_value("primary", "ru")
            source_en = get_metadata_value("primary", "en")

            code = get_metadata_value("code", "uz") or get_metadata_value("identification", "uz")
            unit_uz = get_metadata_value("unit", "uz")
            department_uz = get_metadata_value("department", "uz")
            periodicity_uz = get_metadata_value("periodicity", "uz")

            content_parts = []

            if dataset_name_uz or dataset_name_ru or dataset_name_en:
                content_parts.append(f"Dataset: {dataset_name_uz} / {dataset_name_ru} / {dataset_name_en}")

            if methodology_uz or methodology_ru or methodology_en:
                method_uz_excerpt = methodology_uz[:500] if len(methodology_uz) > 500 else methodology_uz
                method_ru_excerpt = methodology_ru[:500] if len(methodology_ru) > 500 else methodology_ru
                method_en_excerpt = methodology_en[:500] if len(methodology_en) > 500 else methodology_en
                content_parts.append(
                    f"Methodology: {method_uz_excerpt} / {method_ru_excerpt} / {method_en_excerpt}"
                )

            if classifiers_uz or classifiers_ru or classifiers_en:
                content_parts.append(f"Classifiers: {classifiers_uz} / {classifiers_ru} / {classifiers_en}")

            if note_uz or note_ru or note_en:
                note_uz_excerpt = note_uz[:300] if len(note_uz) > 300 else note_uz
                note_ru_excerpt = note_ru[:300] if len(note_ru) > 300 else note_ru
                note_en_excerpt = note_en[:300] if len(note_en) > 300 else note_en
                content_parts.append(
                    f"Note: {note_uz_excerpt} / {note_ru_excerpt} / {note_en_excerpt}"
                )

            if source_uz or source_ru or source_en:
                content_parts.append(f"Source: {source_uz} / {source_ru} / {source_en}")

            records.append(
                {
                    "text": "\n\n".join(content_parts),
                    "metadata": {
                        "sdmx_id": sdmx_id,
                        "code": code,
                        "name_uz": dataset_name_uz,
                        "name_ru": dataset_name_ru,
                        "name_en": dataset_name_en,
                        "methodology_uz": methodology_uz,
                        "methodology_ru": methodology_ru,
                        "methodology_en": methodology_en,
                        "classifiers_uz": classifiers_uz,
                        "classifiers_ru": classifiers_ru,
                        "classifiers_en": classifiers_en,
                        "note_uz": note_uz,
                        "note_ru": note_ru,
                        "note_en": note_en,
                        "source_uz": source_uz,
                        "source_ru": source_ru,
                        "source_en": source_en,
                        "unit_uz": unit_uz,
                        "department_uz": department_uz,
                        "periodicity_uz": periodicity_uz,
                    },
                }
            )
            file_count += 1

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            error_count += 1
            continue

    logger.info(f"Extracted metadata from {file_count} files ({error_count} errors)")
    return records


def _get_metadata_client() -> QdrantClient:
    return get_shared_client()


def initialize_metadata_vectorstore(
    persist_directory: str = None,  # kept for API compatibility with run_in_executor
    base_dir: str = "jsons/sdmxs",
    embedding_model: str = None,    # kept for API compatibility, unused
) -> QdrantClient:
    """
    Initialize the metadata RAG vector store from SDMX data files.

    On restart, loads from the persisted Qdrant collection if it already
    contains data. Otherwise encodes all metadata documents with BGE-M3.
    """
    client = _get_metadata_client()

    try:
        info = client.get_collection(_COLLECTION)
        if info.points_count > 0:
            logger.info(
                f"Loaded existing Qdrant collection '{_COLLECTION}' "
                f"({info.points_count} points)"
            )
            return client
    except Exception:
        pass

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

    records = extract_metadata_from_sdmx_files(base_dir)
    if not records:
        logger.error("No documents extracted, cannot create metadata vector store")
        return None

    logger.info(f"Encoding {len(records)} metadata documents with BGE-M3...")
    texts = [r["text"] for r in records]
    dense_vecs, sparse_weights = encode_dense_sparse(texts)

    points = [
        PointStruct(
            id=record["metadata"]["sdmx_id"],
            vector={
                "dense": dense,
                "sparse": SparseVector(
                    indices=list(sparse.keys()),
                    values=list(sparse.values()),
                ),
            },
            payload={"text": record["text"], **record["metadata"]},
        )
        for record, dense, sparse in zip(records, dense_vecs, sparse_weights)
    ]

    batch_size = 100
    for i in range(0, len(points), batch_size):
        client.upsert(collection_name=_COLLECTION, points=points[i : i + batch_size])

    logger.info(
        f"Qdrant collection '{_COLLECTION}' created and indexed with {len(points)} points"
    )
    return client


def get_metadata_vectorstore() -> QdrantClient | None:
    """Get the initialized metadata Qdrant client."""
    return get_shared_client()


def rebuild_metadata_vectorstore(
    persist_directory: str = None,
    base_dir: str = "jsons/sdmxs",
    embedding_model: str = None,
) -> QdrantClient:
    """Force rebuild the metadata vector store (use when SDMX data has changed)."""
    client = _get_metadata_client()
    try:
        client.delete_collection(_COLLECTION)
        logger.info(f"Deleted existing collection '{_COLLECTION}'")
    except Exception:
        pass
    return initialize_metadata_vectorstore(persist_directory, base_dir, embedding_model)


# --- Tool argument schemas ---
try:
    from pydantic import BaseModel, Field
    from typing import Union

    class _MetadataSearchArgs(BaseModel):
        question: str = Field(
            ..., description="Search query about methodology, classifiers, or legal framework"
        )
        k: Union[int, str] = Field(
            10,
            description="Number of results to return (int or digit-string, e.g. 10 or '10')",
        )

except (ImportError, AttributeError) as e:
    logger.warning(f"Failed to create Pydantic argument schemas: {e}")
    _MetadataSearchArgs = None


@tool(args_schema=_MetadataSearchArgs) if _MetadataSearchArgs else tool
def search_sdmx_metadata(question: str, k: int = 10) -> str:
    """
    Search SDMX metadata using semantic search on methodologies, definitions,
    legal references, and classification systems.

    Use this tool to find SDMX IDs based on:
    - Calculation methodologies and definitions
    - Legal frameworks and regulatory references
    - Classification systems and criteria (e.g., SOATO, OKVED)
    - Methodological documentation

    Args:
        question: Search query about methodology, definitions, or legal framework
        k: Number of results to return (default: 10)

    Returns:
        Comma-separated list of SDMX IDs

    Example:
        search_sdmx_metadata("indicators using SOATO classifier")
        Returns: "SDMX IDs: 225, 226, 227, 228, 229"
    """
    if get_shared_client() is None:
        return "Error: Metadata vector store not initialized. Call initialize_metadata_vectorstore first."

    try:
        if isinstance(k, str):
            k = int(k)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid k parameter '{k}', defaulting to 10: {e}")
        k = 10

    k = max(1, min(k, 20))

    logger.info(f"Searching metadata for: '{question}' (k={k})")

    dense, sparse = encode_query(question)

    results = _get_metadata_client().query_points(
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

    sdmx_ids = [point.payload["sdmx_id"] for point in results]
    return f"SDMX IDs: {', '.join(map(str, sdmx_ids))}"
