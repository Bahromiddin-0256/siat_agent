"""Tests for the top-level admin filter used in multi-region rollups."""
from tools.sdmx_data_retrieval_tool import _is_region_level


def test_republic_is_region_level():
    assert _is_region_level("O‘zbekiston Respublikasi") is True
    assert _is_region_level("Qoraqalpog‘iston Respublikasi") is True


def test_viloyats_are_region_level():
    for name in (
        "Andijon viloyati",
        "Buxoro viloyati",
        "Toshkent viloyati",
        "Farg‘ona viloyati",
        "Xorazm viloyati",
    ):
        assert _is_region_level(name) is True, name


def test_capital_cities_are_region_level():
    assert _is_region_level("Toshkent shahri") is True
    assert _is_region_level("Nukus shahri") is True


def test_districts_are_filtered():
    for name in (
        "Amudaryo tumani",
        "Beruniy tumani",
        "Chimboy tumani",
        "Xo‘jayli tumani",
    ):
        assert _is_region_level(name) is False, name


def test_empty_or_none_filtered():
    assert _is_region_level(None) is False
    assert _is_region_level("") is False


def test_settlements_filtered():
    assert _is_region_level("Yangiyer shaharchasi") is False
