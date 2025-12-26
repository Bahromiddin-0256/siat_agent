#!/usr/bin/env python3
"""Test script for SDMX Agent with birth statistics question."""

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.agent import create_sdmx_agent, run_agent_async
from tools import initialize_sdmx_data, initialize_rag_vectorstore

async def test_birth_statistics():
    """Test the agent with the birth statistics question."""

    # Initialize data
    json_file = Path("jsons/main.json")
    print("Initializing SDMX data...")
    initialize_sdmx_data(json_file)

    print("Initializing RAG vectorstore...")
    from tools import sdmx_tool
    initialize_rag_vectorstore(sdmx_tool._json_data)

    # Create agent
    print("Creating agent...")
    agent, system_prompt = create_sdmx_agent()

    # Test question
    question = "2013-yil Andijon viloyatida nechta bola tu'gilgan"
    expected_answer = "Andijon viloyatida 2013-yil 64239 ta bola tu'gilgan"

    print(f"\n{'='*70}")
    print(f"Question: {question}")
    print(f"Expected: {expected_answer}")
    print(f"{'='*70}\n")

    # Run agent
    print("Running agent...\n")
    response = await run_agent_async(agent, question, system_prompt)

    print(f"\n{'='*70}")
    print(f"Agent Response:")
    print(f"{'='*70}")
    print(response)
    print(f"{'='*70}\n")

    # Check if response contains the expected number
    if "64239" in response and "Andijon" in response and "2013" in response:
        print("✅ TEST PASSED: Response contains correct data!")
    else:
        print("❌ TEST FAILED: Response does not match expected answer")

    return response


if __name__ == "__main__":
    asyncio.run(test_birth_statistics())
