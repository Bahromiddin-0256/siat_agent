"""Deterministic language detection for the user's question.

Used both at agent entry (to lock the response language) and by the critic
(to flag mismatches). Three target languages: uz / ru / en.
"""
from __future__ import annotations

_UZ_MARKERS = (
    " soni ", " aholi", " yil ", " yilda", " mavjud", " ko'rsatkich",
    " bo'yicha", " ma'lumot", "o'zbekiston", "viloyat", " yosh",
    " nechta", " qancha", " jami", " ayollar", " erkaklar",
    " shahar", " qishloq", "darajasi", "indeksi",
)
_EN_MARKERS = (
    " the ", " population", " indicator", " year ", " for ", " is ",
    " of ", " data ", " available", " uzbekistan", " how many",
    " what is", " what's", " how much", " in 20",
)


def detect_language(text: str) -> str:
    """Return one of: 'uz', 'ru', 'en'.

    Falls back to 'uz' (the catalog's native language) when signal is weak.
    """
    s = text.lower()
    cyrillic = sum(1 for c in s if "Ѐ" <= c <= "ӿ")
    latin = sum(1 for c in s if "a" <= c <= "z")
    total = cyrillic + latin
    if total == 0:
        return "uz"
    if cyrillic / total > 0.3:
        return "ru"
    padded = f" {s} "
    uz_hits = sum(1 for m in _UZ_MARKERS if m in padded)
    en_hits = sum(1 for m in _EN_MARKERS if m in padded)
    if en_hits > uz_hits:
        return "en"
    # Latin-script with no strong markers either way → default to Uzbek,
    # since the catalog is Uzbek-native and most queries on the platform are
    # in Uzbek.
    return "uz"


_LANG_NAME = {"uz": "Uzbek", "ru": "Russian", "en": "English"}
_LANG_TABLE_HEADERS = {
    "uz": "Davr / Qiymat / O'sish %",
    "ru": "Период / Значение / Рост %",
    "en": "Period / Value / Growth %",
}


def lock_directive(lang: str) -> str:
    """A short, visible directive to prepend so the LLM can't drift."""
    name = _LANG_NAME.get(lang, "Uzbek")
    headers = _LANG_TABLE_HEADERS.get(lang, "Davr / Qiymat / O'sish %")
    return (
        f"### LANGUAGE LOCK — {name.upper()} ONLY\n"
        f"The user wrote in {name}. Reply in {name} for EVERY word — narrative, "
        f"table headers, bullet labels, units, conclusions. Do not let retrieved "
        f"Uzbek catalog text drag your reply into Uzbek. "
        f"Use these table headers: {headers}.\n"
    )
