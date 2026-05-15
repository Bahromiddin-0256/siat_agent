"""Tests for compute_diff — classify catalog changes between old and new."""
from core.sdmx_sync import CatalogEntry, compute_diff


def _entry(
    id: int,
    *,
    is_active: bool = True,
    name: str = "X",
    name_uz: str | None = None,
    name_en: str | None = None,
    name_ru: str | None = None,
    tags: list[str] | None = None,
    period: str | None = None,
    department: str | None = None,
    status: str | None = None,
    updated_xlsx: str | None = None,
) -> CatalogEntry:
    return CatalogEntry(
        id=id,
        code=f"C{id}",
        is_active=is_active,
        name=name,
        name_uz=name_uz,
        name_en=name_en,
        name_ru=name_ru,
        tags=tags if tags is not None else [],
        period=period,
        department=department,
        status=status,
        updated_xlsx=updated_xlsx,
        path=[name],
    )


def test_empty_old_signals_bootstrap():
    diff = compute_diff(old={}, new={1: _entry(1)})
    assert diff.bootstrap is True


def test_identical_catalogs_all_unchanged():
    e = _entry(1, updated_xlsx="2026-01-01")
    diff = compute_diff(old={1: e}, new={1: e})
    assert diff.bootstrap is False
    assert diff.added == set()
    assert diff.removed == set()
    assert diff.metadata == set()
    assert diff.data_only == set()
    assert diff.inactive == set()
    assert diff.unchanged_count == 1


def test_new_id_is_added():
    old = {1: _entry(1)}
    new = {1: _entry(1), 2: _entry(2)}
    diff = compute_diff(old=old, new=new)
    assert diff.added == {2}


def test_updated_xlsx_change_only_is_data_only():
    old = {1: _entry(1, updated_xlsx="2026-01-01")}
    new = {1: _entry(1, updated_xlsx="2026-02-01")}
    diff = compute_diff(old=old, new=new)
    assert diff.data_only == {1}
    assert diff.metadata == set()


def test_name_uz_change_is_metadata():
    old = {1: _entry(1, name_uz="Aholi")}
    new = {1: _entry(1, name_uz="Aholi soni")}
    diff = compute_diff(old=old, new=new)
    assert diff.metadata == {1}
    assert diff.data_only == set()


def test_both_data_and_metadata_change_classified_as_metadata():
    old = {1: _entry(1, name_uz="A", updated_xlsx="2026-01")}
    new = {1: _entry(1, name_uz="B", updated_xlsx="2026-02")}
    diff = compute_diff(old=old, new=new)
    assert diff.metadata == {1}
    assert diff.data_only == set()


def test_inactive_takes_precedence():
    old = {1: _entry(1, is_active=True, name_uz="A")}
    new = {1: _entry(1, is_active=False, name_uz="B")}
    diff = compute_diff(old=old, new=new)
    assert diff.inactive == {1}
    assert diff.metadata == set()


def test_removed_id_classified():
    old = {1: _entry(1), 2: _entry(2)}
    new = {1: _entry(1)}
    diff = compute_diff(old=old, new=new)
    assert diff.removed == {2}


def test_tag_order_change_is_not_metadata_change():
    """Tags are compared as sets — order does not matter."""
    old = {1: _entry(1, tags=["a", "b"])}
    new = {1: _entry(1, tags=["b", "a"])}
    diff = compute_diff(old=old, new=new)
    assert diff.metadata == set()
    assert diff.unchanged_count == 1


def test_tag_value_change_is_metadata():
    old = {1: _entry(1, tags=["a"])}
    new = {1: _entry(1, tags=["a", "b"])}
    diff = compute_diff(old=old, new=new)
    assert diff.metadata == {1}


def test_each_embedding_field_triggers_metadata():
    """Every field in EMBEDDING_FIELDS should trigger metadata classification."""
    base = _entry(1)
    changes = {
        "name": "Y",
        "name_uz": "Y",
        "name_en": "Y",
        "name_ru": "Y",
        "tags": ["new"],
        "period": "month",
        "department": "Other",
        "status": "deprecated",
    }
    for field, new_value in changes.items():
        new_entry = _entry(1, **{field: new_value})
        diff = compute_diff(old={1: base}, new={1: new_entry})
        assert diff.metadata == {1}, f"field {field} should trigger metadata"


def test_inactive_only_classified_if_active_in_old():
    """If item was already inactive and stays inactive, it's unchanged."""
    e = _entry(1, is_active=False)
    diff = compute_diff(old={1: e}, new={1: e})
    assert diff.inactive == set()
    assert diff.unchanged_count == 1
