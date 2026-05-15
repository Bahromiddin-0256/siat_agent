"""Self-evaluation pass that runs after the ReAct loop drafts an answer.

The Agentic RAG pattern (right column of the comparison diagram) shows an
explicit *self-evaluation* step before the agent commits to its answer. This
module implements that step for SIAT:

- Re-read the user's question + the draft answer.
- Check structural requirements (SDMX ID present, unit present, SIAT link,
  language match, no obvious hedging) cheaply via regex first — most failures
  are caught here without an LLM call.
- If structure is fine but content might be off (wrong region, wrong year,
  unit looks suspicious), ask the LLM with a tight JSON-only prompt.

The critic returns a `CritiqueResult` with a verdict and a fix hint. Callers
decide whether to retry with that hint or pass the answer through. The hint is
designed to be appendable to the message history as a HumanMessage — "your
previous answer had X; please redo Y" — so a retry costs one extra ReAct loop
at most.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from .llm import base_llm
from .logger import setup_logger
from .answer_schema import extract_schema, validate_against_question

logger = setup_logger(__name__)

_SDMX_ID_RE = re.compile(r"SDMX\s*ID\s*\d+", re.IGNORECASE)
_SIAT_LINK_RE = re.compile(r"https?://siat\.stat\.uz/")
_NO_RESPONSE_MARKERS = ("no response generated", "error processing", "i don't know")

# Year-like tokens (2010..2099, optionally with -Q1..Q4 or -MM).
_PERIOD_RE = re.compile(r"\b20\d{2}(?:-(?:Q[1-4]|\d{2}|M\d{1,2}))?\b")

# Relative time spans: "10 yillik", "so'nggi 5 yil", "last 5 years", "за 10 лет".
# Used by `_is_data_question` so growth/trend questions without explicit 20XX
# years still get reviewed by the critic.
_RELATIVE_PERIOD_RE = re.compile(
    r"\b\d+\s*-?\s*(?:yil(?:lik|larda|larda?gi)?|year[s]?|год[аов]?|лет)\b",
    re.IGNORECASE,
)


@dataclass
class CritiqueResult:
    ok: bool
    issues: list[str]
    fix_hint: str  # one short paragraph; empty when ok=True
    severity: str  # "low", "medium", "high"


def _is_data_question(question: str) -> bool:
    """True if the question seems to ask for a specific value/number, growth,
    trend, or any time-series shaped indicator query.

    Heuristic: contains an explicit year (2023), a relative span ("10 yillik",
    "so'nggi 5 yil", "last 5 years"), or one of the value/growth trigger
    words. Lookups like "what is SDMX ID 42 about?" don't need the same
    structural checks (no period to verify, etc.).
    """
    if _PERIOD_RE.search(question) or _RELATIVE_PERIOD_RE.search(question):
        return True
    triggers = (
        # Value lookups
        "qancha", "nechta", "necha", "qaysi yili",
        "how many", "how much", "what is the value", "value of",
        "сколько", "какое значение", "значение",
        # Growth / trend / rate lookups — these also produce numeric answers
        # the critic should validate (wrong indicator variant, wrong region).
        "o'sish", "o`sish", "osish", "sur'at", "sur`at", "surat",
        "dinamika", "tendensiya", "evolyutsiya", "ko'paygan", "kamaygan",
        "growth", "rate", "trend", "change", "increase", "decrease",
        "рост", "темп", "динамика", "тенденция", "изменение",
    )
    q_lower = question.lower()
    return any(t in q_lower for t in triggers)


def _structural_check(question: str, answer: str) -> list[str]:
    """Cheap regex-based checks. Returns a list of issue strings (empty = clean)."""
    issues: list[str] = []

    if not answer or len(answer.strip()) < 10:
        issues.append("answer is empty or too short")
        return issues

    lower = answer.lower()
    if any(marker in lower for marker in _NO_RESPONSE_MARKERS):
        issues.append("answer contains an error/placeholder string")
        return issues

    # Deterministic language check. The LLM critic also has a language rule
    # but has been observed to pass long Uzbek responses to Russian questions
    # because most of the response IS valid catalog content. Detect upfront.
    try:
        from core.lang import detect_language
        q_lang = detect_language(question)
        a_lang_body = answer.split("\n---", 1)[0]  # drop the SDMX footer
        # Strip URLs which add Latin chars and bias against Cyrillic detection.
        import re as _re
        a_lang_body = _re.sub(r"https?://\S+", "", a_lang_body)
        a_lang = detect_language(a_lang_body)
        if q_lang != "uz" and a_lang != q_lang:
            issues.append(
                f"language mismatch — user asked in {q_lang}, response is in "
                f"{a_lang}. Rewrite the narrative, table headers, and "
                f"conclusion in {q_lang}; keep indicator names verbatim from "
                f"tools and SIAT URLs unchanged."
            )
    except Exception:
        # Language check failure must not break the critic; log and move on.
        logger.debug("language check skipped", exc_info=True)

    # Only enforce SDMX ID / SIAT link / period match on questions that actually
    # asked for data. General "what data exists?" answers don't need an ID.
    if _is_data_question(question):
        if not _SDMX_ID_RE.search(answer):
            issues.append("missing SDMX ID — every data answer must cite the indicator ID")
        if not _SIAT_LINK_RE.search(answer):
            issues.append("missing SIAT verification link (https://siat.stat.uz/reports-filed/<id>/table-data)")

        question_periods = set(_PERIOD_RE.findall(question))
        answer_periods = set(_PERIOD_RE.findall(answer))
        # Only flag period mismatch when the user named at least one period and
        # NONE of them appear in the answer — partial overlap is fine (e.g. user
        # asked for 2020–2023, answer shows all four years).
        if question_periods and question_periods.isdisjoint(answer_periods):
            issues.append(
                f"question mentions period(s) {sorted(question_periods)} but answer "
                f"references {sorted(answer_periods) or 'none'}"
            )

    return issues


_LLM_CRITIC_PROMPT = """You are a strict QA reviewer for a statistical-data assistant.
You receive the user's question and the assistant's draft answer. Your job is
to detect *substantive* errors that would mislead the user.

Check ONLY these things:
1. Does the draft answer the question the user actually asked? (Not a related
   indicator, not a different region, not a different year.)
2. **Indicator variant match.** If the cited indicator name carries a
   demographic or geographic suffix — `(ayol)`, `(erkak)`, `(qishloq)`,
   `(shahar)`, `(female)`, `(male)`, `(urban)`, `(rural)`, `(женщины)`,
   `(мужчины)`, `(город)`, `(село)` — the user's question MUST explicitly
   request that subset. Examples of FAIL:
     - User asked "respublika aholisi" (whole-country population), answer
       cited "Doimiy aholi soni (ayol)" — flag it; the correct variant is
       "(jami)".
     - User asked "Uzbekistan population growth", answer cited
       "Permanent population (urban)" — flag it.
   If the question is neutral on gender/urban-rural and the answer uses a
   subset variant, that is a wrong-indicator error, not a stylistic one.
3. Is the unit consistent with the indicator? (kishi for people, mlrd. so'm
   for currency totals, % for shares, etc. — flag if missing or obviously wrong.)
4. Is the response in the SAME LANGUAGE as the user's question?
   (uz → uz, ru → ru, en → en. Mixed-language responses are a fail.)
5. Are there internal contradictions (a table row that doesn't match the
   narrative number, a "growth" labelled positive but with a decreasing value)?

Do NOT flag style, formatting, verbosity, or missing IDs/links — those are
checked elsewhere. Do NOT flag the answer for being too short if it answers
the question.

Output STRICT JSON, no markdown, no prose:
{{"ok": <bool>, "issues": [<short strings>], "fix_hint": "<one paragraph telling the assistant exactly what to redo, or empty>"}}
"""


def _llm_critic(question: str, answer: str) -> CritiqueResult:
    """Ask the base LLM whether the answer is substantively correct."""
    try:
        resp = base_llm.invoke([
            SystemMessage(content=_LLM_CRITIC_PROMPT),
            HumanMessage(
                content=(
                    f"USER QUESTION:\n{question}\n\n"
                    f"DRAFT ANSWER:\n{answer}\n\n"
                    "Return JSON only."
                )
            ),
        ])
    except Exception as e:
        logger.warning(f"LLM critic call failed, treating as pass: {e}")
        return CritiqueResult(ok=True, issues=[], fix_hint="", severity="low")

    raw = getattr(resp, "content", "") or ""
    if not isinstance(raw, str):
        raw = str(raw)

    # Models sometimes wrap JSON in ```json fences — strip them.
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        logger.warning(f"Critic returned non-JSON, treating as pass: {raw[:200]}")
        return CritiqueResult(ok=True, issues=[], fix_hint="", severity="low")

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.warning(f"Critic JSON parse failed, treating as pass: {e}")
        return CritiqueResult(ok=True, issues=[], fix_hint="", severity="low")

    ok = bool(parsed.get("ok", True))
    issues = parsed.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    fix_hint = str(parsed.get("fix_hint") or "")

    # LLM-flagged content issues are "high" by default — the regex pass only
    # catches structural defects, so anything reaching here means the model
    # found a substantive problem.
    severity = "high" if not ok else "low"
    return CritiqueResult(ok=ok, issues=[str(i) for i in issues], fix_hint=fix_hint, severity=severity)


def critique(question: str, answer: str) -> CritiqueResult:
    """Full critique: regex + schema pass first, LLM pass only when needed.

    Strategy:
    - Structural (regex) check catches missing IDs / links / period coverage.
    - Schema-level check (parsed via AnswerSchema) catches the same family of
      issues on typed fields — robust when the answer's formatting drifts.
    - If either pass fails → return "medium" failure with a fix hint.
    - If both pass and the question is a data question → run the LLM critic for
      substantive review (wrong region, wrong unit, language mismatch, …).
    - Non-data questions skip the LLM critic — too expensive for low-risk answers.
    """
    issues: list[str] = []
    issues.extend(_structural_check(question, answer))

    schema = extract_schema(answer)
    issues.extend(validate_against_question(question, schema))

    # De-dupe (the regex and schema passes flag overlapping things in many cases).
    issues = list(dict.fromkeys(issues))

    if issues:
        return CritiqueResult(
            ok=False,
            issues=issues,
            fix_hint=(
                "Reformat the answer to include: the SDMX ID you used, its unit, "
                "the period(s) the user asked about, and the SIAT verification link "
                "(https://siat.stat.uz/reports-filed/<id>/table-data). Keep the same language as the user."
            ),
            severity="medium",
        )

    # Low confidence from the schema extractor is also a signal — but only worth
    # flagging if this was a data question (low confidence on a methodology
    # lookup is fine, since those don't have IDs/units/periods).
    if _is_data_question(question) and schema.confidence < 0.4:
        return CritiqueResult(
            ok=False,
            issues=[f"answer schema confidence is low ({schema.confidence:.2f}) — missing concrete fields"],
            fix_hint="Add the SDMX ID, the unit, and the SIAT verification link explicitly.",
            severity="medium",
        )

    if _is_data_question(question):
        return _llm_critic(question, answer)

    return CritiqueResult(ok=True, issues=[], fix_hint="", severity="low")


def build_retry_message(critique_result: CritiqueResult) -> HumanMessage:
    """Build a HumanMessage that prompts the agent to fix the flagged issues.

    Phrased as if from the user so the agent treats it as a follow-up turn —
    works with the existing checkpointer/state machine without needing a new
    node in the graph.
    """
    issues_block = "\n".join(f"- {i}" for i in critique_result.issues) or "- (unspecified)"
    return HumanMessage(
        content=(
            "Your previous answer needs a correction. Issues found:\n"
            f"{issues_block}\n\n"
            f"Fix: {critique_result.fix_hint}\n\n"
            "Redo the answer addressing these issues. Use the same language as my original question. "
            "Do NOT add new disclaimers or apologies — just give the corrected answer."
        )
    )
