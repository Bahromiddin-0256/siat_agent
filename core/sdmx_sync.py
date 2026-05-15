"""SDMX katalogni incremental sinxronlash.

See docs/superpowers/specs/2026-05-15-sdmx-incremental-sync-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# Scalar fields on CatalogEntry that contribute to the embedding text. Any
# change here forces re-embedding. `tags` is compared separately as a set.
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
class DiffSets:
    bootstrap: bool = False
    added: set[int] = field(default_factory=set)
    removed: set[int] = field(default_factory=set)
    inactive: set[int] = field(default_factory=set)
    metadata: set[int] = field(default_factory=set)
    data_only: set[int] = field(default_factory=set)
    unchanged_count: int = 0


def _embedding_inputs_differ(old: "CatalogEntry", new: "CatalogEntry") -> bool:
    for field_name in _EMBEDDING_SCALAR_FIELDS:
        if getattr(old, field_name) != getattr(new, field_name):
            return True
    if set(old.tags) != set(new.tags):
        return True
    return False


def compute_diff(
    *, old: dict[int, "CatalogEntry"], new: dict[int, "CatalogEntry"]
) -> DiffSets:
    """Classify catalog changes into added/removed/inactive/metadata/data_only.

    `old={}` (no prior catalog on disk) returns bootstrap=True; the caller
    is expected to take the full-rebuild path in that case.
    """
    if not old:
        return DiffSets(bootstrap=True)

    diff = DiffSets()
    old_ids = old.keys()
    new_ids = new.keys()

    diff.added = set(new_ids) - set(old_ids)
    diff.removed = set(old_ids) - set(new_ids)

    for id_ in old_ids & new_ids:
        old_e = old[id_]
        new_e = new[id_]

        if old_e.is_active and not new_e.is_active:
            diff.inactive.add(id_)
            continue

        if _embedding_inputs_differ(old_e, new_e):
            diff.metadata.add(id_)
            continue

        if old_e.updated_xlsx != new_e.updated_xlsx:
            diff.data_only.add(id_)
            continue

        diff.unchanged_count += 1

    return diff


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


def walk_catalog(nodes: Iterable[dict]) -> dict[int, CatalogEntry]:
    """DFS-walk main.json, return {id: CatalogEntry} for nodes that have a code.

    Nodes without `code` are treated as categories: not indexed themselves,
    but their children are still walked. Duplicate IDs keep the first hit
    (matches existing rag_tool behavior).
    """
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
