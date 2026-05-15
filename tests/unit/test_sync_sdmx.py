"""Integration test for sync_sdmx with respx-mocked httpx and in-memory Qdrant."""
import json
from pathlib import Path

import httpx
import pytest
import respx
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)

from core.sdmx_sync import SyncConfig, sync_sdmx


CATALOG_URL = "https://test.example/sdmx/json/"
SDMX_DATA_URL_TEMPLATE = "https://test.example/sdmx_data_{sdmx_id}.json"
COLLECTION = "test_sdmx"


def _node(
    id_: int,
    code: str,
    name_uz: str,
    *,
    updated_xlsx: str = "2026-01-01",
    is_active: bool = True,
    children: list | None = None,
):
    return {
        "id": id_,
        "code": code,
        "name": name_uz,
        "name_uz": name_uz,
        "name_en": f"EN-{code}",
        "name_ru": f"RU-{code}",
        "tags": ["t1"],
        "period": "year",
        "department": "Test",
        "status": "active",
        "is_active": is_active,
        "updated_xlsx": updated_xlsx,
        "updated_at": "2026-01-01",
        "children": children or [],
    }


def _stub_embed_fn(texts: list[str]):
    """Deterministic 1024-dim dense + small sparse so we can build real points."""
    dense = [[0.0] * 1024 for _ in texts]
    for i, vec in enumerate(dense):
        vec[i % 1024] = 1.0
    sparse = [{0: 1.0} for _ in texts]
    return dense, sparse


def _make_collection(client: QdrantClient) -> None:
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse": SparseVectorParams(index=SparseIndexParams())},
    )


def _config(tmp_path: Path, client: QdrantClient) -> SyncConfig:
    sdmxs = tmp_path / "sdmxs"
    sdmxs.mkdir()
    return SyncConfig(
        catalog_url=CATALOG_URL,
        sdmx_data_url_template=SDMX_DATA_URL_TEMPLATE,
        main_json_path=tmp_path / "main.json",
        sdmxs_dir=sdmxs,
        failed_ids_path=tmp_path / ".sync_failed_ids.json",
        lock_path=tmp_path / ".sync.lock",
        qdrant_client_factory=lambda: client,
        embed_fn=_stub_embed_fn,
        qdrant_collection=COLLECTION,
        fetch_concurrency=2,
    )


@respx.mock
def test_bootstrap_when_no_main_json_runs_full_index(tmp_path):
    """First-ever sync with no main.json on disk takes the bootstrap path."""
    client = QdrantClient(":memory:")
    _make_collection(client)

    catalog = [_node(1, "A", "Aholi"), _node(2, "B", "Bola")]
    respx.get(CATALOG_URL).mock(return_value=httpx.Response(200, json=catalog))
    for sid in (1, 2):
        respx.get(SDMX_DATA_URL_TEMPLATE.format(sdmx_id=sid)).mock(
            return_value=httpx.Response(200, json={"values": [{"v": sid}]})
        )

    report = sync_sdmx(config=_config(tmp_path, client))

    assert report.reason == "bootstrap"
    info = client.get_collection(COLLECTION)
    assert info.points_count == 2
    # SDMX IDs become Qdrant point IDs
    pts = client.scroll(collection_name=COLLECTION, limit=10)[0]
    assert {p.id for p in pts} == {1, 2}


@respx.mock
def test_incremental_sync_added_data_only_metadata(tmp_path):
    """Normal incremental: 1 added + 1 data_only + 1 metadata + 0 removed."""
    client = QdrantClient(":memory:")
    _make_collection(client)

    # Bootstrap with v1 (no main.json on disk yet — triggers bootstrap)
    v1 = [
        _node(1, "A", "Aholi", updated_xlsx="2026-01-01"),
        _node(2, "B", "Bola", updated_xlsx="2026-01-01"),
        _node(3, "C", "Chiqim", updated_xlsx="2026-01-01"),
    ]
    cfg = _config(tmp_path, client)
    for sid in (1, 2, 3):
        respx.get(SDMX_DATA_URL_TEMPLATE.format(sdmx_id=sid)).mock(
            return_value=httpx.Response(200, json={"v": sid})
        )
    respx.get(CATALOG_URL).mock(return_value=httpx.Response(200, json=v1))
    bootstrap_report = sync_sdmx(config=cfg)
    assert bootstrap_report.reason == "bootstrap"
    respx.reset()

    # v2 catalog: id=1 keeps same; id=2 data_only (updated_xlsx changes);
    # id=3 metadata (name_uz changes); id=4 added; nothing removed.
    v2 = [
        _node(1, "A", "Aholi", updated_xlsx="2026-01-01"),
        _node(2, "B", "Bola", updated_xlsx="2026-03-01"),  # data_only
        _node(3, "C", "Chiqimlar", updated_xlsx="2026-01-01"),  # metadata
        _node(4, "D", "Daromad", updated_xlsx="2026-03-01"),  # added
    ]
    respx.get(CATALOG_URL).mock(return_value=httpx.Response(200, json=v2))
    for sid in (2, 3, 4):
        respx.get(SDMX_DATA_URL_TEMPLATE.format(sdmx_id=sid)).mock(
            return_value=httpx.Response(200, json={"v": sid})
        )

    embed_calls: list[list[str]] = []

    def tracking_embed(texts):
        embed_calls.append(list(texts))
        return _stub_embed_fn(texts)

    cfg.embed_fn = tracking_embed
    report = sync_sdmx(config=cfg)

    assert report.added == [4]
    assert report.data_only == [2]
    assert report.metadata == [3]
    assert report.removed == []
    assert report.inactive == []
    assert report.failed_ids == []

    # Embedding called only for added + metadata = 2 items
    assert sum(len(b) for b in embed_calls) == 2

    # Qdrant now has 4 points (1,2,3,4)
    info = client.get_collection(COLLECTION)
    assert info.points_count == 4
    pts = client.scroll(collection_name=COLLECTION, limit=10, with_payload=True)[0]
    by_id = {p.id: p for p in pts}
    assert set(by_id) == {1, 2, 3, 4}
    # data_only item: payload.updated_xlsx refreshed
    assert by_id[2].payload["updated_xlsx"] == "2026-03-01"
    # main.json on disk now is v2
    on_disk = json.loads(cfg.main_json_path.read_text())
    assert any(n["id"] == 4 for n in on_disk)


@respx.mock
def test_removed_and_inactive_are_deleted(tmp_path):
    """Catalog drop or is_active:false → delete from Qdrant."""
    client = QdrantClient(":memory:")
    _make_collection(client)

    v1 = [
        _node(1, "A", "A"),
        _node(2, "B", "B"),
        _node(3, "C", "C"),
    ]
    cfg = _config(tmp_path, client)

    respx.get(CATALOG_URL).mock(return_value=httpx.Response(200, json=v1))
    for sid in (1, 2, 3):
        respx.get(SDMX_DATA_URL_TEMPLATE.format(sdmx_id=sid)).mock(
            return_value=httpx.Response(200, json={})
        )
    sync_sdmx(config=cfg)  # bootstrap
    respx.reset()

    # v2: id=1 kept active; id=2 went inactive; id=3 fully removed.
    v2 = [
        _node(1, "A", "A"),
        _node(2, "B", "B", is_active=False),
    ]
    respx.get(CATALOG_URL).mock(return_value=httpx.Response(200, json=v2))
    report = sync_sdmx(config=cfg)

    assert set(report.inactive) == {2}
    assert set(report.removed) == {3}
    info = client.get_collection(COLLECTION)
    assert info.points_count == 1


@respx.mock
def test_concurrent_call_returns_skipped(tmp_path):
    """A second sync_sdmx call while another holds the lock returns skipped."""
    client = QdrantClient(":memory:")
    _make_collection(client)
    cfg = _config(tmp_path, client)
    cfg.main_json_path.write_text("[]")
    respx.get(CATALOG_URL).mock(return_value=httpx.Response(200, json=[]))

    # Manually hold the lock to simulate a concurrent run
    import fcntl

    cfg.lock_path.parent.mkdir(parents=True, exist_ok=True)
    holder = open(cfg.lock_path, "w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        report = sync_sdmx(config=cfg)
        assert report.skipped is True
        assert report.reason == "already_running"
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()


@respx.mock
def test_failed_sdmx_fetch_is_tracked_and_retried(tmp_path):
    """When an sdmx fetch fails, ID lands in failed_ids and is retried next run."""
    client = QdrantClient(":memory:")
    _make_collection(client)
    cfg = _config(tmp_path, client)

    v1 = [_node(1, "A", "A")]
    respx.get(CATALOG_URL).mock(return_value=httpx.Response(200, json=v1))
    respx.get(SDMX_DATA_URL_TEMPLATE.format(sdmx_id=1)).mock(
        return_value=httpx.Response(200, json={})
    )
    sync_sdmx(config=cfg)  # bootstrap
    respx.reset()

    # v2 adds id=2 but its sdmx data fetch fails
    v2 = [_node(1, "A", "A"), _node(2, "B", "B")]
    respx.get(CATALOG_URL).mock(return_value=httpx.Response(200, json=v2))
    respx.get(SDMX_DATA_URL_TEMPLATE.format(sdmx_id=2)).mock(
        return_value=httpx.Response(500)
    )

    report = sync_sdmx(config=cfg)
    assert 2 in report.failed_ids
    # main.json is committed regardless (partial success)
    assert json.loads(cfg.main_json_path.read_text())[1]["id"] == 2
    # failed_ids file persisted
    assert json.loads(cfg.failed_ids_path.read_text()) == [2]

    # Next run with fetch now working → id=2 retried, no longer failed
    respx.reset()
    respx.get(CATALOG_URL).mock(return_value=httpx.Response(200, json=v2))
    respx.get(SDMX_DATA_URL_TEMPLATE.format(sdmx_id=2)).mock(
        return_value=httpx.Response(200, json={})
    )
    report2 = sync_sdmx(config=cfg)
    assert report2.failed_ids == []
    assert not cfg.failed_ids_path.exists()
