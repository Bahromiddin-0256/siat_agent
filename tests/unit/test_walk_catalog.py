"""Tests for catalog walking (DFS extraction of indicators with codes)."""
from core.sdmx_sync import walk_catalog


def test_empty_catalog_returns_empty_index():
    assert walk_catalog([]) == {}


def test_single_leaf_with_code_is_indexed():
    catalog = [
        {
            "id": 42,
            "code": "POP_TOTAL",
            "name": "Population",
            "name_uz": "Aholi",
            "name_en": "Population",
            "name_ru": "Население",
            "tags": ["demographics"],
            "period": "year",
            "department": "Demo",
            "status": "active",
            "is_active": True,
            "updated_xlsx": "2026-01-15",
            "children": [],
        }
    ]
    index = walk_catalog(catalog)

    assert set(index.keys()) == {42}
    entry = index[42]
    assert entry.id == 42
    assert entry.code == "POP_TOTAL"
    assert entry.name == "Population"
    assert entry.name_uz == "Aholi"
    assert entry.tags == ["demographics"]
    assert entry.updated_xlsx == "2026-01-15"
    assert entry.is_active is True
    assert entry.path == ["Population"]


def test_node_without_code_is_skipped_but_children_walked():
    """Categories (no code) are skipped, but their indicator children are kept."""
    catalog = [
        {
            "id": 1,
            "code": None,  # category, not indicator
            "name": "Demographics",
            "children": [
                {
                    "id": 10,
                    "code": "POP",
                    "name": "Population",
                    "is_active": True,
                    "updated_xlsx": "2026-01-01",
                    "children": [],
                }
            ],
        }
    ]
    index = walk_catalog(catalog)
    assert set(index.keys()) == {10}
    assert index[10].path == ["Demographics", "Population"]


def test_nested_dfs_returns_all_indicators():
    catalog = [
        {
            "id": 1,
            "code": None,
            "name": "Root",
            "children": [
                {
                    "id": 2,
                    "code": "A",
                    "name": "A",
                    "is_active": True,
                    "children": [],
                },
                {
                    "id": 3,
                    "code": None,
                    "name": "SubCat",
                    "children": [
                        {
                            "id": 4,
                            "code": "B",
                            "name": "B",
                            "is_active": True,
                            "children": [],
                        }
                    ],
                },
            ],
        }
    ]
    index = walk_catalog(catalog)
    assert set(index.keys()) == {2, 4}


def test_is_active_false_still_indexed():
    """Inactive items are kept in index — diff classifier handles them."""
    catalog = [
        {
            "id": 5,
            "code": "X",
            "name": "X",
            "is_active": False,
            "children": [],
        }
    ]
    index = walk_catalog(catalog)
    assert 5 in index
    assert index[5].is_active is False


def test_duplicate_ids_keep_first_occurrence():
    """If the catalog has duplicate IDs across branches, first DFS hit wins.

    Matches existing initialize_rag_vectorstore behavior (uses seen_ids set).
    """
    catalog = [
        {
            "id": 7,
            "code": "FIRST",
            "name": "First",
            "is_active": True,
            "children": [],
        },
        {
            "id": 7,
            "code": "SECOND",
            "name": "Second",
            "is_active": True,
            "children": [],
        },
    ]
    index = walk_catalog(catalog)
    assert index[7].code == "FIRST"


def test_missing_optional_fields_use_defaults():
    catalog = [
        {
            "id": 8,
            "code": "MIN",
            "name": "Minimal",
            "children": [],
        }
    ]
    index = walk_catalog(catalog)
    entry = index[8]
    assert entry.is_active is True  # default True when missing
    assert entry.tags == []
    assert entry.updated_xlsx is None
    assert entry.name_uz is None
