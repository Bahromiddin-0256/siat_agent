"""
Test script to debug the agent response.
"""
import asyncio
from pathlib import Path
from tools import initialize_sdmx_data, initialize_rag_vectorstore
from tools import sdmx_tool
from core.agent import create_sdmx_agent, run_agent_async


async def test():
    # Initialize data
    json_path = Path(__file__).parent / "jsons" / "main.json"
    initialize_sdmx_data(json_path)
    initialize_rag_vectorstore(sdmx_tool._json_data)

    # Create agent
    agent, system_prompt = create_sdmx_agent()

    # Test question
    question = "What is the SDMX ID for GDP data?"
    print(f"Question: {question}\n")

    # Run agent and get full result
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=question))

    result = await agent.ainvoke(
        {"messages": messages},
        config={"configurable": {"thread_id": "1"}},
    )

    print("All messages in result:")
    print("=" * 80)
    for i, msg in enumerate(result["messages"]):
        print(f"\nMessage {i}: {type(msg).__name__}")
        print(f"Content: {msg.content}")
        if hasattr(msg, 'tool_calls'):
            print(f"Tool calls: {msg.tool_calls}")
        print("-" * 80)

    # Try to get response
    response = await run_agent_async(agent, question, system_prompt)
    print(f"\nExtracted response: {response}")

if __name__ == "__main__":
    asyncio.run(test())
