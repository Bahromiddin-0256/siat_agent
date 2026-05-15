"""Tests for age-range parsing and matching used during RAG rerank."""
from tools.rag_tool import (
    _indicator_age_range,
    _query_age_range,
    _age_range_multiplier,
)


# -- query parsing --------------------------------------------------------

def test_query_range_dash_form():
    assert _query_age_range("0-14 yosh oraligida bolalar soni") == (0, 14)


def test_query_range_with_yoshli():
    assert _query_age_range("8-15 yoshli bolalar") == (8, 15)


def test_query_range_yoshdan_oshgan():
    """X yoshdan oshgan / katta → open-ended upper."""
    assert _query_age_range("60 yoshdan oshgan aholi") == (60, 200)


def test_query_range_va_undan_katta():
    assert _query_age_range("65 yosh va undan katta") == (65, 200)


def test_query_no_age_range():
    assert _query_age_range("o'zbekiston aholisi 2024") is None
    assert _query_age_range("yalpi ichki mahsulot") is None


# -- indicator name parsing ----------------------------------------------

def test_indicator_range_dash():
    assert _indicator_age_range("8-15 yoshli doimiy aholi soni") == (8, 15)
    assert _indicator_age_range("0-2 yoshli doimiy aholi soni (ayollar)") == (0, 2)


def test_indicator_open_ended():
    assert _indicator_age_range("65 yosh va undan katta yoshdagi doimiy aholi soni") == (
        65,
        200,
    )


def test_indicator_no_age_range():
    assert _indicator_age_range("Doimiy aholi soni (jami)") is None


# -- multiplier ------------------------------------------------------------

def test_multiplier_exact_match_bonus():
    assert _age_range_multiplier((8, 15), (8, 15)) > 1.0


def test_multiplier_no_overlap_heavy_penalty():
    # query 0-14, indicator 16-17 — no overlap
    assert _age_range_multiplier((0, 14), (16, 17)) <= 0.4


def test_multiplier_partial_overlap_between():
    # query 0-14, indicator 8-15 — overlap is 8..14 (7), requested width 15
    score = _age_range_multiplier((0, 14), (8, 15))
    assert 0.4 < score < 1.0


def test_multiplier_unspecified_query_is_neutral():
    """Query without age range → don't penalize any indicator."""
    assert _age_range_multiplier(None, (8, 15)) == 1.0


def test_multiplier_unspecified_indicator_with_query():
    """Query with age range, indicator without (e.g. 'total population')
    → heavy penalty. Total/aggregate indicators must NOT be presented as
    answers to age-bracketed questions."""
    score = _age_range_multiplier((0, 14), None)
    assert score <= 0.55


def test_total_indicator_not_preferred_over_partial_overlap():
    """When user asks 0-14, neither '8-15 yoshli' nor 'total population'
    is right — they should be similarly weighted so the cross-encoder /
    other signals decide rather than 'total' winning by default."""
    overlap = _age_range_multiplier((0, 14), (8, 15))
    no_range = _age_range_multiplier((0, 14), None)
    assert no_range <= overlap  # total must not outrank an actual age bracket
