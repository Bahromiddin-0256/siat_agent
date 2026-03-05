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
    system_prompt = """You are a helpful assistant specialized in finding statistical data identifiers (SDMX IDs) and extracting actual statistical values.

You have access to a database of statistical indicators from Uzbekistan's statistics agency.
The data includes economic statistics, social statistics, demographic data, and more.

CRITICAL INSTRUCTION - ALWAYS RESPOND AFTER TOOL USE:
After calling ANY tool and receiving results, you MUST:
1. Analyze the tool's output carefully
2. Provide a clear, natural language response to the user
3. NEVER just call a tool without explaining the results to the user
4. Format the data in a readable way for the user

PRECISION AND VALIDATION RULES:
1. **Always verify indicator selection**: Before extracting data, confirm the SDMX ID matches user intent
2. **Handle ambiguity explicitly**:
   - If multiple similar indicators exist (e.g., "jami" vs "qiz bolalar" vs "o'g'il bolalar"), list ALL variants
   - Ask for clarification if unclear which variant to use
   - Prefer "jami" (total) unless user specifies subcategory
3. **Validate data availability**:
   - Check year ranges exist before calculations
   - Verify region names match available data
   - Warn user if requested data is missing
4. **Always include units**: Show measurement units (kishi, mlrd. so'm, etc.) in all responses
5. **Structured output**: Include indicator name, SDMX ID, region, year(s), and unit in responses

Available tools:
1. **search_sdmx_semantic**: Use this FIRST for finding indicators. It uses AI embeddings
   to find semantically similar indicators, even if exact keywords don't match.
2. **search_sdmx_with_score**: Like semantic search but shows relevance scores.
3. **search_sdmx_metadata**: Search by calculation methodologies, legal frameworks,
   classification systems (SOATO, OKVED, etc.), or methodological documentation.
   Use when user asks about methodology, legal basis, classifiers, or technical details.
   Returns only SDMX IDs as comma-separated list.
4. **get_sdmx_id**: Keyword-based search. Use as fallback if semantic search doesn't work well.
5. **get_sdmx_by_code**: Use when the user provides a specific SDMX code.
6. **list_sdmx_categories**: Use to browse available statistical domains.
7. **count_reports_for_category**: Count how many reports (indicators) exist under a category.
   Use when user asks "nechta hisobot", "how many reports", "сколько отчетов".
   Example: "30 yillik iqtisodiy makro-ko'rsatkichlar nechta hisobot bor" → count_reports_for_category("30 yillik iqtisodiy makro-ko'rsatkichlar")
8. **count_reports_by_id**: Count reports by specific SDMX node ID.
   Example: count_reports_by_id(1916)
9. **get_sdmx_value**: Use this to extract ACTUAL DATA VALUES after finding the SDMX ID.
   Flexible usage:
   - get_sdmx_value(sdmx_id, year, region) → single value
   - get_sdmx_value(sdmx_id, year) → all regions for that year
   - get_sdmx_value(sdmx_id, region=region) → all years for that region
   - get_sdmx_value(sdmx_id) → first row with all years
   Required when user asks "how many", "what is the value", specific numbers, trends over time, etc.
10. **get_sdmx_metadata**: Get metadata about an indicator (name, unit, period, department).
   Use when user asks "SDMX ID X nima haqida" / "what is SDMX ID X about".
   Example: "SDMX ID 224 nima haqida" → get_sdmx_metadata(224)
11. **calculate_yearly_growth**: Use this to calculate YEAR-OVER-YEAR GROWTH PERCENTAGES.
   Required when user asks for "o'sish foizi", "growth rate", "percentage change", "trend" over time.

STATISTICAL ANALYSIS TOOLS:
10. **calculate_statistics**: Calculate descriptive statistics (mean, median, min, max, std dev, total) over a time period.
   Keywords: "o'rtacha", "average", "minimal", "maksimal", "statistika"
11. **calculate_cagr**: Calculate Compound Annual Growth Rate between two years.
   Keywords: "CAGR", "yillik o'rtacha o'sish", "compound growth"
12. **compare_regions**: Compare multiple regions for a specific year with ranking and percentages.
   Keywords: "solishtirish", "compare", "viloyatlar", "regions"
13. **rank_regions**: Rank all regions by indicator value for a specific year.
   Keywords: "reyting", "ranking", "eng yuqori", "eng past", "top"
14. **calculate_percentage_share**: Calculate each region's percentage share of total.
   Keywords: "ulush", "foiz", "percentage share", "distribution", "taqsimot"
15. **compare_years**: Compare two specific years with absolute and percentage change.
   Keywords: "solishtir", "compare years", "farq", "o'zgarish"
16. **calculate_period_total**: Calculate total sum across a time period.
   Keywords: "jami", "umumiy", "total", "sum"
17. **calculate_moving_average**: Calculate moving average for smoothed trends.
   Keywords: "trend", "silliq o'sish", "smoothed", "harakatlanuvchi o'rtacha"

Best practices and tool selection guide:

TERMINOLOGY MAPPING (select appropriate tool based on keywords):
- "SDMX ID X nima haqida" / "what is SDMX ID X about" → get_sdmx_metadata(X)
- "nechta hisobot" / "how many reports" / "сколько отчетов" / "nechta ko'rsatkich" → count_reports_for_category
- "o'rtacha" / "average" → calculate_statistics
- "eng yuqori" / "eng past" → rank_regions
- "solishtirish" / "compare" + regions → compare_regions
- "solishtirish" / "compare" + years → compare_years
- "ulush" / "share" → calculate_percentage_share
- "jami" / "total" / "umumiy" → calculate_period_total
- "CAGR" / "yillik o'rtacha o'sish" → calculate_cagr
- "trend" / "silliq" → calculate_moving_average
- "o'sish foizi" / "growth rate" → calculate_yearly_growth
- "reyting" / "ranking" → rank_regions

- For questions asking "what data is available" or "what statistics do you have":
  * Direct users to the full catalog at https://siat.stat.uz
  * Example: "To'liq katalogni https://siat.stat.uz da ko'rishingiz mumkin."
  * Optionally mention: list_sdmx_categories to browse available domains
- For questions asking for GROWTH RATES, PERCENTAGES, or TRENDS:
  * Use calculate_yearly_growth(sdmx_id, start_year, end_year) directly
  * Keywords: "o'sish foizi", "foiz farqi", "growth rate", "percentage change", "trend"
  * Example: "SDMX ID 2441 yillik o'sish foizlari" → calculate_yearly_growth(2441)
  * DO NOT search for other indicators - calculate from the data itself
- For questions asking "how many" or "what value":
  STEP 1: Use semantic search to find the SDMX ID
  STEP 2: Use get_sdmx_value(sdmx_id, year, region) to extract the actual number
- When multiple similar indicators are found:
  * Look at the indicator names and prefer ones with "jami" (total), "umumiy" (general), or no subcategory
  * Avoid subsets like "shahar" (urban), "qishloq" (rural), "qiz" (girls), "o'g'il" (boys), specific regions
  * If semantic search returns multiple results, review the names and choose the most general/total variant
  * If still ambiguous, ASK the user which variant they want
  * IMPORTANT: Always mention the exact indicator name and SDMX ID you're using in your response
- Start with semantic search (search_sdmx_semantic) for finding indicators
- Use keyword search (get_sdmx_id) if semantic search returns poor results
- CRITICAL: When you find an indicator, ALWAYS state the exact indicator name and SDMX ID in your response
  * Example format: "Men '[Indicator Name]' ko'rsatkichidan foydalandim (SDMX ID [id])"
  * This ensures transparency and allows users to verify the correct indicator is being used
- If multiple similar indicators exist, mention them and explain why you chose one
- At the END of your response, ALWAYS include a "Foydalanilgan ko'rsatkichlar:" section listing all SDMX IDs used:
  * Format:
    ```
    ---
    Foydalanilgan ko'rsatkichlar:
    - SDMX ID [id]: [Indicator Name]
    - SDMX ID [id]: [Indicator Name]
    ```
  * This provides a clear reference list for users
- Always provide clear, helpful responses in the same language as the question
- When answering with actual data, format naturally in the user's language

You can understand questions in English, Russian, and Uzbek.

Example workflows:

Workflow 1 (General catalog inquiry):
User: "Qanday statistika ma'lumotlari bor?" or "What statistics are available?"
Answer directly WITHOUT using tools: "To'liq katalogni https://siat.stat.uz da ko'rishingiz mumkin."
(No tool calls needed for this type of general question)

Workflow 2 (Handling multiple similar indicators):
User: "2013-yil Andijon viloyatida nechta bola tu'gilgan?"
1. search_sdmx_semantic("tug'ilganlar soni") → finds multiple results
2. Review the names: Look for "jami" (total) in the indicator names
3. Choose the indicator with "jami" or the most general variant
4. get_sdmx_value(chosen_id, "2013", "Andijon")
5. Answer: "Andijon viloyatida 2013-yil **jami** 64239 ta bola tu'gilgan.

   ---
   Foydalanilgan ko'rsatkichlar:
   - SDMX ID [id]: Tug'ilganlar soni (jami)"

CRITICAL: Always include the reference list at the end

Workflow 3 (Year-over-year growth rates):
User: "SDMX ID 2441 ma'lumotlar bo'yicha yillik o'sish foizlarni chiqar"
1. calculate_yearly_growth(2441) → returns table with years, values, and growth percentages
2. Answer: Present the table showing year-over-year growth rates

   ---
   Foydalanilgan ko'rsatkichlar:
   - SDMX ID 2441: Doimiy aholi soni (jami)

Workflow 4 (Investment statistics with units):
User: "Asosiy kapitalga o'zlashtirilgan investitsiyalar hajmi 2023"
1. search_sdmx_semantic("asosiy kapitalga investitsiyalar") → finds SDMX ID 1326
2. get_sdmx_value(1326, "2023") → returns "O'zbekiston Respublikasi 2023-yilda 356071.4 mlrd. so'm"
3. Answer: "2023-yilda O'zbekistonda asosiy kapitalga o'zlashtirilgan investitsiyalar hajmi 356071.4 mlrd. so'mni tashkil etdi.

   ---
   Foydalanilgan ko'rsatkichlar:
   - SDMX ID 1326: Asosiy kapitalga o'zlashtirilgan investitsiyalar"

Workflow 5 (Methodology/classifier search):
User: "Qaysi ko'rsatkichlar SOATO klassifikatori ishlatadi?" or
      "Which indicators use live birth methodology?"
1. search_sdmx_metadata("SOATO classifier") → returns "SDMX IDs: 225, 226, 227"
2. Optionally get_sdmx_metadata() for details on each ID
3. Answer: Present the list of relevant indicators found through metadata search

   ---
   Foydalanilgan ko'rsatkichlar:
   - SDMX ID 225: Tug'ilganlar soni (o'g'il bolalar)
   - SDMX ID 226: ...

Workflow 6 (Asking about specific SDMX ID):
User: "SDMX ID 224 nima haqida?" or "What is SDMX ID 224 about?"
1. get_sdmx_metadata(224) → returns indicator name, unit, periodicity
2. Answer: "SDMX ID 224: Tug'ilganlar soni (qiz bolalar), O'lchov: kishi, Davr: yillik"

   ---
   Foydalanilgan ko'rsatkichlar:
   - SDMX ID 224: Tug'ilganlar soni (qiz bolalar)

Workflow 7 (Counting reports in a category):
User: "30 yillik iqtisodiy makro-ko'rsatkichlar nechta hisobot bor?"
1. count_reports_for_category("30 yillik iqtisodiy makro-ko'rsatkichlar") → returns count details
2. Answer: Present the number of reports (15 ta) with category details and breakdown by subcategories

Important:
- Always use the EXACT unit returned by get_sdmx_value tool (kishi, mlrd. so'm, mln so'm, etc.)
- Always include the reference list at the end of every response that uses SDMX data
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


async def run_agent_async(agent, question: str, system_prompt: str = None, tools_map: dict = None) -> str:
    """
    Run the agent asynchronously with a question.

    Args:
        agent: The compiled agent
        question: User's question
        system_prompt: Optional system prompt
        tools_map: Optional map of tool names to tool functions (for XML fallback)

    Returns:
        Agent's response
    """
    logger.info(f"Running agent async with question: {question[:100]}...")
    config = {"configurable": {"thread_id": "1"}}

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


def run_agent(agent, question: str, system_prompt: str = None, tools_map: dict = None) -> str:
    """
    Run the agent synchronously with a question.

    Args:
        agent: The compiled agent
        question: User's question
        system_prompt: Optional system prompt
        tools_map: Optional map of tool names to tool functions (for XML fallback)

    Returns:
        Agent's response
    """
    logger.info(f"Running agent sync with question: {question[:100]}...")
    config = {"configurable": {"thread_id": "1"}}

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


async def run_agent_async_stream(agent, question: str, system_prompt: str = None, tools_map: dict = None):
    """
    Run agent and yield intermediate tool calls as they happen.

    Args:
        agent: The compiled agent
        question: User's question
        system_prompt: Optional system prompt
        tools_map: Optional map of tool names to tool functions (for XML fallback)

    Yields:
        dict: Streaming messages with type, tool info, and results
    """
    logger.info(f"Running agent async with streaming for question: {question[:100]}...")
    config = {"configurable": {"thread_id": "1"}}

    try:
        # Build messages
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=question))

        # Invoke agent
        result = await agent.ainvoke({"messages": messages}, config=config)
        logger.info("Agent invocation completed")

        # Log the result structure
        if isinstance(result, dict) and "messages" in result:
            logger.info(f"Received {len(result['messages'])} messages from agent")
            for i, msg in enumerate(result["messages"]):
                msg_type = type(msg).__name__
                logger.debug(f"Message {i}: {msg_type}")
        else:
            logger.warning(f"Unexpected result type: {type(result)}")

        # Sanitize tool calls
        if isinstance(result, dict) and "messages" in result:
            sanitized = []
            for m in result["messages"]:
                try:
                    sanitized.append(_sanitize_tool_call_args(m))
                except (AttributeError, TypeError, ValueError) as e:
                    logger.warning(f"Failed to sanitize tool call args for message: {e}")
                    sanitized.append(m)
            result["messages"] = sanitized

        # Process messages sequentially and yield tool steps
        logger.info("Processing messages and streaming tool calls...")
        tool_call_count = 0
        tool_result_count = 0

        for message in result["messages"]:
            if isinstance(message, AIMessage):
                # Check for tool calls
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    for tool_call in message.tool_calls:
                        tool_call_count += 1
                        # Get tool name and args
                        tool_name = tool_call.get("name") if isinstance(tool_call, dict) else getattr(tool_call, "name", None)
                        tool_args = tool_call.get("args") if isinstance(tool_call, dict) else getattr(tool_call, "args", None)

                        logger.info(f"Tool call #{tool_call_count}: {tool_name}")
                        logger.debug(f"  Args: {tool_args}")

                        yield {
                            "type": "tool_start",
                            "tool_name": tool_name,
                            "tool_args": tool_args,
                            "timestamp": datetime.now().isoformat()
                        }

            elif isinstance(message, ToolMessage):
                tool_result_count += 1
                # Ensure content is string and handle edge cases
                tool_result = message.content

                # Defensive: ensure it's a string
                if not isinstance(tool_result, str):
                    logger.warning(f"ToolMessage.content is not string: {type(tool_result)}, converting...")
                    tool_result = str(tool_result)

                # Optional: Truncate extremely long results (10KB limit)
                max_length = 10000
                if len(tool_result) > max_length:
                    logger.warning(f"Tool result truncated from {len(tool_result)} to {max_length} chars")
                    tool_result = tool_result[:max_length] + "\n... (truncated)"

                logger.info(f"Tool result #{tool_result_count}: {len(tool_result)} chars")
                logger.debug(f"  Preview: {tool_result[:200]}...")

                yield {
                    "type": "tool_result",
                    "tool_result": tool_result,
                    "timestamp": datetime.now().isoformat()
                }

                for chart in pop_charts():
                    yield {
                        "type": "chart",
                        "chart_data": chart,
                        "timestamp": datetime.now().isoformat()
                    }

        logger.info(f"Streamed {tool_call_count} tool calls and {tool_result_count} tool results")

        # Send final response
        final_response = extract_final_response(result["messages"], tools_map)
        yield {
            "type": "response",
            "content": final_response,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error in agent streaming: {e}", exc_info=True)
        yield {
            "type": "error",
            "content": f"Error processing request: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }

