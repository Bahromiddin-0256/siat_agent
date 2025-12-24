"""
SDMX ID Retriever Agent - Main Entry Point.

This script demonstrates how to use the SDMX agent with Ollama to find
statistical indicator IDs based on user questions using RAG and semantic search.
"""

from pathlib import Path

from core.settings import settings
from tools import (
    initialize_sdmx_data,
    get_sdmx_id,
    initialize_rag_vectorstore,
    search_sdmx_semantic,
)
from core.agent import create_sdmx_agent, run_agent


def load_and_initialize_data(json_path: Path):
    """Load SDMX data and initialize both keyword and RAG search."""
    print(f"Loading SDMX data from: {json_path}")

    # Initialize keyword-based search
    data = initialize_sdmx_data(json_path)
    print("SDMX data loaded successfully!")

    # Initialize RAG vector store
    print("Initializing RAG vector store with embeddings...")
    from tools.sdmx_tool import _json_data
    initialize_rag_vectorstore(_json_data)
    print("RAG vector store initialized successfully!\n")

    return data


def main():
    """Main entry point for the SDMX agent."""
    # Initialize the SDMX data and RAG vector store
    json_path = Path(__file__).parent / "jsons" / "main.json"
    load_and_initialize_data(json_path)

    # Example 1: Direct keyword-based search (without LLM)
    print("=" * 60)
    print("Example 1: Keyword-Based Search (No LLM)")
    print("=" * 60)
    result = get_sdmx_id.invoke({"question": "GDP gross domestic product"})
    print(result)
    print()

    # Example 2: RAG-based semantic search (without LLM agent)
    print("=" * 60)
    print("Example 2: RAG Semantic Search (No LLM)")
    print("=" * 60)
    result = search_sdmx_semantic.invoke({"question": "economic growth indicators"})
    print(result)
    print()

    # Example 3: Using the LangGraph agent with Ollama
    # Check if Ollama is available
    print("=" * 60)
    print("Example 3: LangGraph Agent with Ollama")
    print("=" * 60)

    # Create the agent (will use Ollama)
    agent, system_prompt = create_sdmx_agent()

    # Ask questions
    questions = [
        "What is the SDMX ID for quarterly GDP data?",
        "Find indicators related to population statistics",
        "Show me export and import indicators",
    ]

    for question in questions:
        print(f"\nQuestion: {question}")
        print("-" * 40)
        response = run_agent(agent, question, system_prompt)
        print(response)
        print()



def interactive_mode():
    """Run the agent in interactive mode."""
    # Initialize data
    json_path = Path(__file__).parent / "jsons" / "main.json"
    load_and_initialize_data(json_path)

    print("SDMX ID Retriever - Interactive Mode")
    print("Type 'quit' to exit")
    print("Commands: 'keyword <query>' for keyword search, 'semantic <query>' for RAG search")
    print("Or just type your question to use the LangGraph agent\n")

    # Try to create the agent
    use_agent = False
    agent = None
    system_prompt = None
    try:
        agent, system_prompt = create_sdmx_agent()
        use_agent = True
        print("Using LangGraph agent with Ollama")
        print(f"Model: {settings.ollama_model}\n")
    except Exception as e:
        print(f"Could not connect to Ollama: {e}")
        print("Falling back to direct semantic search mode\n")

    while True:
        try:
            question = input("Enter your question: ").strip()

            if question.lower() in ('quit', 'exit', 'q'):
                print("Goodbye!")
                break

            if not question:
                continue

            # Handle explicit commands
            if question.lower().startswith('keyword '):
                query = question[8:].strip()
                response = get_sdmx_id.invoke({"question": query})
            elif question.lower().startswith('semantic '):
                query = question[9:].strip()
                response = search_sdmx_semantic.invoke({"question": query})
            elif use_agent:
                # Use the agent
                response = run_agent(agent, question, system_prompt)
            else:
                # Fallback to semantic search
                response = search_sdmx_semantic.invoke({"question": question})

            print("\n" + response + "\n")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--interactive':
        interactive_mode()
    else:
        main()

