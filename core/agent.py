"""
SDMX Agent using LangGraph.

This module implements a ReAct agent that can search for SDMX IDs
based on user questions using LangGraph's prebuilt agent with Ollama.
"""
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage
from langchain.agents import create_agent
from langgraph.graph.message import add_messages

from .llm import base_llm, _sanitize_tool_call_args
from .logger import setup_logger

logger = setup_logger(__name__)
from tools import (
    get_sdmx_id,
    get_sdmx_by_code,
    list_sdmx_categories,
    search_sdmx_semantic,
    search_sdmx_with_score,
    get_sdmx_value,
    get_sdmx_metadata,
    calculate_yearly_growth,
)


class AgentState(TypedDict):
    """State for the SDMX agent."""
    messages: Annotated[list[BaseMessage], add_messages]


def create_sdmx_agent(
) -> tuple[Any, str]:
    """
    Create an SDMX agent using LangGraph's prebuilt ReAct agent with Ollama.

    Args:

    Returns:
        A tuple of (compiled LangGraph agent, system prompt)
    """
    # Get configuration from environment or use defaults


    # Define the tools
    tools = [
        search_sdmx_semantic,  # RAG-based semantic search (primary)
        search_sdmx_with_score,  # RAG search with relevance scores
        get_sdmx_id,  # Keyword-based search (fallback)
        get_sdmx_by_code,  # Get by specific code
        list_sdmx_categories,  # Browse categories
        get_sdmx_value,  # Extract actual data values
        get_sdmx_metadata,  # Get indicator metadata
        calculate_yearly_growth,  # Calculate year-over-year growth rates
    ]

    # System prompt for the agent
    system_prompt = """You are a helpful assistant specialized in finding statistical data identifiers (SDMX IDs) and extracting actual statistical values.

You have access to a database of statistical indicators from Uzbekistan's statistics agency.
The data includes economic statistics, social statistics, demographic data, and more.

Available tools:
1. **search_sdmx_semantic**: Use this FIRST for finding indicators. It uses AI embeddings
   to find semantically similar indicators, even if exact keywords don't match.
2. **search_sdmx_with_score**: Like semantic search but shows relevance scores.
3. **get_sdmx_id**: Keyword-based search. Use as fallback if semantic search doesn't work well.
4. **get_sdmx_by_code**: Use when the user provides a specific SDMX code.
5. **list_sdmx_categories**: Use to browse available statistical domains.
6. **get_sdmx_value**: Use this to extract ACTUAL DATA VALUES after finding the SDMX ID.
   Required when user asks "how many", "what is the value", specific numbers, etc.
7. **get_sdmx_metadata**: Get minimal metadata about an indicator (unit, period, department).
8. **calculate_yearly_growth**: Use this to calculate YEAR-OVER-YEAR GROWTH PERCENTAGES.
   Required when user asks for "o'sish foizi", "growth rate", "percentage change", "trend" over time.

Best practices:
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

Important:
- Always use the EXACT unit returned by get_sdmx_value tool (kishi, mlrd. so'm, mln so'm, etc.)
- Always include the reference list at the end of every response that uses SDMX data
"""

    # Create the ReAct agent
    logger.info("Creating SDMX ReAct agent with tools")
    agent = create_agent(base_llm, tools)
    logger.info(f"SDMX agent created successfully with {len(tools)} tools")

    return agent, system_prompt


async def run_agent_async(agent, question: str, system_prompt: str = None) -> str:
    """
    Run the agent asynchronously with a question.

    Args:
        agent: The compiled agent
        question: User's question
        system_prompt: Optional system prompt

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
    logger.debug("Agent invocation completed")

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

    # Get the last AI message with actual response content
    for message in reversed(result["messages"]):
        if isinstance(message, AIMessage):
            # Skip messages that only contain tool calls without text content
            if hasattr(message, 'tool_calls') and message.tool_calls:
                if not message.content or not str(message.content).strip():
                    continue

            # Return string content if it's meaningful
            if message.content:
                content_str = str(message.content).strip()
                # Skip if it looks like a JSON tool call representation
                if content_str and not (content_str.startswith('{') or content_str.startswith('[')):
                    return content_str
                # Accept longer JSON responses (actual content, not tool calls)
                if len(content_str) > 200:
                    return content_str

    return "No response generated."


def run_agent(agent, question: str, system_prompt: str = None) -> str:
    """
    Run the agent synchronously with a question.

    Args:
        agent: The compiled agent
        question: User's question
        system_prompt: Optional system prompt

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
    logger.debug("Agent invocation completed")

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

    # ...existing code scanning for last AIMessage...

    for message in reversed(result["messages"]):
        if isinstance(message, AIMessage):
            # Skip messages that only contain tool calls without text content
            if hasattr(message, 'tool_calls') and message.tool_calls:
                if not message.content or not str(message.content).strip():
                    continue

            # Return string content if it's meaningful
            if message.content:
                content_str = str(message.content).strip()
                # Skip if it looks like a JSON tool call representation
                if content_str and not (content_str.startswith('{') or content_str.startswith('[')):
                    return content_str
                # Accept longer JSON responses (actual content, not tool calls)
                if len(content_str) > 200:
                    return content_str

    # Get the last AI message with actual response content
    return "No response generated."

