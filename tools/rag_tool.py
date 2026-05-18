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


def build_indicator_text_and_payload(
    item: dict, path: list[str], catalog_index: int
) -> tuple[str, dict]:
    """Build the (embedding text, Qdrant payload) for one catalog item.

    Shared by initialize_rag_vectorstore (bulk indexing) and
    core.sdmx_sync (incremental upsert) so the embedding format and
    payload shape stay in one place.
    """
    parts = []
    for fld, label in [
        ("name", "Name"),
        ("name_en", "English"),
        ("name_ru", "Russian"),
        ("name_uz", "Uzbek"),
    ]:
        if item.get(fld):
            parts.append(f"{label}: {item[fld]}")
    tags = item.get("tags") or []
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    if item.get("period"):
        parts.append(f"Period: {item['period']}")
    if item.get("department"):
        parts.append(f"Department: {item['department']}")

    subset = _detect_subset(
        item.get("name_uz") or item.get("name"), item.get("name_en")
    )
    if subset:
        parts.append(_SUBSET_DOC_TEXT[subset])

    text = "\n".join(parts)
    item_id = item.get("id")
    payload = {
        "id": str(item_id) if item_id is not None else item.get("code"),
        "code": item.get("code"),
        "name": item.get("name"),
        "name_en": item.get("name_en"),
        "name_ru": item.get("name_ru"),
        "period": item.get("period"),
        "department": item.get("department"),
        "status": item.get("status"),
        "path": " > ".join(path + [item.get("name", "")]),
        "subset": subset,
        "catalog_index": catalog_index,
        "updated_xlsx": item.get("updated_xlsx"),
    }
    return text, payload


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
    """Rerank-score multiplier.

    Asymmetric by design:
      - Neutral query + subset variant → 0.7 (total wins).
      - Subset query + total/neutral indicator → 0.7 (subset variant wins).
      - Matching intent or fully neutral both ways → 1.0.

    The second branch is what stops "Ayollarda ishsizlik darajasi" from
    returning the total-population unemployment rate: when the user has
    named a subset dimension, the 'total' variant gets demoted instead of
    riding the cross-encoder score alone.
    """
    sub = subset or ""
    if sub in ("", "total"):
        if intent & {"gender", "area", "age"}:
            return 0.7
        return 1.0
    if sub in ("female", "male"):
        return 1.0 if "gender" in intent else 0.7
    if sub in ("urban", "rural"):
        return 1.0 if "area" in intent else 0.7
    if sub in ("age_group", "working_age"):
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


# ---------------------------------------------------------------------------
# Age-range matching — keeps RAG from confidently returning "8-15 yoshli"
# when the user explicitly asked for a different range like "0-14".
# ---------------------------------------------------------------------------

_AGE_DASH_RE = re.compile(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s*yosh", re.IGNORECASE)
_AGE_DASH_INDICATOR_RE = re.compile(
    r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s*yoshli", re.IGNORECASE
)
_AGE_OPEN_RE = re.compile(
    r"\b(\d{1,2})\s*yosh"
    # "yoshdan oshgan / yuqori / katta" — suffix `dan` attached without a space
    r"(?:dan\s+(?:oshgan|yuqori|katta|kattaroq)"
    # "yosh va undan katta / yuqori / kattaroq" — `undan` optional
    r"|\s+va\s+(?:undan\s+)?(?:katta|yuqori|kattaroq))",
    re.IGNORECASE,
)


def _query_age_range(q: str) -> tuple[int, int] | None:
    """Extract an explicit age range from the user's question.

    Returns (low, high) inclusive (high=200 means open-ended), or None.
    """
    m = _AGE_DASH_RE.search(q)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo <= hi:
            return lo, hi
    m = _AGE_OPEN_RE.search(q)
    if m:
        return int(m.group(1)), 200
    return None


def _indicator_age_range(name: str | None) -> tuple[int, int] | None:
    """Parse the age range from an indicator name. None if not age-specific."""
    if not name:
        return None
    m = _AGE_DASH_INDICATOR_RE.search(name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _AGE_OPEN_RE.search(name)
    if m:
        return int(m.group(1)), 200
    return None


def _age_range_multiplier(
    q_range: tuple[int, int] | None,
    i_range: tuple[int, int] | None,
) -> float:
    """Score how well an indicator's age range matches the query's.

    - Query has no range: neutral (1.0) — don't bias.
    - Query has range, indicator has none: 0.5 — total/aggregate indicators
      must NOT be presented as answers to age-bracketed questions; equal-
      penalty with partial-overlap brackets so the cross-encoder decides
      rather than 'total' winning by default.
    - Exact match: 1.5 — strong bonus.
    - No overlap: 0.3 — heavy penalty (kept above 0 so cross-encoder still has
      a fallback when no age-bracket indicator covers the range at all).
    - Partial overlap: scaled 0.5..1.0 by Jaccard.
    """
    if q_range is None:
        return 1.0
    if i_range is None:
        return 0.5
    if q_range == i_range:
        return 1.5
    ql, qh = q_range
    il, ih = i_range
    if ih < ql or il > qh:
        return 0.3
    inter = min(qh, ih) - max(ql, il) + 1
    union = max(qh, ih) - min(ql, il) + 1
    jaccard = inter / union if union > 0 else 0.0
    return max(0.5, min(1.0, jaccard))


# ---------------------------------------------------------------------------
# Measure-type axis — keeps "Ishsizlar SONI" from winning when the user asks
# for "ishsiz odamlar FOIZI". The embedder alone can't reliably tell apart
# count / rate / share / index indicators that share most of their nouns, so
# we add a lexical multiplier on top of the cross-encoder score.
# ---------------------------------------------------------------------------

_MEASURE_QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "rate": (
        "foiz", "foizi", "foizini", "foizda",
        "darajasi", "darajada",
        "ulush", "ulushi", "ulushini",
        "percent", "rate", "share",
        "процент", "уровень", "доля",
    ),
    "count": (
        "soni", "sonini", "sonida",
        "nechta", "qancha", "qanchasi",
        "number of", "how many",
        "количество", "число", "сколько",
    ),
    "index": (
        "indeks", "indeksi",
        "koeffitsient", "koeffitsienti",
        "index",
        "индекс", "коэффициент",
    ),
}

_MEASURE_NAME_MARKERS: dict[str, tuple[str, ...]] = {
    "rate": (
        "darajasi", "foizi", "ulushi",
        "rate", "share",
        "уровень", "доля",
    ),
    "count": (
        "soni",
        "number",
        "число", "количество",
    ),
    "index": (
        "indeksi", "koeffitsienti",
        "index",
        "индекс", "коэффициент",
    ),
}


def _query_measure_intent(q: str) -> str | None:
    """Which measure type did the user ask for: rate, count, or index?

    Returns None when no marker is found, so the multiplier degrades to 1.0
    and behavior is unchanged for queries that don't hint at a measure.
    """
    ql = q.lower()
    for measure, hints in _MEASURE_QUERY_HINTS.items():
        if any(h in ql for h in hints):
            return measure
    return None


def _indicator_measure(name: str | None) -> str | None:
    """Classify an indicator's measure type from its name."""
    n = (name or "").lower()
    for measure, markers in _MEASURE_NAME_MARKERS.items():
        if any(m in n for m in markers):
            return measure
    return None


def _measure_multiplier(
    q_measure: str | None, i_measure: str | None
) -> float:
    """Composite multiplier for measure-type match.

    Conservative: only penalises an *explicit* mismatch. If either side has
    no detected measure, returns 1.0 — the catalog has plenty of indicators
    whose name doesn't carry a count/rate marker (raw values, currencies,
    etc.), and we don't want to demote them just for being unmarked.
    """
    if q_measure is None or i_measure is None:
        return 1.0
    return 1.0 if q_measure == i_measure else 0.5


_AGE_BRACKET_INDEX_CACHE: list[tuple[int, str, tuple[int, int]]] | None = None


def _age_bracket_index() -> list[tuple[int, str, tuple[int, int]]]:
    """All age-bracketed population/count indicators in the catalog.

    Built by scrolling Qdrant once and cached. Returns (sdmx_id, name, range)
    for indicators whose name has an age range AND looks like a count
    (not a rate/share/provision/ratio).
    """
    global _AGE_BRACKET_INDEX_CACHE
    if _AGE_BRACKET_INDEX_CACHE is not None:
        return _AGE_BRACKET_INDEX_CACHE

    off_topic = (
        "ta'minlanganligi",
        "taʼminlanganligi",
        "darajasi",
        "indeksi",
        "ulushi",
        "tug'ilgan",
        "tugʻilgan",
        "o'sish",
        "oʻsish",
        "koeffitsienti",
        "o'lim",
        "oʻlim",
    )

    out: list[tuple[int, str, tuple[int, int]]] = []
    try:
        client = _get_client()
        offset = None
        while True:
            records, offset = client.scroll(
                collection_name=_COLLECTION,
                limit=512,
                with_payload=True,
                offset=offset,
            )
            for rec in records:
                p = rec.payload or {}
                name = p.get("name") or ""
                rng = _indicator_age_range(name)
                if rng is None:
                    continue
                lower = name.lower()
                if any(m in lower for m in off_topic):
                    continue
                pid = p.get("id")
                try:
                    pid_int = int(pid)
                except (TypeError, ValueError):
                    continue
                out.append((pid_int, name, rng))
            if offset is None:
                break
    except Exception:
        logger.exception("Failed to build age-bracket index")
        return []

    _AGE_BRACKET_INDEX_CACHE = out
    return out


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
    # matches what this version writes. Schema markers:
    #   v1 → +subset           (dimension-aware rerank)
    #   v2 → +catalog_index    (catalog-order tiebreaker)
    #   v2 → +updated_xlsx     (freshness multiplier)
    #   v3 → point.id == int(payload["id"])  (incremental sync needs stable IDs)
    try:
        info = client.get_collection(_COLLECTION)
        if info.points_count > 0:
            try:
                sample_records = client.scroll(
                    collection_name=_COLLECTION, limit=1, with_payload=True
                )[0]
                if not sample_records:
                    raise ValueError("empty collection")
                sample = sample_records[0]
                first_payload = sample.payload or {}
                if "catalog_index" not in first_payload:
                    logger.info(
                        f"Collection '{_COLLECTION}' missing 'catalog_index' — "
                        f"rebuilding for v2 schema (subset + catalog order + freshness)."
                    )
                    raise ValueError("schema upgrade needed (v2)")
                try:
                    expected_id = int(first_payload.get("id"))
                except (TypeError, ValueError):
                    raise ValueError("schema upgrade needed (v3: unparseable id)")
                if sample.id != expected_id:
                    logger.info(
                        "Detected old sequential point IDs — "
                        "rebuilding for v3 schema (point.id = int(sdmx_id))."
                    )
                    raise ValueError("schema upgrade needed (v3)")
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
    sdmx_ids: list[int] = []
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

            text, payload = build_indicator_text_and_payload(
                item, path, catalog_index=len(texts)
            )
            texts.append(text)
            payloads.append(payload)
            sdmx_ids.append(int(item_id))

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

    # Build Qdrant points — point.id is the SDMX id so incremental sync
    # can upsert/delete by id without a separate mapping.
    points = [
        PointStruct(
            id=sdmx_id,
            vector={
                "dense": dense,
                "sparse": SparseVector(
                    indices=list(sparse.keys()),
                    values=list(sparse.values()),
                ),
            },
            payload={"text": text, **payload},
        )
        for sdmx_id, text, payload, dense, sparse in zip(
            sdmx_ids, texts, payloads, dense_vecs, sparse_weights
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

    # Compute the user's dimensional intent now — we reuse it both for the
    # retrieval-time "neutrality boost" and for the rerank-time subset penalty.
    intent = _query_dimension_intent(question)

    # Expand the query with domain synonyms before encoding. The expanded
    # version is only used for retrieval; the cache key keeps the original
    # so identical user queries still hit the cache.
    encoded_query = expand_query(question)

    # Neutrality boost: when the user did NOT name a demographic or geographic
    # subset, append "total / jami" synonyms so the dense+sparse retrieval is
    # pulled toward indicators tagged Subset: total. Without this, BGE-M3
    # ranks the bare "(jami)" variant well below richer subset variants
    # (age-group, share/ratio) because their indexed text matches more of the
    # query's surface terms — that's how ID 246 ended up at rank 68 while
    # ID 247 (qishloq) reached rank 3 on a neutral query.
    if not intent:
        encoded_query = (
            f"{encoded_query} | jami umumiy total всего общий "
            f"whole population both sexes all areas"
        )

    dense, sparse = encode_query(encoded_query)

    # Over-fetch from RRF so the reranker has a real candidate pool to choose
    # from. RRF gives strong recall; cross-encoder rerank gives precision.
    # Pool grows with k but is capped to keep rerank latency bounded. We widen
    # the pool when the query has an explicit age range so age-bracketed
    # alternatives have a fair chance of surfacing for the warning's
    # constituent-bracket suggestions.
    q_age_range_for_pool = _query_age_range(question)
    rerank_pool = min(max(k * 3, 30), 60)
    if q_age_range_for_pool is not None:
        rerank_pool = min(max(rerank_pool, 120), 150)

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
    # `intent` was already computed above for the retrieval-time boost.

    q_age_range = _query_age_range(question)
    q_measure = _query_measure_intent(question)

    def _composite(payload: dict, base: float) -> float:
        p = payload or {}
        sub = p.get("subset", "") or ""
        upd = p.get("updated_xlsx")
        sts = p.get("status")
        cidx = p.get("catalog_index")
        ind_name = p.get("name") or ""
        return (
            base
            * _subset_penalty(sub, intent)
            * _freshness_multiplier(upd, sts)
            * _catalog_order_multiplier(cidx, _catalog_total)
            * _age_range_multiplier(q_age_range, _indicator_age_range(ind_name))
            * _measure_multiplier(q_measure, _indicator_measure(ind_name))
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

    output_lines: list[str] = []

    # If the user named a specific age range, surface the age-bracket landscape
    # so the LLM can either pick an exact-match indicator, sum constituents, or
    # honestly tell the user no single indicator covers the range. Off-topic
    # exact matches (e.g. "Bolalarning (0-14 yosh) shifoxona o'rinlari..." for
    # "0-14 yosh bolalar soni") should NOT silently get substituted.
    if q_age_range is not None:
        lo, hi = q_age_range
        range_label = f"{lo}+" if hi >= 200 else f"{lo}-{hi}"

        # Collect all overlapping age-bracketed indicators from the pool.
        # Skip indicators whose name suggests they're rates/ratios/provisions
        # rather than counts — those aren't summable into a population count.
        _OFF_TOPIC_MARKERS = (
            "ta'minlanganligi",
            "taʼminlanganligi",
            "darajasi",
            "indeksi",
            "ulushi",
            "tug'ilgan",
            "tugʻilgan",
            "o'sish",
            "oʻsish",
            "koeffitsienti",
        )

        def _is_off_topic_for_count(name: str) -> bool:
            n = (name or "").lower()
            return any(m in n for m in _OFF_TOPIC_MARKERS)

        overlapping: list[tuple[int, str, tuple[int, int], bool]] = []
        exact_match_count_topic = False
        for point in results:
            p = point.payload or {}
            i_range = _indicator_age_range(p.get("name"))
            if i_range is None:
                continue
            il, ih = i_range
            if ih < lo or il > hi:
                continue
            name = p.get("name") or ""
            off_topic = _is_off_topic_for_count(name)
            overlapping.append((p.get("id"), name, i_range, off_topic))
            if i_range == q_age_range and not off_topic:
                exact_match_count_topic = True

        if not exact_match_count_topic:
            warning = [
                f"⚠️ NO EXACT COUNT INDICATOR for age range {range_label}. "
                f"The catalog has no single indicator giving a population/count "
                f"figure for exactly {range_label}."
            ]
            # Suggest summable on-topic constituents — pull from full catalog
            # age-bracket index (not just the rerank pool), since population
            # age brackets often don't surface in dense+sparse search for
            # range-mismatched queries like "0-14".
            catalog_brackets = [
                (cid, cname, crng)
                for (cid, cname, crng) in _age_bracket_index()
                if not (crng[1] < lo or crng[0] > hi)  # overlap test
            ]
            # Deduplicate against the rerank-pool overlapping list to keep
            # ordering stable; prefer the catalog-walk list since it's
            # exhaustive.
            seen = {cid for cid, _, _ in catalog_brackets}
            for (i, n, r, off) in overlapping:
                if not off and i not in seen:
                    catalog_brackets.append((i, n, r))
                    seen.add(i)
            constituents = catalog_brackets
            if constituents:
                warning.append(
                    f"Age brackets that overlap {range_label} (jami / total "
                    f"variants only — gender-specific subsets are excluded "
                    f"below to avoid double-counting):"
                )
                # Prefer the "jami" / total variants — exclude gender splits
                # so the agent doesn't accidentally add a male subset to the
                # total and double-count.
                gender_markers = ("(ayollar)", "(erkaklar)", "(ayol)", "(erkak)")
                jami_constituents = [
                    (cid, cname, crng)
                    for (cid, cname, crng) in constituents
                    if not any(g in cname.lower() for g in gender_markers)
                ]
                for cid, cname, (cl, ch) in jami_constituents[:15]:
                    if cl >= lo and ch <= hi:
                        cover = "fully inside"
                    elif cl < lo and ch > hi:
                        cover = "extends both ends"
                    elif ch > hi:
                        cover = f"extends past upper bound (covers up to {ch})"
                    else:
                        cover = f"extends below lower bound (starts at {cl})"
                    warning.append(f"  - SDMX {cid}: {cname} [{cover}]")
                warning.append(
                    "CRITICAL RULE: Do NOT silently sum these and present a "
                    "single number — past attempts have produced wrong totals "
                    "by double-counting gender subsets, inventing intermediate "
                    "ranges, or mislabeling units. Instead: present this "
                    "bracket list to the user, explain that no single "
                    "indicator covers the requested range, and ask which "
                    "brackets to fetch. Only sum if the user explicitly "
                    "confirms, and only after fetching each bracket's value "
                    "via the value-fetching tool."
                )
            # Flag off-topic exact-range matches so the LLM doesn't use them
            off_topic_exact = [
                (i, n) for (i, n, r, off) in overlapping if r == q_age_range and off
            ]
            if off_topic_exact:
                warning.append(
                    f"NOTE: Some indicators below have the exact range "
                    f"{range_label} in their name but are about a DIFFERENT "
                    f"topic (rates, provisions, ratios — not counts). Do NOT "
                    f"present their values as the requested count:"
                )
                for cid, cname in off_topic_exact[:5]:
                    warning.append(f"  - SDMX {cid}: {cname}")
            if not constituents and not off_topic_exact:
                warning.append(
                    "No age-bracketed alternatives in the top results. Tell the "
                    "user explicitly that no indicator covers this range; do NOT "
                    "silently substitute a total-population or unrelated indicator."
                )
            output_lines.append("\n".join(warning) + "\n")

    output_lines.append(f"Found {len(results)} semantically similar indicator(s):\n")

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
