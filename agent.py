"""
SDMX Agent using LangGraph.

This module implements a ReAct agent that can search for SDMX IDs
based on user questions using LangGraph's prebuilt agent with Ollama.
"""

import os
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from langgraph.graph.message import add_messages

from tools import (
    get_sdmx_id,
    get_sdmx_by_code,
    list_sdmx_categories,
    search_sdmx_semantic,
    search_sdmx_with_score,
)


class AgentState(TypedDict):
    """State for the SDMX agent."""
    messages: Annotated[list[BaseMessage], add_messages]


def create_sdmx_agent(
    model_name: str = None,
    temperature: float = 0,
    base_url: str = None,
) -> Any:
    """
    Create an SDMX agent using LangGraph's prebuilt ReAct agent with Ollama.

    Args:
        model_name: The Ollama model to use (default: from env or "llama3.2")
        temperature: Temperature for the model
        base_url: Ollama base URL (default: from env or "http://localhost:11434")

    Returns:
        A compiled LangGraph agent
    """
    # Get configuration from environment or use defaults
    if model_name is None:
        model_name = os.getenv("OLLAMA_MODEL", "llama3.2")
    if base_url is None:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Initialize the LLM with Ollama
    llm = ChatOllama(
        model=model_name,
        temperature=temperature,
        base_url=base_url,
    )

    # Define the tools
    tools = [
        search_sdmx_semantic,  # RAG-based semantic search (primary)
        search_sdmx_with_score,  # RAG search with relevance scores
        get_sdmx_id,  # Keyword-based search (fallback)
        get_sdmx_by_code,  # Get by specific code
        list_sdmx_categories,  # Browse categories
    ]

    # System prompt for the agent
    system_prompt = """You are a helpful assistant specialized in finding statistical data identifiers (SDMX IDs).

You have access to a database of statistical indicators from Uzbekistan's statistics agency.
The data includes economic statistics, social statistics, demographic data, and more.

Available tools:
1. **search_sdmx_semantic**: Use this FIRST for natural language questions. It uses AI embeddings
   to find semantically similar indicators, even if exact keywords don't match.
2. **search_sdmx_with_score**: Like semantic search but shows relevance scores. Use when you want
   to see how confident the matches are.
3. **get_sdmx_id**: Keyword-based search. Use as fallback if semantic search doesn't work well.
4. **get_sdmx_by_code**: Use when the user provides a specific SDMX code.
5. **list_sdmx_categories**: Use to browse available statistical domains.

Best practices:
- Start with semantic search (search_sdmx_semantic) for most questions
- Use keyword search (get_sdmx_id) if semantic search returns poor results
- Always provide clear, helpful responses with SDMX IDs and descriptions
- If multiple results are found, help the user identify the most relevant one

You can understand questions in English, Russian, and Uzbek."""

    # Create the ReAct agent
    agent = create_react_agent(
        model=llm,
        tools=tools,
        messages_modifier=system_prompt,
    )

    return agent


async def run_agent_async(agent, question: str) -> str:
    """
    Run the agent asynchronously with a question.

    Args:
        agent: The compiled agent
        question: User's question

    Returns:
        Agent's response
    """
    config = {"configurable": {"thread_id": "1"}}

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=question)]},
        config=config,
    )

    # Get the last AI message
    for message in reversed(result["messages"]):
        if isinstance(message, AIMessage) and message.content:
            return message.content

    return "No response generated."


def run_agent(agent, question: str) -> str:
    """
    Run the agent synchronously with a question.

    Args:
        agent: The compiled agent
        question: User's question

    Returns:
        Agent's response
    """
    config = {"configurable": {"thread_id": "1"}}

    result = agent.invoke(
        {"messages": [HumanMessage(content=question)]},
        config=config,
    )

    # Get the last AI message
    for message in reversed(result["messages"]):
        if isinstance(message, AIMessage) and message.content:
            return message.content

    return "No response generated."

