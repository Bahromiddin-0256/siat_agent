"""SDMX katalogni incremental sinxronlash.

See docs/superpowers/specs/2026-05-15-sdmx-incremental-sync-design.md.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import httpx

logger = logging.getLogger(__name__)


_EMBEDDING_SCALAR_FIELDS = (
    "name",
    "name_uz",
    "name_en",
    "name_ru",
    "period",
    "department",
    "status",
)


@dataclass
class CatalogEntry:
    id: int
    code: str | None
    is_active: bool
    name: str | None
    name_uz: str | None
    name_en: str | None
    name_ru: str | None
    tags: list[str]
    period: str | None
    department: str | None
    status: str | None
    updated_xlsx: str | None
    path: list[str]


@dataclass
class DiffSets:
    bootstrap: bool = False
    added: set[int] = field(default_factory=set)
    removed: set[int] = field(default_factory=set)
    inactive: set[int] = field(default_factory=set)
    metadata: set[int] = field(default_factory=set)
    data_only: set[int] = field(default_factory=set)
    unchanged_count: int = 0


@dataclass
class SyncReport:
    skipped: bool = False
    reason: str | None = None
    added: list[int] = field(default_factory=list)
    data_only: list[int] = field(default_factory=list)
    metadata: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    inactive: list[int] = field(default_factory=list)
    unchanged: int = 0
    failed_ids: list[int] = field(default_factory=list)
    duration_s: float = 0.0
    trigger: str = "manual"


@dataclass
class SyncConfig:
    catalog_url: str
    sdmx_data_url_template: str
    main_json_path: Path
    sdmxs_dir: Path
    failed_ids_path: Path
    lock_path: Path
    qdrant_client_factory: Callable
    embed_fn: Callable
    qdrant_collection: str
    fetch_concurrency: int = 5
    http_timeout_s: float = 30.0


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def walk_catalog(nodes: Iterable[dict]) -> dict[int, CatalogEntry]:
    """DFS-walk main.json, return {id: CatalogEntry} for nodes that have a code."""
    index: dict[int, CatalogEntry] = {}

    def visit(items: Iterable[dict], path: list[str]) -> None:
        for item in items:
            item_id = item.get("id")
            name = item.get("name")
            next_path = path + [name] if name else path

            if item.get("code") and item_id is not None and item_id not in index:
                index[item_id] = CatalogEntry(
                    id=item_id,
                    code=item.get("code"),
                    is_active=item.get("is_active", True),
                    name=name,
                    name_uz=item.get("name_uz"),
                    name_en=item.get("name_en"),
                    name_ru=item.get("name_ru"),
                    tags=list(item.get("tags") or []),
                    period=item.get("period"),
                    department=item.get("department"),
                    status=item.get("status"),
                    updated_xlsx=item.get("updated_xlsx"),
                    path=next_path,
                )

            children = item.get("children") or []
            if children:
                visit(children, next_path)

    visit(nodes, [])
    return index


def _embedding_inputs_differ(old: CatalogEntry, new: CatalogEntry) -> bool:
    for fld in _EMBEDDING_SCALAR_FIELDS:
        if getattr(old, fld) != getattr(new, fld):
            return True
    if set(old.tags) != set(new.tags):
        return True
    return False


def compute_diff(
    *, old: dict[int, CatalogEntry], new: dict[int, CatalogEntry]
) -> DiffSets:
    """Classify catalog changes."""
    if not old:
        return DiffSets(bootstrap=True)

    diff = DiffSets()
    old_ids = set(old.keys())
    new_ids = set(new.keys())

    # Only index items that are currently active. Inactive newcomers are
    # silently ignored (they aren't in Qdrant and shouldn't be added).
    diff.added = {id_ for id_ in new_ids - old_ids if new[id_].is_active}
    diff.removed = old_ids - new_ids

    for id_ in old_ids & new_ids:
        old_e = old[id_]
        new_e = new[id_]
        # active -> inactive transition: delete from Qdrant
        if old_e.is_active and not new_e.is_active:
            diff.inactive.add(id_)
            continue
        # already-inactive: not in Qdrant, ignore any further changes
        if not new_e.is_active:
            diff.unchanged_count += 1
            continue
        if _embedding_inputs_differ(old_e, new_e):
            diff.metadata.add(id_)
            continue
        if old_e.updated_xlsx != new_e.updated_xlsx:
            diff.data_only.add(id_)
            continue
        diff.unchanged_count += 1

    return diff


def _walk_for_raw_items(
    nodes: Iterable[dict],
) -> Iterable[tuple[dict, list[str], int]]:
    """Yield (item, path, dfs_index) for every node with a code.

    The dfs_index is the position in the new catalog's DFS traversal, used as
    `catalog_index` payload field for ranking tiebreaker.
    """
    seen: set[int] = set()
    counter = [0]

    def visit(items: Iterable[dict], path: list[str]):
        for item in items:
            item_id = item.get("id")
            name = item.get("name")
            next_path = path + [name] if name else path
            if item.get("code") and item_id is not None and item_id not in seen:
                seen.add(item_id)
                yield item, list(path), counter[0]
                counter[0] += 1
            children = item.get("children") or []
            if children:
                yield from visit(children, next_path)

    yield from visit(nodes, [])


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


@contextmanager
def _try_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            yield False
            return
        yield True
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
            f.close()
        except Exception:
            pass


def _cleanup_stale_tmp(config: SyncConfig) -> None:
    new_main = config.main_json_path.with_suffix(".json.new")
    if new_main.exists():
        new_main.unlink()
    if config.sdmxs_dir.exists():
        for tmp in config.sdmxs_dir.glob("*.tmp"):
            tmp.unlink()


def _load_failed_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return set()


def _write_failed_ids(path: Path, failed: Iterable[int]) -> None:
    failed_list = sorted(failed)
    if not failed_list:
        if path.exists():
            path.unlink()
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(failed_list))
    os.replace(tmp, path)


async def _fetch_catalog_async(
    url: str, timeout_s: float
) -> list[dict]:
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


async def _fetch_one_sdmx(
    client: httpx.AsyncClient,
    sdmx_id: int,
    url_template: str,
    sdmxs_dir: Path,
) -> bool:
    url = url_template.format(sdmx_id=sdmx_id)
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("Failed to fetch sdmx data for id=%s", sdmx_id)
        return False

    target = sdmxs_dir / f"sdmx_data_{sdmx_id}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return True


async def _fetch_sdmx_files(
    ids: set[int], config: SyncConfig
) -> tuple[set[int], set[int]]:
    """Returns (ok_set, failed_set)."""
    if not ids:
        return set(), set()
    config.sdmxs_dir.mkdir(parents=True, exist_ok=True)
    ok: set[int] = set()
    failed: set[int] = set()
    sem = asyncio.Semaphore(config.fetch_concurrency)

    async def go(sid: int, client: httpx.AsyncClient):
        async with sem:
            if await _fetch_one_sdmx(
                client, sid, config.sdmx_data_url_template, config.sdmxs_dir
            ):
                ok.add(sid)
            else:
                failed.add(sid)

    async with httpx.AsyncClient(timeout=config.http_timeout_s) as client:
        await asyncio.gather(*(go(sid, client) for sid in ids))
    return ok, failed


# ---------------------------------------------------------------------------
# Vector ops
# ---------------------------------------------------------------------------


def _ensure_collection(client, collection: str) -> None:
    """Create the collection if missing. Schema matches initialize_rag_vectorstore."""
    from qdrant_client.models import (
        Distance,
        SparseIndexParams,
        SparseVectorParams,
        VectorParams,
    )

    try:
        client.get_collection(collection)
    except Exception:
        client.create_collection(
            collection_name=collection,
            vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
            sparse_vectors_config={
                "sparse": SparseVectorParams(index=SparseIndexParams())
            },
        )


def _apply_vector_changes(
    diff: DiffSets,
    new_catalog: list[dict],
    config: SyncConfig,
) -> None:
    """Upsert/set_payload/delete points in Qdrant."""
    from qdrant_client.models import PointStruct, SparseVector

    from tools.rag_tool import build_indicator_text_and_payload

    client = config.qdrant_client_factory()
    _ensure_collection(client, config.qdrant_collection)

    # Build (item, path, dfs_index) map from new catalog for points we need
    items_by_id: dict[int, tuple[dict, list[str], int]] = {}
    for item, path, dfs_idx in _walk_for_raw_items(new_catalog):
        items_by_id[item["id"]] = (item, path, dfs_idx)

    # --- 1. Embed + upsert (added ∪ metadata) ---
    to_embed_ids = sorted(diff.added | diff.metadata)
    if to_embed_ids:
        texts: list[str] = []
        payloads: list[dict] = []
        for sid in to_embed_ids:
            item, path, dfs_idx = items_by_id[sid]
            text, payload = build_indicator_text_and_payload(item, path, dfs_idx)
            texts.append(text)
            payloads.append(payload)
        dense_vecs, sparse_weights = config.embed_fn(texts)
        points = [
            PointStruct(
                id=sid,
                vector={
                    "dense": dense,
                    "sparse": SparseVector(
                        indices=list(sparse.keys()),
                        values=list(sparse.values()),
                    ),
                },
                payload={"text": text, **payload},
            )
            for sid, text, payload, dense, sparse in zip(
                to_embed_ids, texts, payloads, dense_vecs, sparse_weights
            )
        ]
        # Upsert in batches of 100 to match existing pattern
        batch = 100
        for i in range(0, len(points), batch):
            client.upsert(
                collection_name=config.qdrant_collection,
                points=points[i : i + batch],
            )

    # --- 2. set_payload (data_only) — only refresh updated_xlsx ---
    for sid in diff.data_only:
        item, _, _ = items_by_id[sid]
        client.set_payload(
            collection_name=config.qdrant_collection,
            payload={"updated_xlsx": item.get("updated_xlsx")},
            points=[sid],
        )

    # --- 3. Delete (removed ∪ inactive) ---
    to_delete = sorted(diff.removed | diff.inactive)
    if to_delete:
        client.delete(
            collection_name=config.qdrant_collection,
            points_selector=to_delete,
        )


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def _do_bootstrap(
    config: SyncConfig,
    new_json_path: Path,
    started: float,
    trigger: str,
) -> SyncReport:
    """Full rebuild from scratch — used when there's no old main.json."""
    catalog = json.loads(new_json_path.read_text())
    item_index = walk_catalog(catalog)

    # Fetch all sdmx data files
    ok, failed = asyncio.run(_fetch_sdmx_files(set(item_index.keys()), config))

    # Index everything in Qdrant from scratch
    diff = DiffSets(added=ok)
    _apply_vector_changes(diff, catalog, config)

    # Commit
    os.replace(new_json_path, config.main_json_path)
    _write_failed_ids(config.failed_ids_path, failed)

    return SyncReport(
        reason="bootstrap",
        added=sorted(ok),
        failed_ids=sorted(failed),
        duration_s=time.time() - started,
        trigger=trigger,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def sync_sdmx(
    *,
    force_full: bool = False,
    trigger: str = "manual",
    config: SyncConfig | None = None,
) -> SyncReport:
    """Incremental SDMX catalog sync.

    Returns a SyncReport describing what changed. Safe to call concurrently:
    a second call while a sync is in progress returns skipped=True.
    """
    if config is None:
        config = default_config()

    started = time.time()

    with _try_lock(config.lock_path) as got_lock:
        if not got_lock:
            return SyncReport(
                skipped=True,
                reason="already_running",
                trigger=trigger,
                duration_s=time.time() - started,
            )

        _cleanup_stale_tmp(config)

        # Download new catalog
        try:
            new_catalog = asyncio.run(
                _fetch_catalog_async(config.catalog_url, config.http_timeout_s)
            )
        except Exception:
            logger.exception("Catalog fetch failed")
            return SyncReport(
                skipped=True,
                reason="catalog_fetch_failed",
                trigger=trigger,
                duration_s=time.time() - started,
            )

        new_json_path = config.main_json_path.with_suffix(".json.new")
        new_json_path.parent.mkdir(parents=True, exist_ok=True)
        new_json_path.write_text(
            json.dumps(new_catalog, ensure_ascii=False), encoding="utf-8"
        )

        # Bootstrap path
        if force_full or not config.main_json_path.exists():
            return _do_bootstrap(config, new_json_path, started, trigger)

        # Normal incremental path
        old_catalog = json.loads(config.main_json_path.read_text())
        old_index = walk_catalog(old_catalog)
        new_index = walk_catalog(new_catalog)
        diff = compute_diff(old=old_index, new=new_index)

        # Retry IDs that failed last run
        prev_failed = _load_failed_ids(config.failed_ids_path)
        for fid in prev_failed:
            if fid in new_index:
                diff.added.add(fid)
                # If it was previously classified as unchanged/data_only/metadata,
                # remove from those sets to avoid double-handling.
                diff.data_only.discard(fid)
                diff.metadata.discard(fid)

        # Network: fetch sdmx data for added | data_only | metadata
        to_fetch = diff.added | diff.data_only | diff.metadata
        _, fetch_failed = asyncio.run(_fetch_sdmx_files(to_fetch, config))

        # Drop failed IDs from operation sets (they'll retry next time)
        diff.added -= fetch_failed
        diff.data_only -= fetch_failed
        diff.metadata -= fetch_failed

        # Apply vector changes
        _apply_vector_changes(diff, new_catalog, config)

        # Atomic catalog commit
        os.replace(new_json_path, config.main_json_path)
        _write_failed_ids(config.failed_ids_path, fetch_failed)

        return SyncReport(
            added=sorted(diff.added),
            data_only=sorted(diff.data_only),
            metadata=sorted(diff.metadata),
            removed=sorted(diff.removed),
            inactive=sorted(diff.inactive),
            unchanged=diff.unchanged_count,
            failed_ids=sorted(fetch_failed),
            duration_s=time.time() - started,
            trigger=trigger,
        )


def default_config() -> SyncConfig:
    """Production config from settings."""
    from core.settings import settings
    from tools.embedder import encode_dense_sparse
    from tools.qdrant_shared_client import get_shared_client
    from tools.rag_tool import _COLLECTION

    BASE = Path(__file__).resolve().parents[1]
    return SyncConfig(
        catalog_url=settings.sdmx_catalog_url,
        sdmx_data_url_template="https://api.siat.stat.uz/media/uploads/sdmx/sdmx_data_{sdmx_id}.json",
        main_json_path=BASE / "jsons" / "main.json",
        sdmxs_dir=BASE / "jsons" / "sdmxs",
        failed_ids_path=BASE / "jsons" / ".sync_failed_ids.json",
        lock_path=BASE / "vector" / ".sync.lock",
        qdrant_client_factory=get_shared_client,
        embed_fn=encode_dense_sparse,
        qdrant_collection=_COLLECTION,
    )
