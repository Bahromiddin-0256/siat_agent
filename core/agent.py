"""
SDMX Agent using LangGraph.

This module implements a ReAct agent that can search for SDMX IDs
based on user questions using LangGraph's prebuilt agent with Ollama.
"""
from typing import Annotated, Any, TypedDict
from datetime import datetime
import re
import json

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain.agents import create_agent
from langgraph.graph.message import add_messages

from .llm import base_llm, _sanitize_tool_call_args
from .logger import setup_logger
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
    calculate_yearly_growth,
    calculate_statistics,
    calculate_cagr,
    compare_regions,
    rank_regions,
    calculate_percentage_share,
    compare_years,
    calculate_period_total,
    calculate_moving_average,
    count_reports_for_category,
    count_reports_by_id,
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

        # Data extraction tools
        get_sdmx_value,  # Extract actual data values
        get_sdmx_metadata,  # Get indicator metadata

        # Time series analysis tools
        calculate_yearly_growth,  # Calculate year-over-year growth rates
        calculate_statistics,  # Descriptive statistics (mean, median, min, max, std dev)
        calculate_cagr,  # Compound Annual Growth Rate
        calculate_period_total,  # Total sum over period
        calculate_moving_average,  # Moving average for smoothed trends

        # Regional comparison tools
        compare_regions,  # Compare multiple regions for a year
        rank_regions,  # Rank regions by value
        calculate_percentage_share,  # Regional percentage distribution

        # Comparison tools
        compare_years,  # Compare two specific years
    ]

    # System prompt for the agent
    system_prompt = """You are a statistical data assistant for Uzbekistan's statistics agency (SIAT).
You answer questions in the user's language (Uzbek, Russian, or English) about statistical
indicators by selecting the right tool, executing it, and explaining the result.

## Core rules
1. **Always respond in natural language after a tool runs.** Never end on a raw tool call —
   summarize and format the result for the user.
2. **State which indicator you used.** Include the exact name and SDMX ID in the response.
3. **Always include units** returned by the tool (kishi, mlrd. so'm, mln so'm, etc.).
4. **Prefer "jami" (total)** when several variants exist (e.g. "jami" vs "qiz bolalar" /
   "o'g'il bolalar" / "shahar" / "qishloq"). If still ambiguous, ask the user.
5. **End every data response with a reference list:**
   ```
   ---
   Foydalanilgan ko'rsatkichlar:
   - SDMX ID <id>: <Indicator Name>
   ```
6. For general "what data exists?" questions, do not call tools — point to
   https://siat.stat.uz and optionally suggest `list_sdmx_categories`.

## Tool selection (by keyword)
| User intent (uz / en / ru) | Tool |
|---|---|
| Find an indicator | `search_sdmx_semantic` (primary), `get_sdmx_id` (keyword fallback) |
| Find by methodology / classifier (SOATO, OKVED) | `search_sdmx_metadata` |
| User gave an SDMX code | `get_sdmx_by_code` |
| "SDMX ID X nima haqida" / "what is SDMX ID X" | `get_sdmx_metadata` |
| "nechta hisobot" / "how many reports" / "сколько отчетов" | `count_reports_for_category` or `count_reports_by_id` |
| "qancha" / "how many" / "what value" | first `search_sdmx_semantic`, then `get_sdmx_value` |
| "o'sish foizi" / "growth rate" / "percentage change" | `calculate_yearly_growth` |
| "o'rtacha" / "average" / "minimal" / "maksimal" | `calculate_statistics` |
| "CAGR" / "yillik o'rtacha o'sish" | `calculate_cagr` |
| "solishtir" / "compare" + regions | `compare_regions` |
| "solishtir" / "compare" + years | `compare_years` |
| "reyting" / "ranking" / "eng yuqori" / "eng past" | `rank_regions` |
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
→ `get_sdmx_value(<id>, "2013", "Andijon")`
→ "Andijon viloyatida 2013-yil jami 64 239 ta bola tug'ilgan." + reference list.

**Specific SDMX ID lookup:**
User: "SDMX ID 224 nima haqida?"
→ `get_sdmx_metadata(224)` → "SDMX ID 224: Tug'ilganlar soni (qiz bolalar), o'lchov: kishi, davr: yillik" + reference list.

**Methodology search:**
User: "Qaysi ko'rsatkichlar SOATO klassifikatorini ishlatadi?"
→ `search_sdmx_metadata("SOATO classifier")` → list the IDs returned + reference list.
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

    agent = create_agent(base_llm, tools)
    logger.info(f"SDMX agent created successfully with {len(tools)} tools")

    # Create tools map for fallback XML function calling
    tools_map = {tool.name: tool for tool in tools if hasattr(tool, 'name')}
    logger.info(f"Created tools_map with {len(tools_map)} tools")

    return agent, system_prompt, tools_map


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
    config = {"configurable": {"thread_id": thread_id or "default"}}

    # Build messages with system prompt
    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=question))

    result = await agent.ainvoke(
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

    # Use extract_final_response for consistent extraction with XML fallback support
    return extract_final_response(result["messages"], tools_map)


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
    config = {"configurable": {"thread_id": thread_id or "default"}}

    # Build messages with system prompt
    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=question))

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

    # Use extract_final_response for consistent extraction with XML fallback support
    return extract_final_response(result["messages"], tools_map)


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
    Run the agent and yield tool calls / results / final response *as they happen*.

    Uses `agent.astream(stream_mode="updates")` so each LangGraph node update is
    surfaced to the client immediately, rather than after the whole run finishes.

    Args:
        agent: The compiled agent
        question: User's question
        system_prompt: Optional system prompt
        tools_map: Optional map of tool names to tool functions (for XML fallback)
        thread_id: Per-request thread id for checkpointer isolation.

    Yields:
        dict: Streaming messages with type, tool info, and results
    """
    logger.info(f"Running agent async with streaming for question: {question[:100]}...")
    config = {"configurable": {"thread_id": thread_id or "default"}}

    try:
        messages: list[BaseMessage] = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=question))

        all_messages: list[BaseMessage] = []
        seen_message_ids: set[int] = set()
        tool_call_count = 0
        tool_result_count = 0

        async for update in agent.astream(
            {"messages": messages},
            config=config,
            stream_mode="updates",
        ):
            # update is a dict like {"agent": {"messages": [...]}, ...} keyed by node name
            for node_name, node_state in update.items():
                node_messages = (
                    node_state.get("messages", []) if isinstance(node_state, dict) else []
                )
                for raw in node_messages:
                    try:
                        msg = _sanitize_tool_call_args(raw)
                    except (AttributeError, TypeError, ValueError) as e:
                        logger.warning(f"Failed to sanitize tool call args: {e}")
                        msg = raw

                    # Deduplicate: a checkpointer can re-emit the same message across updates.
                    msg_key = id(msg)
                    if msg_key in seen_message_ids:
                        continue
                    seen_message_ids.add(msg_key)
                    all_messages.append(msg)

                    if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                        for tool_call in msg.tool_calls:
                            tool_call_count += 1
                            tool_name = (
                                tool_call.get("name") if isinstance(tool_call, dict)
                                else getattr(tool_call, "name", None)
                            )
                            tool_args = (
                                tool_call.get("args") if isinstance(tool_call, dict)
                                else getattr(tool_call, "args", None)
                            )
                            logger.info(f"Tool call #{tool_call_count}: {tool_name}")
                            yield {
                                "type": "tool_start",
                                "tool_name": tool_name,
                                "tool_args": tool_args,
                                "timestamp": datetime.now().isoformat(),
                            }

                    elif isinstance(msg, ToolMessage):
                        tool_result_count += 1
                        tool_result = msg.content
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

        final_response = extract_final_response(all_messages, tools_map)
        yield {
            "type": "response",
            "content": final_response,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error in agent streaming: {e}", exc_info=True)
        yield {
            "type": "error",
            "content": f"Error processing request: {str(e)}",
            "timestamp": datetime.now().isoformat(),
        }

