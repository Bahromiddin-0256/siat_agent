"""
SDMX Agent using LangGraph.

This module implements a ReAct agent that can search for SDMX IDs
based on user questions using LangGraph's prebuilt agent with Ollama.
"""
from typing import Annotated, Any, TypedDict
from datetime import datetime
import re
import json


def _extract_response_metadata(final_text: str, tools_used: list[str]) -> dict:
    """Pull lightweight structured fields out of the final markdown response.

    Wraps `answer_schema.extract_schema` and returns a dict-shaped view that the
    frontend already consumes. Empty fields are omitted so the over-the-wire
    payload stays small for short answers.
    """
    from .answer_schema import extract_schema  # local import to avoid cycle at import time

    schema = extract_schema(final_text, tools_used)
    metadata: dict = {}
    if schema.sdmx_ids:
        metadata["sdmx_ids"] = schema.sdmx_ids
    if schema.siat_links:
        metadata["siat_links"] = schema.siat_links
    elif schema.sdmx_ids:
        # Synthesize canonical links if the answer cited IDs but didn't include URLs
        metadata["siat_links"] = [
            f"https://siat.stat.uz/reports-filed/{i}/table-data" for i in schema.sdmx_ids
        ]
    if schema.periods:
        metadata["periods"] = schema.periods[:8]
    if schema.regions:
        metadata["regions"] = schema.regions
    if schema.units:
        metadata["units"] = schema.units
    if schema.indicator_names:
        metadata["indicator_names"] = schema.indicator_names
    metadata["confidence"] = schema.confidence
    if schema.tools_used:
        metadata["tools_used"] = schema.tools_used
    return metadata

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain.agents import create_agent
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from .llm import base_llm, _sanitize_tool_call_args
from .logger import setup_logger
from .telemetry import RunTelemetry
from . import answer_cache
from .critic import critique, build_retry_message
from .few_shot import retrieve_examples, format_for_prompt
from tools.chart_utils import pop_charts

logger = setup_logger(__name__)
from tools import (
    get_sdmx_id,
    get_sdmx_by_code,
    list_sdmx_categories,
    search_sdmx_semantic,
    search_sdmx_with_score,
    search_sdmx_metadata,
    get_sdmx_value,
    get_sdmx_metadata,
    inspect_sdmx_data,
    rank_rows_by_value,
    calculate_yearly_growth,
    forecast_value,
    calculate_statistics,
    calculate_cagr,
    compare_regions,
    # rank_regions is deprecated — superseded by rank_rows_by_value, which works
    # for any dataset (regions OR categories) and any period granularity.
    calculate_percentage_share,
    compare_years,
    calculate_period_total,
    calculate_moving_average,
    count_reports_for_category,
    count_reports_by_id,
    find_indicators_by_person,
    random_indicators,
)


class AgentState(TypedDict):
    """State for the SDMX agent."""
    messages: Annotated[list[BaseMessage], add_messages]


def parse_xml_function_call(content: str) -> tuple[str | None, dict | None]:
    """
    Parse XML-style function calls from model output.

    Example: <function=search_sdmx_metadata{"question": "..."}></function>

    Returns:
        Tuple of (function_name, arguments) or (None, None) if not found
    """
    # Pattern to match: <function=NAME{JSON}></function>
    pattern = r'<function=(\w+)(\{.*?\})></function>'
    match = re.search(pattern, content, re.DOTALL)

    if match:
        function_name = match.group(1)
        json_str = match.group(2)

        try:
            arguments = json.loads(json_str)
            logger.info(f"Detected XML function call: {function_name}")
            logger.debug(f"  Args: {arguments}")
            return function_name, arguments
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON arguments: {e}")
            logger.warning(f"  Raw: {json_str}")
            return None, None

    return None, None


def execute_tool_from_xml(content: str, tools_map: dict) -> str | None:
    """
    Extract and execute tool from XML-style function call.

    Args:
        content: Message content containing XML function call
        tools_map: Dictionary mapping tool names to tool functions

    Returns:
        Tool execution result or None if tool not found/failed
    """
    function_name, arguments = parse_xml_function_call(content)

    if not function_name:
        return None

    # Find the tool
    tool = tools_map.get(function_name)
    if not tool:
        logger.warning(f"Tool '{function_name}' not found in tools_map")
        return None

    try:
        logger.info(f"Executing tool fallback: {function_name}")
        result = tool.run(arguments) if arguments else tool.run()
        logger.info(f"Tool execution successful: {len(str(result))} chars")
        return result
    except Exception as e:
        logger.error(f"Tool execution failed: {e}", exc_info=True)
        return f"Error executing tool: {str(e)}"


def create_sdmx_agent(
) -> tuple[Any, str, dict]:
    """
    Create an SDMX agent using LangGraph's prebuilt ReAct agent with Ollama.

    Args:

    Returns:
        A tuple of (compiled LangGraph agent, system prompt, tools_map)
    """
    # Get configuration from environment or use defaults


    # Define the tools
    tools = [
        # Search and discovery tools
        search_sdmx_semantic,  # RAG-based semantic search (primary)
        search_sdmx_with_score,  # RAG search with relevance scores
        search_sdmx_metadata,  # Metadata search (methodologies, classifiers, legal refs)
        get_sdmx_id,  # Keyword-based search (fallback)
        get_sdmx_by_code,  # Get by specific code
        list_sdmx_categories,  # Browse categories
        count_reports_for_category,  # Count reports under a category
        count_reports_by_id,  # Count reports by node ID
        find_indicators_by_person,  # Lookup by responsible person / department metadata
        random_indicators,  # Sample N random indicators when user asks for "random statistika"

        # Data extraction tools
        inspect_sdmx_data,  # Inspect dataset structure (rows + periods) before querying
        get_sdmx_value,  # Extract actual data values
        get_sdmx_metadata,  # Get indicator metadata
        rank_rows_by_value,  # Sorted ranking — use for max/min/top/bottom queries
        forecast_value,  # CAGR-based projection for explicit "future year" questions

        # Time series analysis tools
        calculate_yearly_growth,  # Calculate year-over-year growth rates
        calculate_statistics,  # Descriptive statistics (mean, median, min, max, std dev)
        calculate_cagr,  # Compound Annual Growth Rate
        calculate_period_total,  # Total sum over period
        calculate_moving_average,  # Moving average for smoothed trends

        # Regional comparison tools
        compare_regions,  # Compare multiple regions for a year
        # rank_regions removed — rank_rows_by_value is more general and applies
        # to any dataset (regions or categories) and any period granularity.
        calculate_percentage_share,  # Regional percentage distribution

        # Comparison tools
        compare_years,  # Compare two specific years
    ]

    # System prompt for the agent
    system_prompt = """You are a statistical data assistant for Uzbekistan's statistics agency (SIAT).
You answer questions in the user's language (Uzbek, Russian, or English) about statistical
indicators by selecting the right tool, executing it, and explaining the result.

## Core rules
0. **LANGUAGE MATCHING (highest priority).** Detect the language of the user's
   question and reply in **THAT EXACT LANGUAGE for the entire response** —
   narrative, table headers, bullet labels, units, conclusions, everything.
   Do NOT mix languages within a response. The system prompt being in English
   is irrelevant — what matters is what the user wrote.
   - User wrote Uzbek → reply 100% Uzbek (table headers like "Davr", "Qiymat", "O'sish %").
   - User wrote Russian → reply 100% Russian (headers like "Период", "Значение", "Рост %").
   - User wrote English → reply 100% English.
   - If the user explicitly asks for a translation, output language follows
     the *requested* target, not the input.
   The only fixed-language strings allowed are: SDMX IDs, indicator names
   verbatim from tools, units returned by tools, and SIAT URLs.
1. **Always respond in natural language after a tool runs.** Never end on a raw tool call —
   summarize and format the result for the user.
2. **State which indicator you used.** Include the exact name and SDMX ID in the response.
3. **Always include units** returned by the tool (kishi, mlrd. so'm, mln so'm, etc.).
4. **Prefer "jami" (total)** when several variants exist (e.g. "jami" vs "qiz bolalar" /
   "o'g'il bolalar" / "shahar" / "qishloq"). If still ambiguous, ask the user.
5. **End every data response with a reference list, including a direct SIAT link:**
   ```
   ---
   Foydalanilgan ko'rsatkichlar:
   - SDMX ID <id>: <Indicator Name> — https://siat.stat.uz/reports-filed/<id>/table-data
   ```
   The link lets users verify the number on the official site. Always include it.
6. For general "what data exists?" questions, do not call tools — point to
   https://siat.stat.uz and optionally suggest `list_sdmx_categories`.
7. **NEVER eyeball a list of values to pick max/min/top/bottom.** If the user
   asks for "eng yuqori", "eng past", "max", "min", "ranking", "qaysi ... eng ko'p",
   "which ... is highest/lowest", use `rank_rows_by_value(sdmx_id, period)` —
   it returns the values pre-sorted with explicit max, min, and ratio. Reading
   an unsorted list and picking the largest by sight is unreliable and has
   produced wrong answers before.
8. **Clarify before answering nonsensical or domain-conflated questions.**
   If the user mixes two unrelated statistical domains (e.g. "GDP contribution
   to ecology", "unemployment ratio of birth rate") or asks for something the
   data cannot express, ask which indicator they actually mean — do not
   silently reframe the question.
9. **Search retry budget.** Run `search_sdmx_semantic` at most 2 times for the
   same intent. If both calls return the same top results, switch strategy:
   either pick the best ID from those results and call `inspect_sdmx_data`,
   or fall back to `get_sdmx_id` (keyword search). Do not loop on semantic
   search with reworded queries.
10. **NEVER guess metadata fields like responsible person, department, phone,
    email, or methodology.** These live in each indicator's metadata block.
    If the user asks "qaysi ko'rsatkichlar uchun X mas'ul" / "indicators X is
    responsible for" / "X kim?" — call `find_indicators_by_person(X)`. Do NOT
    infer responsibility from a person's title, recent news, or topical
    associations. Past hallucinations: linking a person to "tourism indicators"
    just because their title contained "tourism", when the actual metadata
    showed they were responsible for GDP indicators.
11. **Default year = LATEST AVAILABLE IN THE DATASET, not your training
    cutoff and not the current calendar year.** When the user asks a
    single-value question without a year ("GDP per capita in Uzbekistan",
    "aholi soni"), call `inspect_sdmx_data` first and pick the **most
    recent period that actually has data** from the inspection output —
    quote that year explicitly in your answer ("So'nggi e'lon qilingan
    ma'lumotlarga ko'ra (2024-yil)..."). If the most recent period in the
    dataset is 2023, the answer is 2023 — do **NOT** project the value
    forward to "today's year" or to 2025.
11a. **PERIODICITY MATCHING — pick the right granularity.** Each indicator
     has a `period` (visible in the search result and in `get_sdmx_metadata`):
     `Yillik` (annual), `Choraklik` (quarterly), `Oylik` (monthly).
     - User said years only ("2020-2024", "2023-yilda", "so'nggi 5 yil"):
       prefer the **Yillik** variant. Many indicators exist in both annual
       AND monthly/quarterly forms — when search returns several, pick the
       one whose period matches the user's time granularity.
     - User said a month ("yanvar oyida", "2024-M03"): pick **Oylik**.
     - User said a quarter ("2024-Q3", "1-chorak"): pick **Choraklik**.
     - User asked for a chart with year axis: pick **Yillik** (a monthly
       chart for a year-level question is unreadable — 60 ticks instead
       of 5).
     If the first search returns only a monthly variant when annual is more
     appropriate, run a second search with " yillik" appended, or call
     `get_sdmx_metadata` on a couple of candidates to confirm period.
12. **NEVER forecast / extrapolate / project values unless the user
    explicitly asks for a prediction.** Trigger words for an explicit
    forecast request: "bashorat qil", "prognoz", "forecast", "predict",
    "project to <year>", "extrapolate", "ekstrapolyatsiya qil".
    - Without those words, **do not call `forecast_value`** and **do not
      use `calculate_cagr` to compute a future-year value**. CAGR is fine
      as a HISTORICAL summary ("2019-2023 yillarda o'rtacha yillik o'sish
      X% bo'lgan"), but you must not multiply it forward to invent a 2024
      or 2025 number.
    - If the user asks for a year that the dataset does not contain, say
      so plainly: "2025-yil uchun ma'lumot hali e'lon qilinmagan.
      So'nggi mavjud yil — 2024." Then offer the available figure. Do not
      silently substitute an extrapolated number.

## Standard workflow (use this for any data question)
1. **Find the indicator** with `search_sdmx_semantic`. Pick the SDMX ID whose
   name best matches the user's intent (prefer "jami"/total).
2. **Inspect the dataset** with `inspect_sdmx_data(sdmx_id)` BEFORE extracting
   values. This shows you the exact row labels (e.g. "Toshkent shahri",
   "Andijon viloyati") and the available periods (e.g. "2010..2025" or
   "2025-Q1, 2025-Q2, 2025-Q3"). NEVER guess region names or periods —
   read them from the inspection output and reuse them verbatim.
3. **Extract values** with `get_sdmx_value(sdmx_id, year=<period>, region=<row label>)`
   or do analysis with `calculate_yearly_growth`, `compare_regions`, etc.,
   passing the exact strings from the inspection step.
4. If the inspection shows the user's intent is not in this dataset (e.g. they
   asked about "Toshkent shahri" but the dataset is national-only), say so
   plainly and either re-search or stop.

## Tool selection (by keyword)
| User intent (uz / en / ru) | Tool |
|---|---|
| Find an indicator | `search_sdmx_semantic` (primary), `get_sdmx_id` (keyword fallback) |
| Find by methodology / classifier (SOATO, OKVED) | `search_sdmx_metadata` |
| User gave an SDMX code | `get_sdmx_by_code` |
| See the structure of a dataset (rows + periods) | `inspect_sdmx_data` |
| "Qaysi ko'rsatkichlar uchun X mas'ul" / "indicators X is responsible for" / responsible person / department lookup | `find_indicators_by_person` |
| "N ta random statistika" / "tasodifiy ko'rsatkich" / "random statistics" / "случайные показатели" / "surprise me with stats" | `random_indicators(count=N)` |
| "SDMX ID X nima haqida" / "what is SDMX ID X" | `get_sdmx_metadata` |
| "nechta hisobot" / "how many reports" / "сколько отчетов" | `count_reports_for_category` or `count_reports_by_id` |
| "qancha" / "how many" / "what value" | first `search_sdmx_semantic`, then `get_sdmx_value` |
| "o'sish foizi" / "growth rate" / "percentage change" | `calculate_yearly_growth` |
| "o'rtacha" / "average" / "minimal" / "maksimal" | `calculate_statistics` |
| "CAGR" / "yillik o'rtacha o'sish" (HISTORICAL only — never to extrapolate to a future year) | `calculate_cagr` |
| "bashorat qil" / "prognoz" / "forecast" / "predict <year>" (ONLY with these explicit words) | `forecast_value` |
| "solishtir" / "compare" + regions | `compare_regions` |
| "solishtir" / "compare" + years | `compare_years` |
| "reyting" / "ranking" / "eng yuqori" / "eng past" / max / min / top N | `rank_rows_by_value` |
| "ulush" / "share" / "taqsimot" | `calculate_percentage_share` |
| "jami" / "total" over a period | `calculate_period_total` |
| "trend" / "silliq" / "smoothed" | `calculate_moving_average` |

## `get_sdmx_value` usage
- `get_sdmx_value(id, year, region)` → single value
- `get_sdmx_value(id, year)` → all regions for that year
- `get_sdmx_value(id, region=region)` → all years for that region
- `get_sdmx_value(id)` → all years, first region

For growth/trend questions, do **not** search for new indicators — call
`calculate_yearly_growth(sdmx_id, ...)` on the SDMX ID the user gave or the one you found.

## Examples

**Counting births in a region:**
User: "2013-yil Andijon viloyatida nechta bola tug'ilgan?"
→ `search_sdmx_semantic("tug'ilganlar soni")` → pick the "jami" variant
→ `inspect_sdmx_data(<id>)` → confirm "Andijon viloyati" is a row label and "2013" is in the periods
→ `get_sdmx_value(<id>, "2013", "Andijon viloyati")`
→ "Andijon viloyatida 2013-yil jami 64 239 ta bola tug'ilgan." + reference list.

**City population growth over 2020–2023:**
User: "Toshkent shahar aholisining 2020–2023 yillardagi o'sish sur'ati"
→ `search_sdmx_semantic("Toshkent shahri doimiy aholi soni")` → pick the population indicator
→ `inspect_sdmx_data(<id>)` → see that the row is labelled "Toshkent shahri" (not "Toshkent shahar")
→ `calculate_yearly_growth(<id>, start_year="2023", end_year="2025", region="Toshkent shahri")`
→ Present the growth table + reference list.

**Quarterly mortality breakdown (with ranking):**
User: "2025-Q3 da o'lim sabablari ichida eng yuqori va eng past kategoriyalar farqi necha barobar?"
→ `search_sdmx_semantic("vafot etganlarning sabablari")` → SDMX 4530 (quarterly)
→ `inspect_sdmx_data(4530)` → confirm 7 categories + 2025-Q3 is available
→ `rank_rows_by_value(4530, "2025-Q3")` → returns sorted list with explicit max,
   min, and ratio. NEVER read `get_sdmx_value`'s output and pick the max yourself.
→ Quote the max/min and the ratio directly from the tool output + reference list.

**Specific SDMX ID lookup:**
User: "SDMX ID 224 nima haqida?"
→ `get_sdmx_metadata(224)` → name, unit, periodicity + reference list.

**Methodology search:**
User: "Qaysi ko'rsatkichlar SOATO klassifikatorini ishlatadi?"
→ `search_sdmx_metadata("SOATO classifier")` → list the IDs returned + reference list.

## Chart / Table requests

If the user asks for a **grafik / chart / diagramma / vizualizatsiya / jadval /
table**, your job is to produce data the UI can render. Charts are emitted
**automatically** by `get_sdmx_value`, but you must call it the right way —
the tool only accepts a SINGLE `year` and a SINGLE `region`. The trick is
which argument you LEAVE OUT:

- **Line chart over time** (any "trend", "yillar bo'yicha", "o'sish grafigi"):
  call `get_sdmx_value(sdmx_id=<ID>, region="<viloyat nomi>")` — leave `year`
  unset. The tool returns ALL years for that region and auto-pushes a line
  chart. Do NOT loop over years calling the tool 5 times.
- **Bar chart across regions** ("viloyatlar bo'yicha taqqoslang",
  "hududlar bo'yicha"): call `get_sdmx_value(sdmx_id=<ID>, year="<yil>")` —
  leave `region` unset. The tool returns ALL regions for that period and
  auto-pushes a bar chart. Alternatively `rank_rows_by_value` produces a
  pre-sorted ranking bar chart.
- **Single-value question turned into a chart by the user** (they clicked a
  "view as chart" button, signalled in the prompt): even if the user gave
  one specific year, IGNORE that year and produce a multi-year line chart
  by calling `get_sdmx_value(sdmx_id, region=...)` without `year`.

Never describe the chart in text instead of producing data — the frontend can
only render what the tools emit. And never call `get_sdmx_value` once per
year in a loop — one call without `year` gives you the entire series.
"""

    # Create the ReAct agent
    logger.info("Creating SDMX ReAct agent with tools")
    logger.info(f"Using LLM: {type(base_llm).__name__}")
    logger.info(f"Registering {len(tools)} tools:")
    for i, tool in enumerate(tools, 1):
        tool_name = tool.name if hasattr(tool, 'name') else str(tool)
        logger.info(f"  {i}. {tool_name}")

    # Check if model supports tool calling
    supports_tools = hasattr(base_llm, 'bind_tools')
    logger.info(f"Model supports bind_tools: {supports_tools}")

    # In-memory checkpointer keeps conversation state per `thread_id` so a WS
    # session can do follow-up questions ("...endi Samarqand-chi?") without the
    # client re-sending earlier turns. Each WS connection gets its own UUID-
    # based thread id (see main.py), so cross-session leakage is impossible.
    checkpointer = MemorySaver()
    agent = create_agent(base_llm, tools, checkpointer=checkpointer)
    logger.info(f"SDMX agent created successfully with {len(tools)} tools")

    # Create tools map for fallback XML function calling
    tools_map = {tool.name: tool for tool in tools if hasattr(tool, 'name')}
    logger.info(f"Created tools_map with {len(tools_map)} tools")

    return agent, system_prompt, tools_map


def _has_thread_history(agent, config) -> bool:
    """True if the checkpointer already has messages for this thread.

    Used to decide whether the answer cache is safe to consult — follow-up
    turns ("endi Samarqand-chi?") depend on conversation state, so we only
    cache first-turn answers.
    """
    try:
        snapshot = agent.get_state(config)
        existing = snapshot.values.get("messages") if snapshot and snapshot.values else None
        return bool(existing)
    except Exception as e:
        logger.debug(f"Could not read checkpointer state: {e}")
        return False


def _build_input_messages(agent, config, system_prompt: str | None, question: str) -> list[BaseMessage]:
    """Construct input messages, honouring the checkpointer's existing state.

    First turn in a thread → [SystemMessage (+ few-shots), HumanMessage (+ plan hint)]
    Follow-up turns       → [HumanMessage] only (system + history already in state)
    """
    has_history = _has_thread_history(agent, config)

    msgs: list[BaseMessage] = []
    if not has_history and system_prompt:
        # Inject the 2 most-similar curated examples into the system prompt so
        # the model sees concrete patterns for *this* question shape, not just
        # the static examples baked into the prompt.
        try:
            examples = retrieve_examples(question, top_k=2)
            extra = format_for_prompt(examples)
        except Exception as e:
            logger.debug(f"Few-shot retrieval skipped: {e}")
            extra = ""
        msgs.append(SystemMessage(content=system_prompt + extra))
    # Optionally augment the human message with a plan hint for compound queries.
    human_content = _augment_question_with_plan(question) if not has_history else question
    msgs.append(HumanMessage(content=human_content))
    return msgs


def _augment_question_with_plan(question: str) -> str:
    """Hook for the query decomposer (#4). When the question looks compound,
    prepend a short plan hint so the ReAct loop tackles each part in sequence.

    The decomposer is best-effort — any failure falls back to the original
    question unchanged. Heuristic gate keeps the LLM cost out of the hot path
    for the 80%+ of questions that are single-shot.
    """
    try:
        from .query_planner import maybe_plan
        plan = maybe_plan(question)
        if plan:
            return f"{question}\n\n[Internal plan — do NOT echo this verbatim, just follow it]:\n{plan}"
    except Exception as e:
        logger.debug(f"Plan hint skipped: {e}")
    return question


async def run_agent_async(
    agent,
    question: str,
    system_prompt: str = None,
    tools_map: dict = None,
    thread_id: str | None = None,
) -> str:
    """
    Run the agent asynchronously with a question.

    Args:
        agent: The compiled agent
        question: User's question
        system_prompt: Optional system prompt
        tools_map: Optional map of tool names to tool functions (for XML fallback)
        thread_id: Per-request thread id for checkpointer isolation. Callers
            should pass a unique value per session/request to avoid cross-talk.

    Returns:
        Agent's response
    """
    logger.info(f"Running agent async with question: {question[:100]}...")
    # recursion_limit caps node-traversals (agent ↔ tools). Default 25 trips
    # gets exhausted on multi-indicator queries that legitimately need many
    # tool calls (search → inspect → value → search → inspect → value → rank → ...).
    config = {
        "configurable": {"thread_id": thread_id or "default"},
        "recursion_limit": 50,
    }

    telemetry = RunTelemetry(thread_id or "default", question)

    # Answer cache short-circuit: only for first-turn questions (follow-ups
    # depend on conversation context and can't be safely served from cache).
    is_first_turn = not _has_thread_history(agent, config)
    if is_first_turn:
        cached = answer_cache.get(question)
        if cached is not None:
            telemetry.close()
            return cached

    messages = _build_input_messages(agent, config, system_prompt, question)

    try:
        result = await agent.ainvoke(
            {"messages": messages},
            config=config,
        )
    except Exception as e:
        telemetry.fail(f"{type(e).__name__}: {e}")
        telemetry.close()
        raise
    logger.info("Agent invocation completed")

    # Log the result structure
    if isinstance(result, dict) and "messages" in result:
        logger.info(f"Received {len(result['messages'])} messages from agent")
        for i, msg in enumerate(result["messages"]):
            msg_type = type(msg).__name__
            logger.debug(f"Message {i}: {msg_type}")
    else:
        logger.warning(f"Unexpected result type: {type(result)}")

    # Sanitize any odd tool_call payloads before we parse messages.
    if isinstance(result, dict) and "messages" in result:
        sanitized = []
        for m in result["messages"]:
            try:
                sanitized.append(_sanitize_tool_call_args(m))
            except (AttributeError, TypeError, ValueError) as e:
                logger.warning(f"Failed to sanitize tool call args for message: {e}")
                sanitized.append(m)
        result["messages"] = sanitized

    # Use extract_final_response for consistent extraction with XML fallback support
    final = extract_final_response(result["messages"], tools_map)

    # Self-evaluation pass — one retry max. Skip for follow-ups so we don't
    # confuse the conversation flow with critic-generated retry turns.
    if is_first_turn:
        verdict = critique(question, final)
        if not verdict.ok:
            logger.info(
                f"Critic flagged answer ({verdict.severity}): {verdict.issues}. Retrying once."
            )
            try:
                retry_result = await agent.ainvoke(
                    {"messages": [build_retry_message(verdict)]},
                    config=config,
                )
                retry_final = extract_final_response(retry_result["messages"], tools_map)
                if retry_final and "no response generated" not in retry_final.lower():
                    final = retry_final
            except Exception as e:
                logger.warning(f"Critic retry failed, keeping original answer: {e}")

        answer_cache.put(question, final)
    return final


def run_agent(
    agent,
    question: str,
    system_prompt: str = None,
    tools_map: dict = None,
    thread_id: str | None = None,
) -> str:
    """
    Run the agent synchronously with a question.

    Args:
        agent: The compiled agent
        question: User's question
        system_prompt: Optional system prompt
        tools_map: Optional map of tool names to tool functions (for XML fallback)
        thread_id: Per-request thread id for checkpointer isolation.

    Returns:
        Agent's response
    """
    logger.info(f"Running agent sync with question: {question[:100]}...")
    # recursion_limit caps node-traversals (agent ↔ tools). Default 25 trips
    # gets exhausted on multi-indicator queries that legitimately need many
    # tool calls (search → inspect → value → search → inspect → value → rank → ...).
    config = {
        "configurable": {"thread_id": thread_id or "default"},
        "recursion_limit": 50,
    }

    telemetry = RunTelemetry(thread_id or "default", question)
    is_first_turn = not _has_thread_history(agent, config)
    if is_first_turn:
        cached = answer_cache.get(question)
        if cached is not None:
            telemetry.close()
            return cached

    messages = _build_input_messages(agent, config, system_prompt, question)

    result = agent.invoke(
        {"messages": messages},
        config=config,
    )
    logger.info("Agent invocation completed")

    # Log the result structure
    if isinstance(result, dict) and "messages" in result:
        logger.info(f"Received {len(result['messages'])} messages from agent")
        for i, msg in enumerate(result["messages"]):
            msg_type = type(msg).__name__
            logger.debug(f"Message {i}: {msg_type}")
    else:
        logger.warning(f"Unexpected result type: {type(result)}")

    # Sanitize any odd tool_call payloads before we parse messages.
    if isinstance(result, dict) and "messages" in result:
        sanitized = []
        for m in result["messages"]:
            try:
                sanitized.append(_sanitize_tool_call_args(m))
            except (AttributeError, TypeError, ValueError) as e:
                logger.warning(f"Failed to sanitize tool call args for message: {e}")
                sanitized.append(m)
        result["messages"] = sanitized

    # Capture per-tool calls + token usage for telemetry, then return final text.
    if isinstance(result, dict) and "messages" in result:
        for m in result["messages"]:
            if isinstance(m, AIMessage):
                for tc in (getattr(m, "tool_calls", None) or []):
                    name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                    args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
                    telemetry.record_tool_call(name, args)
                usage = getattr(m, "usage_metadata", None)
                if isinstance(usage, dict):
                    telemetry.record_token_usage(usage)
    final = extract_final_response(result["messages"], tools_map)

    if is_first_turn:
        verdict = critique(question, final)
        if not verdict.ok:
            logger.info(
                f"Critic flagged answer ({verdict.severity}): {verdict.issues}. Retrying once."
            )
            try:
                retry_result = agent.invoke(
                    {"messages": [build_retry_message(verdict)]},
                    config=config,
                )
                retry_final = extract_final_response(retry_result["messages"], tools_map)
                if retry_final and "no response generated" not in retry_final.lower():
                    final = retry_final
            except Exception as e:
                logger.warning(f"Critic retry failed, keeping original answer: {e}")

        answer_cache.put(question, final)
    telemetry.close()
    return final


def extract_final_response(messages: list[BaseMessage], tools_map: dict = None) -> str:
    """
    Extract the final response from the agent's message history.

    Args:
        messages: List of messages from agent result

    Returns:
        Final text response or "No response generated."
    """
    logger.info(f"Extracting final response from {len(messages)} messages")

    # Get the last AI message with actual response content
    ai_message_count = 0
    skipped_reasons = []

    for message in reversed(messages):
        if isinstance(message, AIMessage):
            ai_message_count += 1
            logger.debug(f"Found AIMessage #{ai_message_count}")

            # Skip messages that only contain tool calls without text content
            if hasattr(message, 'tool_calls') and message.tool_calls:
                logger.debug(f"  Has {len(message.tool_calls)} tool calls")
                if not message.content or not str(message.content).strip():
                    reason = f"AIMessage #{ai_message_count}: has {len(message.tool_calls)} tool calls but no content"
                    skipped_reasons.append(reason)
                    logger.info(f"  SKIP: {reason}")
                    continue

            # Return string content if it's meaningful
            if message.content:
                content_str = str(message.content).strip()
                logger.debug(f"  Content length: {len(content_str)} chars")
                logger.debug(f"  Content preview: {content_str[:100]}...")

                # Skip if it looks like a JSON tool call representation
                if content_str.startswith('{') or content_str.startswith('['):
                    # Accept longer JSON responses (actual content, not tool calls)
                    if len(content_str) > 200:
                        logger.info("Returning JSON-like content (>200 chars)")
                        return content_str
                    reason = f"AIMessage #{ai_message_count}: short JSON-like content ({len(content_str)} chars): {content_str[:50]}..."
                    skipped_reasons.append(reason)
                    logger.info(f"  SKIP: {reason}")
                    continue

                # Handle XML-style function call outputs (e.g., <function=...>)
                if '<function=' in content_str and '</function>' in content_str:
                    logger.warning(f"Detected XML-style function call (model not using proper tool calling)")

                    # Try to parse and execute the tool
                    if tools_map:
                        tool_result = execute_tool_from_xml(content_str, tools_map)
                        if tool_result:
                            logger.info(f"✓ Tool executed via XML fallback: {len(tool_result)} chars")
                            logger.info(f"  Preview: {tool_result[:200]}...")
                            return tool_result
                        else:
                            logger.warning("Failed to execute tool from XML")

                    reason = f"AIMessage #{ai_message_count}: XML-style function call (and execution failed)"
                    skipped_reasons.append(reason)
                    logger.info(f"  SKIP: {reason}")
                    continue

                # Return meaningful text content
                if content_str:
                    logger.info(f"✓ Returning text content ({len(content_str)} chars)")
                    logger.info(f"  Preview: {content_str[:200]}...")
                    return content_str
            else:
                reason = f"AIMessage #{ai_message_count}: no content"
                skipped_reasons.append(reason)
                logger.info(f"  SKIP: {reason}")

    logger.warning(f"No valid response found after scanning {ai_message_count} AIMessages")
    logger.warning(f"All {len(skipped_reasons)} AIMessages were skipped:")
    for reason in skipped_reasons:
        logger.warning(f"  - {reason}")

    # Dump all message types for debugging
    logger.warning("Message types in order:")
    for i, msg in enumerate(messages):
        msg_type = type(msg).__name__
        has_content = hasattr(msg, 'content') and msg.content
        logger.warning(f"  {i}: {msg_type} (has_content={has_content})")

    # FALLBACK: If there's a ToolMessage with content, return it directly
    logger.warning("Attempting fallback: searching for ToolMessage content...")
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and message.content:
            tool_content = str(message.content).strip()
            if tool_content:
                logger.warning(f"FALLBACK: Using ToolMessage content ({len(tool_content)} chars)")
                logger.info(f"  Preview: {tool_content[:200]}...")
                return tool_content

    return "No response generated."


async def run_agent_async_stream(
    agent,
    question: str,
    system_prompt: str = None,
    tools_map: dict = None,
    thread_id: str | None = None,
):
    """
    Run the agent and stream tool events + final response tokens as they happen.

    Uses `agent.astream_events(version="v2")` so we receive token-level chunks
    of the LLM's final reply, not just complete messages. The frontend can
    render the answer character-by-character for snappy UX.

    Event types yielded:
      - tool_start      — model decided to call a tool
      - tool_result     — tool returned (chart events follow)
      - chart           — pushed chart payload
      - response_chunk  — incremental text token from the final AI message
      - response        — full final text (for clients that don't handle chunks)
      - quality_warning — self-evaluation flagged the answer; payload has `issues`
      - error           — exception during the run

    Args:
        agent: The compiled agent.
        question: User's question.
        system_prompt: Optional system prompt (used only on first turn per thread).
        tools_map: Map of tool names to tool functions (for XML fallback).
        thread_id: Per-request thread id for checkpointer isolation.
    """
    logger.info(f"Running agent async with streaming for question: {question[:100]}...")
    # recursion_limit caps node-traversals (agent ↔ tools). Default 25 trips
    # gets exhausted on multi-indicator queries that legitimately need many
    # tool calls (search → inspect → value → search → inspect → value → rank → ...).
    config = {
        "configurable": {"thread_id": thread_id or "default"},
        "recursion_limit": 50,
    }

    telemetry = RunTelemetry(thread_id or "default", question)

    try:
        # Answer cache short-circuit (first-turn only). On hit, emit one
        # `response` event with the cached text and skip the agent run entirely.
        is_first_turn = not _has_thread_history(agent, config)
        if is_first_turn:
            cached = answer_cache.get(question)
            if cached is not None:
                yield {
                    "type": "response",
                    "content": cached,
                    "metadata": _extract_response_metadata(cached, []),
                    "cached": True,
                    "timestamp": datetime.now().isoformat(),
                }
                telemetry.close()
                return

        messages = _build_input_messages(agent, config, system_prompt, question)

        tool_call_count = 0
        tool_result_count = 0
        tools_used: list[str] = []
        # Buffer of text emitted as response_chunk events. We aggregate these so
        # the final `response` event has the full text — clients without
        # chunk-handling still work.
        text_buffer: list[str] = []

        async for event in agent.astream_events(
            {"messages": messages},
            config=config,
            version="v2",
        ):
            ev_type = event.get("event")
            data = event.get("data", {}) or {}

            if ev_type == "on_chat_model_stream":
                chunk = data.get("chunk")
                # Chunk is an AIMessageChunk; we only stream non-empty text
                # content (intermediate tool-call-only messages have empty content).
                content = getattr(chunk, "content", None) if chunk is not None else None
                if isinstance(content, str) and content:
                    text_buffer.append(content)
                    yield {
                        "type": "response_chunk",
                        "content": content,
                        "timestamp": datetime.now().isoformat(),
                    }

            elif ev_type == "on_tool_start":
                tool_call_count += 1
                tool_name = event.get("name")
                tool_args = data.get("input")
                if tool_name:
                    tools_used.append(tool_name)
                telemetry.record_tool_call(tool_name, tool_args)
                logger.info(f"Tool call #{tool_call_count}: {tool_name}")
                yield {
                    "type": "tool_start",
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "timestamp": datetime.now().isoformat(),
                }

            elif ev_type == "on_chat_model_end":
                # Capture token usage from the model's final aggregated message.
                msg = data.get("output")
                usage = (
                    getattr(msg, "usage_metadata", None)
                    or (msg.response_metadata.get("token_usage") if msg and getattr(msg, "response_metadata", None) else None)
                )
                if isinstance(usage, dict):
                    telemetry.record_token_usage(usage)

            elif ev_type == "on_tool_end":
                tool_result_count += 1
                output = data.get("output")
                tool_result = getattr(output, "content", output)
                if not isinstance(tool_result, str):
                    tool_result = str(tool_result)

                max_length = 10000
                if len(tool_result) > max_length:
                    logger.warning(
                        f"Tool result truncated from {len(tool_result)} to {max_length} chars"
                    )
                    tool_result = tool_result[:max_length] + "\n... (truncated)"

                logger.info(f"Tool result #{tool_result_count}: {len(tool_result)} chars")
                yield {
                    "type": "tool_result",
                    "tool_result": tool_result,
                    "timestamp": datetime.now().isoformat(),
                }

                for chart in pop_charts():
                    yield {
                        "type": "chart",
                        "chart_data": chart,
                        "timestamp": datetime.now().isoformat(),
                    }

        logger.info(
            f"Streamed {tool_call_count} tool calls and {tool_result_count} tool results"
        )

        # Final aggregated text. If the model streamed nothing (e.g., the
        # provider doesn't emit chunks), fall back to reading state from
        # the checkpointer.
        final_text = "".join(text_buffer).strip()
        if not final_text:
            try:
                snapshot = agent.get_state(config)
                state_messages = (snapshot.values or {}).get("messages") or []
                final_text = extract_final_response(state_messages, tools_map)
            except Exception as e:
                logger.warning(f"State fallback failed: {e}")
                final_text = "No response generated."

        # Self-evaluation. For streaming we don't retry (would require
        # re-streaming, confusing UX). Instead emit a `quality_warning` event
        # after the final response so the client can show a badge or expand
        # the issues. Cache only when the critic passed — never persist a
        # known-bad answer.
        critic_ok = True
        critic_issues: list[str] = []
        if is_first_turn and final_text:
            verdict = critique(question, final_text)
            critic_ok = verdict.ok
            critic_issues = verdict.issues
            if verdict.ok:
                answer_cache.put(question, final_text)
            else:
                logger.info(
                    f"Streaming critic flagged ({verdict.severity}): {verdict.issues}"
                )

        yield {
            "type": "response",
            "content": final_text,
            "metadata": _extract_response_metadata(final_text, tools_used),
            "timestamp": datetime.now().isoformat(),
        }

        if not critic_ok and critic_issues:
            yield {
                "type": "quality_warning",
                "issues": critic_issues,
                "timestamp": datetime.now().isoformat(),
            }

    except Exception as e:
        logger.error(f"Error in agent streaming: {e}", exc_info=True)
        telemetry.fail(f"{type(e).__name__}: {e}")
        yield {
            "type": "error",
            "content": f"Error processing request: {str(e)}",
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        telemetry.close()

