"""Retrieve relevant few-shot examples for the system prompt at runtime.

The static system prompt in `agent.py` carries 4 hand-picked examples. Useful
when the user asks one of those exact patterns, dead weight otherwise. This
module keeps a larger bank of curated examples and injects the top-2 *most
similar to the current question* — so a question about CAGR pulls in the CAGR
example, a question about quarterly ranking pulls in the ranking example.

Retrieval uses BGE-M3 (already loaded) on the example questions. The bank
encodes once on first use and stays in memory; this is a ~20-item bank so we
do a simple in-process cosine search rather than spinning up a third Qdrant
collection.
"""
from __future__ import annotations

import math
import threading
from typing import Optional

from .logger import setup_logger

logger = setup_logger(__name__)


# Curated examples. Each entry shows: the kind of question (with its language
# embedded), the tool sequence the agent should follow, and the *shape* of a
# good answer. Keep these short — they're prepended to the system prompt and
# eat context budget.
_EXAMPLES: list[dict] = [
    {
        "question": "2013-yil Andijon viloyatida nechta bola tug'ilgan?",
        "language": "uz",
        "plan": (
            "search_sdmx_semantic(\"tug'ilganlar soni\") → pick the \"jami\" variant\n"
            "inspect_sdmx_data(<id>) → confirm 'Andijon viloyati' row + '2013' period\n"
            "get_sdmx_value(<id>, '2013', 'Andijon viloyati')"
        ),
        "answer_shape": "Andijon viloyatida 2013-yil jami 64 239 ta bola tug'ilgan.\n\n---\nFoydalanilgan ko'rsatkichlar:\n- SDMX ID 223: Tug'ilganlar soni — https://siat.stat.uz/reports-filed/223/table-data",
    },
    {
        "question": "Toshkent shahar aholisining 2020–2023 yillardagi o'sish sur'ati",
        "language": "uz",
        "plan": (
            "search_sdmx_semantic(\"Toshkent shahri doimiy aholi soni\")\n"
            "inspect_sdmx_data(<id>) → see exact label 'Toshkent shahri'\n"
            "calculate_yearly_growth(<id>, start_year='2020', end_year='2023', region='Toshkent shahri')"
        ),
        "answer_shape": "O'sish jadvali (yillik %) + jami davr o'sishi + reference list with SIAT link.",
    },
    {
        "question": "2025-Q3 da o'lim sabablari ichida eng yuqori va eng past kategoriyalar farqi necha barobar?",
        "language": "uz",
        "plan": (
            "search_sdmx_semantic(\"vafot etganlarning sabablari\")\n"
            "inspect_sdmx_data(<id>) → confirm 7 categories + 2025-Q3 period\n"
            "rank_rows_by_value(<id>, '2025-Q3')  ← NEVER eyeball the list, always use this tool"
        ),
        "answer_shape": "Max kategoriya / min kategoriya / nisbat (X barobar) — quoted directly from rank_rows_by_value output + reference list.",
    },
    {
        "question": "SDMX ID 224 nima haqida?",
        "language": "uz",
        "plan": "get_sdmx_metadata(224)",
        "answer_shape": "Indicator name, unit, period, department + reference list with SIAT link.",
    },
    {
        "question": "Какой ВВП Узбекистана в 2022 году?",
        "language": "ru",
        "plan": (
            "search_sdmx_semantic(\"ВВП Узбекистана\") → выбрать вариант 'jami'\n"
            "inspect_sdmx_data(<id>) → проверить наличие '2022'\n"
            "get_sdmx_value(<id>, '2022')"
        ),
        "answer_shape": "ВВП в 2022 году составил X млрд. сум. + reference list (in Russian: 'Использованные показатели').",
    },
    {
        "question": "Compare birth rates between Tashkent city and Andijan region for 2023",
        "language": "en",
        "plan": (
            "search_sdmx_semantic(\"birth rate\") → pick 'jami'\n"
            "inspect_sdmx_data(<id>) → confirm both rows + 2023\n"
            "compare_regions(<id>, '2023', ['Toshkent shahri', 'Andijon viloyati'])"
        ),
        "answer_shape": "Side-by-side comparison + difference + reference list (in English: 'Sources used').",
    },
    {
        "question": "2015-2023 yillarda Toshkent shahar aholisining yillik o'rtacha o'sish sur'ati (CAGR)",
        "language": "uz",
        "plan": (
            "search_sdmx_semantic(\"Toshkent shahri doimiy aholi soni\")\n"
            "calculate_cagr(<id>, start_year='2015', end_year='2023', region='Toshkent shahri')"
        ),
        "answer_shape": "CAGR foizi + yillar oralig'i + boshlang'ich/oxirgi qiymat + reference list.",
    },
    {
        "question": "Qaysi ko'rsatkichlar uchun Iqtisodiy taraqqiyot bo'limi mas'ul?",
        "language": "uz",
        "plan": "find_indicators_by_person('Iqtisodiy taraqqiyot bo'limi')  ← NEVER guess responsibility from titles or news",
        "answer_shape": "Ro'yxat: SDMX ID + nomi har bir mas'ul ko'rsatkich uchun + reference list.",
    },
    {
        "question": "Qaysi ko'rsatkichlar SOATO klassifikatorini ishlatadi?",
        "language": "uz",
        "plan": "search_sdmx_metadata(\"SOATO classifier\")",
        "answer_shape": "Topilgan ID'lar ro'yxati + qisqa izoh + reference list.",
    },
    {
        "question": "2020-2023 yillarda Uzbekistan bo'yicha jami GDP",
        "language": "uz",
        "plan": (
            "search_sdmx_semantic(\"YaIM jami\")\n"
            "calculate_period_total(<id>, start_year='2020', end_year='2023')"
        ),
        "answer_shape": "Jami summa + har yil bo'yicha qiymat + reference list.",
    },
]


_lock = threading.Lock()
_embeddings: Optional[list[list[float]]] = None
_embedding_failed = False


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors. Returns 0 on zero norm."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _build_bank_embeddings() -> Optional[list[list[float]]]:
    """Encode all example questions once. Falls back to None on failure so
    callers can degrade gracefully (skip few-shot, keep the static prompt)."""
    global _embeddings, _embedding_failed
    if _embeddings is not None or _embedding_failed:
        return _embeddings

    with _lock:
        if _embeddings is not None or _embedding_failed:
            return _embeddings
        try:
            from tools.embedder import encode_dense_sparse
            texts = [ex["question"] for ex in _EXAMPLES]
            dense, _ = encode_dense_sparse(texts)
            _embeddings = dense
            logger.info(f"Few-shot example bank encoded ({len(_EXAMPLES)} examples)")
        except Exception as e:
            logger.warning(f"Failed to encode few-shot bank, disabling few-shot: {e}")
            _embedding_failed = True
            return None
    return _embeddings


def retrieve_examples(question: str, top_k: int = 2, min_score: float = 0.35) -> list[dict]:
    """Return up to `top_k` examples most similar to `question`.

    Filters out examples with score < `min_score` so we don't inject irrelevant
    examples for off-distribution questions (which would mislead more than help).
    """
    bank = _build_bank_embeddings()
    if not bank:
        return []

    try:
        from tools.embedder import encode_query
        q_dense, _ = encode_query(question)
    except Exception as e:
        logger.warning(f"Few-shot query encoding failed: {e}")
        return []

    scored = [
        (i, _cosine(q_dense, bank[i])) for i in range(len(_EXAMPLES))
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    picked = []
    for i, score in scored[:top_k]:
        if score < min_score:
            continue
        picked.append({**_EXAMPLES[i], "_score": round(score, 3)})
    return picked


def format_for_prompt(examples: list[dict]) -> str:
    """Render examples as a Markdown block to append to the system prompt.

    Empty input → empty string (so callers can unconditionally concatenate).
    """
    if not examples:
        return ""
    parts = ["\n## Retrieved examples (most similar to the current question)\n"]
    for ex in examples:
        parts.append(f"**Q ({ex.get('language', '??')}, sim={ex.get('_score', '?')}):** {ex['question']}")
        parts.append(f"**Plan:**\n{ex['plan']}")
        parts.append(f"**Answer shape:** {ex['answer_shape']}\n")
    return "\n".join(parts)
