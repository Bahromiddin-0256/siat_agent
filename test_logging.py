#!/usr/bin/env python3
"""Test script to demonstrate improved logging."""

import logging
import sys

# Set up logging to show all levels
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

from core.agent import create_sdmx_agent, run_agent

# Create agent
print("="*80)
print("Creating SDMX agent...")
print("="*80)
agent, system_prompt = create_sdmx_agent()

# Test question
question = "30 yillik iqtisodiy makro-ko'rsatkichlar nechta hisobot bor?"

print("\n" + "="*80)
print(f"Testing question: {question}")
print("="*80 + "\n")

# Run agent with logging
response = run_agent(agent, question, system_prompt)

print("\n" + "="*80)
print("FINAL RESPONSE:")
print("="*80)
print(response)
print("="*80)
