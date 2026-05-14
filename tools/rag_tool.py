"""
RAG-based SDMX ID Retriever Tool.

Uses BGE-M3 (dense + sparse) with Qdrant for hybrid semantic search
via Reciprocal Rank Fusion (RRF).
"""

import re
from datetime import datetime, timedelta, timezone
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
from tools.embedder import encode_dense_sparse, encode_query, rerank_pairs
from tools.qdrant_shared_client import get_shared_client
from tools.query_expander import expand_query

logger = setup_logger(__name__)

_COLLECTION = "sdmx_rag"

# Total number of indicators currently indexed. Set by
# `initialize_rag_vectorstore` (after extract OR after detecting an existing
# collection) and read by `_catalog_order_multiplier` to normalize position
# into a [0, 1] range. Zero means "not initialized yet"; the multiplier
# degrades to a no-op in that case.
_catalog_total: int = 0

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


def _detect_subset(name_uz: str | None, name_en: str | None) -> str:
    """Classify an indicator's demographic / geographic subset from its name.

    Why: indicators like "Doimiy aholi soni (jami)" and "(ayol)" embed to
    near-identical vectors because only one word distinguishes them. We
    attach an explicit subset tag to the embedded document (and the payload)
    so dense+sparse retrieval can tell them apart, and so queries that
    don't request a specific subset can downweight the variants at rerank
    time. Returned label is one of:
      total, female, male, urban, rural, age_group, working_age, "".
    """
    text = f"{name_uz or ''} {name_en or ''}".lower()
    if re.search(r"\b\d{1,2}\s*-\s*\d{1,2}\s*yosh", text) or re.search(
        r"\b\d{1,2}\s+yosh\s+va\b", text
    ):
        return "age_group"
    if "mehnatga layoqatli" in text or "working age" in text or "working-age" in text:
        return "working_age"
    if (
        re.search(r"[(\-]\s*ayol", text)
        or "ayollar" in text
        or "(female" in text
        or "(women" in text
        or "(женщин" in text
    ):
        return "female"
    if (
        re.search(r"[(\-]\s*erkak", text)
        or "erkaklar" in text
        or "(male" in text
        or "(men" in text
        or "(мужчин" in text
    ):
        return "male"
    if re.search(r"[(\-]\s*qishloq", text) or "(rural" in text or "(село" in text:
        return "rural"
    if re.search(r"[(\-]\s*shahar", text) or "(urban" in text or "(город" in text:
        return "urban"
    if (
        re.search(r"[(\-]\s*jami", text)
        or "(total" in text
        or "-total" in text
        or "(всего" in text
    ):
        return "total"
    return ""


_SUBSET_DOC_TEXT = {
    "total": "Subset: total — whole population, both sexes, all areas combined.",
    "female": "Subset: female only — women only, NOT total population.",
    "male": "Subset: male only — men only, NOT total population.",
    "urban": "Subset: urban areas only — city dwellers, NOT total population.",
    "rural": "Subset: rural areas only — village dwellers, NOT total population.",
    "age_group": "Subset: specific age group only, NOT total population.",
    "working_age": "Subset: working-age population only, NOT total population.",
}


def _query_dimension_intent(question: str) -> set[str]:
    """Which demographic / geographic dimensions does the user EXPLICITLY name?

    Used by the rerank penalty: when the user asks a dimension-neutral
    question, indicators whose name carries a subset suffix in that
    dimension get demoted so the "jami / total" variant ranks first.
    """
    q = question.lower()
    intent: set[str] = set()
    if any(
        t in q
        for t in (
            "ayol",
            "erkak",
            "qiz bola",
            "o'g'il bola",
            "o`g`il bola",
            "female",
            "male",
            "women",
            "men",
            " gender",
            "женщ",
            "мужч",
            "по полу",
        )
    ):
        intent.add("gender")
    # Urban/rural: only trigger on phrases that name the dimension itself,
    # NOT on region names like "Toshkent shahri" / "Andijon shahri" where
    # "shahar" is part of a region label. We deliberately do NOT match the
    # bare word "shahar" / "qishloq".
    if any(
        t in q
        for t in (
            "shahar va qishloq",
            "qishloq va shahar",
            "shahar joylar",
            "qishloq joylar",
            "shahar joyda",
            "qishloq joyda",
            "urban population",
            "rural population",
            "urban area",
            "rural area",
            "городское насел",
            "сельское насел",
            "городских и сель",
        )
    ):
        intent.add("area")
    if (
        re.search(r"\b\d{1,2}\s*-\s*\d{1,2}\s*yosh", q)
        or "yoshda" in q
        or "yoshli" in q
        or "yosh guruh" in q
        or "age group" in q
        or "возраст" in q
    ):
        intent.add("age")
    return intent


def _subset_penalty(subset: str, intent: set[str]) -> float:
    """Rerank-score multiplier. Neutral query + subset variant → 0.7;
    matching intent or total/neutral indicator → 1.0."""
    if not subset or subset == "total":
        return 1.0
    if subset in ("female", "male"):
        return 1.0 if "gender" in intent else 0.7
    if subset in ("urban", "rural"):
        return 1.0 if "area" in intent else 0.7
    if subset in ("age_group", "working_age"):
        return 1.0 if "age" in intent else 0.7
    return 1.0


# Status weights: how much we trust this indicator's data is current.
# Anchored at "Yangilangan" = 1.0; stale and pending statuses pay a small
# penalty so they sort behind a fresh equivalent on tied semantic scores.
_STATUS_WEIGHT = {
    "Yangilangan": 1.00,
    "Yangilanmaydigan": 0.92,   # frozen-by-design (historical series); still valid
    "Muddati o'tib yangilangan": 0.85,
    "Kutulmoqda": 0.78,
    "Muddati o'tgan": 0.70,
}


def _parse_iso_safe(ts: str | None) -> datetime | None:
    """Tolerant ISO-8601 parser. Returns None on any parse error.

    The catalog uses "2025-05-07T09:50:54.069753+05:00"; some entries may
    drop the offset or use 'Z' — handle both without raising.
    """
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _freshness_multiplier(updated_xlsx: str | None, status: str | None) -> float:
    """Combine data-file age and status into a single [0.65, 1.0] multiplier.

    `updated_xlsx` is when the indicator's xlsx data file was last refreshed
    on SIAT — that's what actually determines whether the numbers a user
    will see are recent. `status` is the catalog's own freshness label.
    Both move in the same direction, so we multiply them — a fresh file
    on a stale-status indicator still beats an old file on a pending one,
    but a fresh-and-updated combo wins outright.
    """
    status_w = _STATUS_WEIGHT.get(status or "", 0.85)

    ts = _parse_iso_safe(updated_xlsx)
    if ts is None:
        age_w = 0.85  # unknown age — moderate penalty
    else:
        now = datetime.now(timezone.utc)
        age_days = max(0, (now - ts.astimezone(timezone.utc)).days)
        if age_days <= 365:
            age_w = 1.00
        elif age_days <= 730:
            age_w = 0.92
        elif age_days <= 1825:
            age_w = 0.82
        else:
            age_w = 0.72

    return max(0.65, status_w * age_w)


def _catalog_order_multiplier(catalog_index: int | None, total: int) -> float:
    """Tiny bias toward indicators that appear earlier in main.json.

    Range [0.93, 1.0]. Lighter than freshness / subset weights because
    "earlier in catalog" is only a soft signal of prominence — semantic
    similarity should still dominate.
    """
    if catalog_index is None or not total or total <= 1:
        return 1.0
    rel = max(0.0, min(1.0, catalog_index / (total - 1)))
    return 1.0 - 0.07 * rel


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
    global _catalog_total
    client = _get_client()

    # Skip re-indexing if the collection already has points AND the schema
    # matches what this version writes. We bump the sentinel field every
    # time the payload shape changes:
    #   v1 → +subset           (dimension-aware rerank)
    #   v2 → +catalog_index    (catalog-order tiebreaker)
    #   v2 → +updated_xlsx     (freshness multiplier)
    # The `catalog_index` field is the v2 marker: its presence implies the
    # whole v2 schema is in the payload.
    try:
        info = client.get_collection(_COLLECTION)
        if info.points_count > 0:
            try:
                sample = client.scroll(
                    collection_name=_COLLECTION, limit=1, with_payload=True
                )[0]
                first_payload = sample[0].payload if sample else {}
                if "catalog_index" not in first_payload:
                    logger.info(
                        f"Collection '{_COLLECTION}' missing 'catalog_index' field — "
                        f"rebuilding to pick up new schema (subset + catalog order + freshness)."
                    )
                    raise ValueError("schema upgrade needed")
            except ValueError:
                pass  # fall through to rebuild
            else:
                _catalog_total = info.points_count
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

            subset = _detect_subset(item.get("name_uz") or item.get("name"), item.get("name_en"))
            if subset:
                parts.append(_SUBSET_DOC_TEXT[subset])

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
                    "subset": subset,
                    # Global DFS index — earlier in main.json means more
                    # prominent in the SIAT catalog UI, used as a small
                    # tiebreaker at rerank time.
                    "catalog_index": len(texts) - 1,
                    # Data-file freshness — drives the freshness multiplier
                    # at search time. `updated_xlsx` tracks when the xlsx
                    # data on SIAT was last refreshed; `updated_at` would
                    # track only metadata edits, which we don't use.
                    "updated_xlsx": item.get("updated_xlsx"),
                }
            )

            children = item.get("children", [])
            if children:
                extract(children, path + [item.get("name", "Unknown")])

    extract(json_data)
    logger.info(f"Extracted {len(texts)} documents from SDMX data")

    # Stash total count for the catalog-order multiplier in search.
    _catalog_total = len(texts)

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
            20,
            description="Number of results to return (int or a digit-string, e.g. 20 or '20')",
        )

    class _SearchWithScoreArgs(BaseModel):
        question: str = Field(..., description="A question about statistics")
        k: Union[int, str] = Field(
            20,
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
def search_sdmx_semantic(question: str, k: int = 20) -> str:
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

    # Expand the query with domain synonyms before encoding. The expanded
    # version is only used for retrieval; the cache key keeps the original
    # so identical user queries still hit the cache.
    encoded_query = expand_query(question)
    dense, sparse = encode_query(encoded_query)

    # Over-fetch from RRF so the reranker has a real candidate pool to choose
    # from. RRF gives strong recall; cross-encoder rerank gives precision.
    # Capped at 30 to keep rerank latency under ~300ms on CPU.
    rerank_pool = min(max(k * 3, 15), 30)

    results = _get_client().query_points(
        collection_name=_COLLECTION,
        prefetch=[
            Prefetch(query=dense, using="dense", limit=rerank_pool * 2),
            Prefetch(
                query=SparseVector(
                    indices=list(sparse.keys()),
                    values=list(sparse.values()),
                ),
                using="sparse",
                limit=rerank_pool * 2,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=rerank_pool,
    ).points

    if not results:
        return f"No matching SDMX IDs found for: '{question}'"

    # Rerank with the same BGE-M3 model (colbert+dense+sparse fusion). Use the
    # original user question — not the expanded one — so synonym noise added by
    # expand_query doesn't bias the cross-encoder.
    #
    # Composite multiplier applied on top of the cross-encoder score:
    #   * subset_penalty — push (ayol)/(erkak)/(urban)/(rural)/age-group below
    #     neutral when the query doesn't request that dimension
    #   * freshness_multiplier — reward indicators whose xlsx was refreshed
    #     recently and whose catalog status is "Yangilangan"
    #   * catalog_order_multiplier — small bias toward indicators that appear
    #     earlier in main.json (a soft prominence prior)
    intent = _query_dimension_intent(question)

    def _composite(payload: dict, base: float) -> float:
        sub = (payload or {}).get("subset", "") or ""
        upd = (payload or {}).get("updated_xlsx")
        sts = (payload or {}).get("status")
        cidx = (payload or {}).get("catalog_index")
        return (
            base
            * _subset_penalty(sub, intent)
            * _freshness_multiplier(upd, sts)
            * _catalog_order_multiplier(cidx, _catalog_total)
        )

    if len(results) > k:
        passages = [(p.payload or {}).get("text", "") for p in results]
        scores = rerank_pairs(question, passages)
        if scores and any(s != 0.0 for s in scores):
            adjusted = [
                _composite(p.payload or {}, s) for p, s in zip(results, scores)
            ]
            scored = sorted(
                zip(results, adjusted), key=lambda x: x[1], reverse=True
            )
            results = [r for r, _ in scored[:k]]
        else:
            # Rerank produced no signal — fall back to the composite as the
            # sole sort key, using a constant base so subset/freshness/order
            # still nudge results into a sensible order.
            adjusted = [_composite(p.payload or {}, 1.0) for p in results]
            scored = sorted(
                zip(results, adjusted), key=lambda x: x[1], reverse=True
            )
            results = [r for r, _ in scored[:k]]
    elif len(results) > 1:
        # No rerank pool to score against — apply the composite as the sort
        # key (constant base) so subset / freshness / order still come into
        # play. RRF order is implicit via the constant base + stable sort.
        adjusted = [_composite(p.payload or {}, 1.0) for p in results]
        order = sorted(
            range(len(results)),
            key=lambda i: (-adjusted[i], i),
        )
        results = [results[i] for i in order]

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
