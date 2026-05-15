"""Tests for the deterministic language detector."""
from core.lang import detect_language, lock_directive


def test_cyrillic_query_is_russian():
    assert detect_language("Численность населения Узбекистана 2024 год") == "ru"
    assert detect_language("ВВП за 2024 год") == "ru"


def test_uzbek_query_with_apostrophes():
    assert detect_language("O'zbekiston aholisi 2024 yil") == "uz"
    assert detect_language("Aholi soni qancha 2024") == "uz"


def test_english_query():
    assert detect_language("Population of Uzbekistan in 2024") == "en"
    assert detect_language("What is the unemployment rate in 2024") == "en"


def test_uzbek_specific_markers():
    assert detect_language("Ayollar soni 2024") == "uz"
    assert detect_language("Qishloq aholisi") == "uz"


def test_short_or_ambiguous_defaults_to_uz():
    # Pure number / mixed strings → default to Uzbek (catalog's native lang)
    assert detect_language("2024") == "uz"
    assert detect_language("") == "uz"


def test_mixed_uz_en_picks_majority_marker():
    # "Aholi" is Uzbek-only — should dominate even if "2024" looks neutral
    assert detect_language("Aholi 2024") == "uz"


def test_lock_directive_mentions_language():
    assert "ENGLISH" in lock_directive("en").upper()
    assert "RUSSIAN" in lock_directive("ru").upper()
    assert "UZBEK" in lock_directive("uz").upper()


def test_lock_directive_includes_table_headers():
    assert "Период" in lock_directive("ru")
    assert "Period" in lock_directive("en")
    assert "Davr" in lock_directive("uz")
