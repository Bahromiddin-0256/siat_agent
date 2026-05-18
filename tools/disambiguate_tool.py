"""Indicator disambiguation tool.

Runs the same hybrid retrieval + rerank pipeline as `search_sdmx_semantic`,
but its job is to flag ambiguity rather than silently picking the top hit.

When the top candidates differ on a meaningful axis the user did NOT pin
(subset, age range, reporting period) or are within a small relative score
margin, the tool returns "AMBIGUOUS:" along with the candidates and a
suggested clarifying question. Otherwise it returns "RESOLVED:" with the
winning indicator.

Why a separate tool: `search_sdmx_semantic` always returns top-k and lets
the LLM choose. For queries like "Toshkentda 2020-yil aholi soni" where
(jami) and (ayollar) variants score within a few percent, the LLM has no
explicit signal that it's guessing. This tool makes that ambiguity loud.
"""
from __future__ import annotations

from typing import Union

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from qdrant_client.models import Fusion, FusionQuery, Prefetch, SparseVector

from core.logger import setup_logger
from tools.embedder import encode_query, rerank_pairs
from tools.qdrant_shared_client import get_shared_client
from tools.query_expander import expand_query
from tools.rag_tool import (
    _COLLECTION,
    _age_range_multiplier,
    _catalog_order_multiplier,
    _catalog_total,
    _freshness_multiplier,
    _indicator_age_range,
    _query_age_range,
    _query_dimension_intent,
    _subset_penalty,
)

logger = setup_logger(__name__)

_DEFAULT_TOP_N = 5
_DEFAULT_MARGIN = 0.05
_RERANK_POOL = 30


class _DisambiguateArgs(BaseModel):
    question: str = Field(..., description="The user's indicator question")
    top_n: Union[int, str] = Field(
        _DEFAULT_TOP_N,
        description="How many top candidates to consider (3-10)",
    )
    margin: Union[float, str] = Field(
        _DEFAULT_MARGIN,
        description="Relative score gap below which the top-2 are flagged ambiguous",
    )


@tool(args_schema=_DisambiguateArgs)
def disambiguate_indicator(
    question: str,
    top_n: int = _DEFAULT_TOP_N,
    margin: float = _DEFAULT_MARGIN,
) -> str:
    """
    Find the SDMX indicator for a question and flag any ambiguity.

    Returns one of:
      - "RESOLVED: id=<id> — <name>" with a confidence note, OR
      - "AMBIGUOUS on axis: <subset|age_range|period|score-tie>" with a
        numbered candidate list and a suggested clarifying question.

    Use this BEFORE `get_sdmx_value` when the user's question does NOT
    name a gender / area / age / scope, or when the search results feel
    too close to confidently pick a winner. Skip it when the question
    already pins the relevant dimensions.
    """
    if get_shared_client() is None:
        return "Error: RAG vector store not initialized."

    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        top_n = _DEFAULT_TOP_N
    try:
        margin = float(margin)
    except (TypeError, ValueError):
        margin = _DEFAULT_MARGIN
    top_n = max(3, min(top_n, 10))
    margin = max(0.01, min(margin, 0.5))

    intent = _query_dimension_intent(question)
    encoded = expand_query(question)
    if not intent:
        encoded = (
            f"{encoded} | jami umumiy total всего общий "
            f"whole population both sexes all areas"
        )
    dense, sparse = encode_query(encoded)

    points = get_shared_client().query_points(
        collection_name=_COLLECTION,
        prefetch=[
            Prefetch(query=dense, using="dense", limit=_RERANK_POOL * 2),
            Prefetch(
                query=SparseVector(
                    indices=list(sparse.keys()),
                    values=list(sparse.values()),
                ),
                using="sparse",
                limit=_RERANK_POOL * 2,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=_RERANK_POOL,
    ).points

    if not points:
        return f"No candidates found for: '{question}'"

    q_age = _query_age_range(question)
    passages = [(p.payload or {}).get("text", "") for p in points]
    base_scores = rerank_pairs(question, passages) or [1.0] * len(points)

    def composite(payload: dict, base: float) -> float:
        p = payload or {}
        return (
            base
            * _subset_penalty(p.get("subset", "") or "", intent)
            * _freshness_multiplier(p.get("updated_xlsx"), p.get("status"))
            * _catalog_order_multiplier(p.get("catalog_index"), _catalog_total)
            * _age_range_multiplier(q_age, _indicator_age_range(p.get("name")))
        )

    scored = sorted(
        [(pt, composite(pt.payload, s)) for pt, s in zip(points, base_scores)],
        key=lambda x: x[1],
        reverse=True,
    )[:top_n]

    top_pt, top_score = scored[0]
    second = scored[1] if len(scored) > 1 else None
    rel_gap = (
        (top_score - second[1]) / top_score
        if second is not None and top_score > 0
        else 1.0
    )

    axis = _differing_axis([pt.payload for pt, _ in scored])
    is_close = second is not None and rel_gap < margin
    ambiguous = is_close or (axis is not None and not _intent_covers(axis, intent))

    if not ambiguous:
        p = top_pt.payload or {}
        return (
            f"RESOLVED: id={p.get('id')} — {p.get('name')}\n"
            f"Confidence: high (gap={rel_gap:.0%}, no unresolved axis)"
        )

    lines: list[str] = [
        f"AMBIGUOUS on axis: {axis or 'score-tie'}",
        f"Top-2 composite score gap: {rel_gap:.1%} (margin={margin:.0%})",
        "",
        "Candidates:",
    ]
    for i, (pt, sc) in enumerate(scored, 1):
        p = pt.payload or {}
        lines.append(
            f"{i}. id={p.get('id')} | score={sc:.3f} | "
            f"subset={p.get('subset') or 'total'} | "
            f"period={p.get('period') or '?'} | "
            f"{p.get('name')}"
        )
    lines.append("")
    lines.append("Suggested clarifying question to user:")
    lines.append(_clarifying_question(axis, [pt.payload for pt, _ in scored]))
    return "\n".join(lines)


def _differing_axis(payloads: list[dict]) -> str | None:
    """Return the first axis on which the top candidates disagree."""
    if len(payloads) < 2:
        return None
    head = payloads[:3]
    if len({(p or {}).get("subset") or "total" for p in head}) > 1:
        return "subset"
    ranges = {_indicator_age_range((p or {}).get("name")) for p in head}
    if len(ranges) > 1 and None not in ranges:
        return "age_range"
    if len({(p or {}).get("period") for p in head if (p or {}).get("period")}) > 1:
        return "period"
    return None


def _intent_covers(axis: str, intent: set[str]) -> bool:
    """True when the user already pinned this axis explicitly."""
    if axis == "subset":
        return bool({"gender", "area"} & intent)
    if axis == "age_range":
        return "age" in intent
    return False


def _clarifying_question(axis: str | None, payloads: list[dict]) -> str:
    if axis == "subset":
        subsets = sorted({(p or {}).get("subset") or "total" for p in payloads[:3]})
        return (
            f"Which population subset do you mean? Candidates differ on: "
            f"{', '.join(subsets)}."
        )
    if axis == "age_range":
        ranges = sorted(
            r
            for r in {_indicator_age_range((p or {}).get("name")) for p in payloads[:3]}
            if r is not None
        )
        labels = [f"{lo}-{hi}" if hi < 200 else f"{lo}+" for lo, hi in ranges]
        return f"Which age range? Candidates: {', '.join(labels)}."
    if axis == "period":
        return "Which reporting period (annual vs. quarterly vs. monthly)?"
    return (
        "Multiple indicators are nearly tied. Could you add a region, year, "
        "or population detail to narrow it down?"
    )