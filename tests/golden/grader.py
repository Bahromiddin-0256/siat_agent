"""Typed assertion graders for the SIAT golden eval set.

Each grader returns (passed: bool, detail: str). detail is shown when the
assertion fails and is empty on pass.
"""
from __future__ import annotations

import re
from typing import Any


_SDMX_ID_RE = re.compile(r"SDMX\s*ID\s*[:#]?\s*(\d{1,5})|/reports-filed/(\d{1,5})/", re.IGNORECASE)


def _extract_sdmx_ids(response: str) -> set[int]:
    """Pull SDMX IDs cited in the response — by 'SDMX ID 123' or URL."""
    ids: set[int] = set()
    for m in _SDMX_ID_RE.finditer(response):
        for grp in m.groups():
            if grp:
                try:
                    ids.add(int(grp))
                except ValueError:
                    pass
    return ids


def _detect_language(response: str) -> str:
    """Crude language detection by character class and stopwords.

    Returns 'uz', 'ru', 'en', or 'unknown'. Suffices for our 3-language case.
    """
    text = response.lower()
    cyrillic = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    latin = sum(1 for c in text if "a" <= c <= "z")
    total = cyrillic + latin
    if total == 0:
        return "unknown"
    cyr_ratio = cyrillic / total
    if cyr_ratio > 0.4:
        return "ru"
    # Both Uzbek (Latin) and English use Latin script — disambiguate by tokens.
    uz_markers = (
        " soni ", " aholi", " yil ", " yilda", " mavjud", " ko'rsatkich",
        " bo'yicha", " ma'lumot", "o'zbekiston", "viloyat",
    )
    en_markers = (
        " the ", " population", " indicator", " year ", " for ", " is ", " of ",
        " data ", " available",
    )
    uz_hits = sum(1 for m in uz_markers if m in f" {text} ")
    en_hits = sum(1 for m in en_markers if m in f" {text} ")
    if uz_hits >= en_hits:
        return "uz"
    return "en"


def _count_markdown_table_data_rows(response: str) -> int:
    """Count data rows in any markdown table — first table only."""
    lines = response.splitlines()
    in_table = False
    seen_separator = False
    rows = 0
    for line in lines:
        s = line.strip()
        is_table_line = s.startswith("|") and s.endswith("|") and s.count("|") >= 2
        if not in_table:
            if is_table_line:
                in_table = True
                seen_separator = False
            continue
        if not is_table_line:
            break
        # separator row like | --- | --- |
        if re.match(r"^\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|$", s):
            seen_separator = True
            continue
        if seen_separator:
            rows += 1
    return rows


def _numbers_in(text: str) -> list[float]:
    """Extract all numeric values from text (with ' ' or ',' as thousand seps)."""
    out: list[float] = []
    for m in re.finditer(r"\b(\d{1,3}(?:[\s,]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\b", text):
        s = m.group(1).replace(" ", "").replace(",", "")
        try:
            out.append(float(s))
        except ValueError:
            pass
    return out


def grade(
    assertion: dict[str, Any], response: str, duration_s: float
) -> tuple[bool, str]:
    """Run a single typed assertion. Returns (passed, detail_on_fail)."""
    t = assertion.get("type")

    if t == "language":
        expected = assertion["expected"]
        actual = _detect_language(response)
        return actual == expected, f"expected {expected}, got {actual}"

    if t == "indicator_in":
        wanted = set(assertion["ids"])
        cited = _extract_sdmx_ids(response)
        ok = bool(cited & wanted)
        return ok, f"none of {sorted(wanted)} cited; cited={sorted(cited)}"

    if t == "indicator_not_in":
        banned = set(assertion["ids"])
        cited = _extract_sdmx_ids(response)
        hit = cited & banned
        return not hit, f"banned id(s) cited: {sorted(hit)} — {assertion.get('reason','')}"

    if t == "contains":
        text = assertion["text"]
        case_sensitive = assertion.get("case_sensitive", False)
        if case_sensitive:
            ok = text in response
        else:
            ok = text.lower() in response.lower()
        return ok, f"missing substring: {text!r}"

    if t == "not_contains":
        text = assertion["text"]
        case_sensitive = assertion.get("case_sensitive", False)
        if case_sensitive:
            hit = text in response
        else:
            hit = text.lower() in response.lower()
        return not hit, f"forbidden substring present: {text!r} — {assertion.get('reason','')}"

    if t == "contains_regex":
        pattern = assertion["pattern"]
        ok = re.search(pattern, response) is not None
        return ok, f"regex did not match: {pattern}"

    if t == "says_unavailable":
        hints = assertion.get("lang_hints", [
            "mavjud emas", "ma'lumot yo'q", "e'lon qilinmagan",
            "не доступн", "нет данных",
            "not available", "not yet published",
        ])
        low = response.lower()
        ok = any(h.lower() in low for h in hints)
        return ok, "response did not acknowledge unavailability"

    if t == "table_min_rows":
        n = assertion["n"]
        rows = _count_markdown_table_data_rows(response)
        return rows >= n, f"table has {rows} data rows, expected >= {n}"

    if t == "max_seconds":
        n = assertion["n"]
        return duration_s <= n, f"took {duration_s:.1f}s, max {n}s"

    if t == "no_fabricated_total":
        target = float(assertion["value"])
        tol = float(assertion.get("tolerance", 0))
        nums = _numbers_in(response)
        # Compare both as-is and times-1000 (to catch "ming kishi" off-by-1000)
        candidates = nums + [n * 1000 for n in nums]
        hit = any(abs(n - target) <= tol for n in candidates)
        return not hit, (
            f"fabricated value ~{target} appeared in response — "
            f"{assertion.get('reason','')}"
        )

    return False, f"unknown assertion type: {t}"
