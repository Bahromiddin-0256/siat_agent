"""Tests for build_indicator_text_and_payload — the per-item text+payload builder.

Locks the existing rag_tool format so the refactor stays behaviorally equivalent.
"""
from tools.rag_tool import build_indicator_text_and_payload


def test_full_item_produces_expected_text_and_payload():
    item = {
        "id": 42,
        "code": "POP_TOTAL",
        "name": "Aholi soni",
        "name_uz": "Aholi soni",
        "name_en": "Population",
        "name_ru": "Численность населения",
        "tags": ["demographics", "annual"],
        "period": "year",
        "department": "Demo",
        "status": "active",
        "updated_xlsx": "2026-01-15",
    }
    text, payload = build_indicator_text_and_payload(
        item, path=["Demographics"], catalog_index=7
    )

    assert "Name: Aholi soni" in text
    assert "English: Population" in text
    assert "Russian: Численность населения" in text
    assert "Uzbek: Aholi soni" in text
    assert "Tags: demographics, annual" in text
    assert "Period: year" in text
    assert "Department: Demo" in text

    assert payload["id"] == "42"
    assert payload["code"] == "POP_TOTAL"
    assert payload["name"] == "Aholi soni"
    assert payload["catalog_index"] == 7
    assert payload["updated_xlsx"] == "2026-01-15"
    assert payload["path"] == "Demographics > Aholi soni"


def test_missing_optional_fields_omitted_from_text():
    item = {"id": 1, "code": "X", "name": "X"}
    text, _ = build_indicator_text_and_payload(item, path=[], catalog_index=0)
    assert "Name: X" in text
    assert "Tags:" not in text
    assert "Period:" not in text
    assert "Department:" not in text


def test_subset_detected_and_added_to_text_and_payload():
    item = {
        "id": 99,
        "code": "POP_F",
        "name": "Aholi soni (ayol)",
        "name_uz": "Aholi soni (ayol)",
        "name_en": "Population (female)",
    }
    text, payload = build_indicator_text_and_payload(item, path=[], catalog_index=0)
    assert payload["subset"] == "female"
    assert "Subset:" in text  # subset doc text appended


def test_id_is_stringified():
    """Payload `id` stays a string for backwards compat with existing search code."""
    item = {"id": 12345, "code": "X", "name": "X"}
    _, payload = build_indicator_text_and_payload(item, path=[], catalog_index=0)
    assert payload["id"] == "12345"
