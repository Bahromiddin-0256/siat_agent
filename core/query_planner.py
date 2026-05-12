"""Decompose compound questions into a tool-execution plan.

The ReAct loop already handles linear chains well (search → inspect → value).
Where it degrades is *parallel* sub-questions joined by conjunctions:

  "compare birth rate in Toshkent and Andijon for 2020-2023, and also show
   GDP per capita over the same period"

A naive ReAct tends to attack the first half thoroughly, then short-circuit.
This module runs a tiny planner LLM call *only when the question looks
compound* and returns a plan hint that the agent injects into the HumanMessage.

We DON'T orchestrate multiple agent runs — that turned out to be hard to
stitch back into a single coherent answer. Instead we let the ReAct loop see
the explicit plan and execute against it.
"""
from __future__ import annotations

import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from .llm import base_llm
from .logger import setup_logger

logger = setup_logger(__name__)


# Cheap heuristic gate. We only call the LLM planner when the question has at
# least one of these signals; otherwise we skip and let the normal ReAct loop run.
_COMPOUND_CONJUNCTIONS = (
    " va ",     # uz
    " hamda ",  # uz
    " yoki ",   # uz
    " and also ", " as well as ", " plus ",
    " и также ", " а также ",
)

_PERIOD_RE = re.compile(r"\b20\d{2}(?:-(?:Q[1-4]|M\d{1,2}|\d{2}))?\b")

# Multiple region mentions in the same question. Listing region tokens here
# keeps detection cheap; the planner LLM call decides whether it's *really*
# compound.
_REGION_TOKENS = (
    "toshkent", "andijon", "buxoro", "farg'ona", "farg", "jizzax",
    "xorazm", "namangan", "navoiy", "qashqadaryo", "samarqand",
    "sirdaryo", "surxondaryo", "qoraqalpog",
    "ташкент", "андижан", "бухар", "ферган",
)


def _looks_compound(question: str) -> bool:
    """True if there's any signal that this question has more than one ask.

    False positives here are cheap (one extra LLM call); false negatives mean
    we'd skip planning, so we err on the side of including marginal cases.
    """
    q = question.lower()

    if any(c in q for c in _COMPOUND_CONJUNCTIONS):
        return True

    # Multiple distinct periods (e.g. "2020 va 2023") usually means compare.
    periods = set(_PERIOD_RE.findall(question))
    if len(periods) >= 2:
        return True

    # Multiple region mentions.
    hits = sum(1 for tok in _REGION_TOKENS if tok in q)
    if hits >= 2:
        return True

    # Multiple sentences asking different things.
    sentences = [s for s in re.split(r"[?!]\s*", question.strip()) if s.strip()]
    if len(sentences) >= 2:
        return True

    return False


_PLANNER_PROMPT = """You are a planning assistant for a statistics agent. Given a user
question, decide if it is COMPOUND (asks for two or more substantively different
data slices) and, if so, write a short numbered plan the agent should follow.

Rules:
- A single comparison across regions or years counts as ONE ask, not compound.
  Example: "compare 2020 and 2023 birth rate in Toshkent" → NOT compound.
- "compare X in Toshkent and Andijon, AND ALSO show GDP for same period" → compound.
- "what is X and how does it relate to Y" → compound.
- Plan steps must reference SIAT tools by name when obvious
  (search_sdmx_semantic, inspect_sdmx_data, get_sdmx_value, calculate_yearly_growth,
  rank_rows_by_value, compare_regions, calculate_cagr, calculate_period_total).
- Keep the plan SHORT — max 5 numbered steps, one line each.
- Do NOT solve the question. Do NOT call tools yourself. Only plan.

Output STRICT JSON, no markdown:
{"compound": <bool>, "plan": "<numbered plan as a single string, or empty if not compound>"}
"""


def _llm_plan(question: str) -> Optional[str]:
    """Ask the LLM whether the question is compound; return plan string or None."""
    import json

    try:
        resp = base_llm.invoke([
            SystemMessage(content=_PLANNER_PROMPT),
            HumanMessage(content=f"QUESTION:\n{question}\n\nReturn JSON only."),
        ])
    except Exception as e:
        logger.warning(f"Planner LLM call failed, skipping plan: {e}")
        return None

    raw = getattr(resp, "content", "") or ""
    if not isinstance(raw, str):
        raw = str(raw)

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    if not parsed.get("compound"):
        return None

    plan = str(parsed.get("plan") or "").strip()
    return plan or None


def maybe_plan(question: str) -> Optional[str]:
    """Return a plan string if the question is compound, else None.

    Cheap heuristic first — most questions short-circuit without an LLM call.
    """
    if not _looks_compound(question):
        return None

    plan = _llm_plan(question)
    if plan:
        logger.info(f"Compound question detected; generated plan ({len(plan)} chars)")
    return plan
