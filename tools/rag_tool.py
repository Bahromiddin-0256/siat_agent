"""
RAG-based SDMX ID Retriever Tool.

This tool uses vector embeddings and semantic search to find
relevant SDMX IDs based on user questions.
"""

from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_ollama import OllamaEmbeddings
from langchain_chroma.vectorstores import Chroma
from langchain_core.vectorstores import VectorStore

from core.settings import settings
from core.logger import setup_logger

logger = setup_logger(__name__)

# Global variable to store vector store
_vector_store: VectorStore | None = None


def initialize_rag_vectorstore(
    json_data: list[dict[str, Any]],
    persist_directory: str = None,
    embedding_model: str = None,
) -> VectorStore:
    """
    Initialize the RAG vector store from JSON data.

    Args:
        json_data: List of SDMX data items
        persist_directory: Directory to persist the vector store
        embedding_model: Ollama embedding model to use

    Returns:
        Initialized vector store
    """
    global _vector_store

    logger.info("Initializing RAG vector store")

    if persist_directory is None:
        persist_directory = str(settings.chroma_persist_dir)

    if embedding_model is None:
        embedding_model = settings.ollama_embedding_model

    logger.info(f"Using embedding model: {embedding_model}")

    # Create embeddings
    embeddings = OllamaEmbeddings(
        model=embedding_model,
        base_url=settings.ollama_base_url,
    )

    # Convert SDMX data to documents
    documents = []
    seen_ids = set()  # Track unique IDs to prevent duplicates

    def extract_documents(items: list[dict[str, Any]], path: list[str] = None):
        """Recursively extract documents from nested structure."""
        if path is None:
            path = []

        for item in items:
            # Only create documents for items with codes
            if item.get('code'):
                # Create a unique identifier
                item_id = item.get('id')
                item_code = item.get('code')

                # Skip if we've already processed this ID
                if item_id and item_id in seen_ids:
                    continue

                # Mark as seen
                if item_id:
                    seen_ids.add(item_id)

                # Combine all name fields for better searchability
                content_parts = []

                if item.get('name'):
                    content_parts.append(f"Name: {item['name']}")
                if item.get('name_en'):
                    content_parts.append(f"English: {item['name_en']}")
                if item.get('name_ru'):
                    content_parts.append(f"Russian: {item['name_ru']}")
                if item.get('name_uz'):
                    content_parts.append(f"Uzbek: {item['name_uz']}")

                # Add tags if available
                tags = item.get('tags', [])
                if tags:
                    content_parts.append(f"Tags: {', '.join(tags)}")

                # Add period and department info
                if item.get('period'):
                    content_parts.append(f"Period: {item['period']}")
                if item.get('department'):
                    content_parts.append(f"Department: {item['department']}")

                content = "\n".join(content_parts)

                # Create document with metadata
                doc = Document(
                    page_content=content,
                    metadata={
                        'id': str(item_id) if item_id else item_code,
                        'code': item_code,
                        'name': item.get('name'),
                        'name_en': item.get('name_en'),
                        'name_ru': item.get('name_ru'),
                        'period': item.get('period'),
                        'department': item.get('department'),
                        'status': item.get('status'),
                        'path': ' > '.join(path + [item.get('name', '')]),
                    }
                )
                documents.append(doc)

            # Recursively process children
            children = item.get('children', [])
            if children:
                current_path = path + [item.get('name', 'Unknown')]
                extract_documents(children, current_path)

    # Create or load vector store
    persist_path = Path(persist_directory)

    # Check if vector store already exists - load it instead of recreating
    if persist_path.exists() and (persist_path / "chroma.sqlite3").exists():
        logger.info("Loading existing vector store from disk")
        _vector_store = Chroma(
            persist_directory=str(persist_path),
            embedding_function=embeddings,
        )
        logger.info(f"Vector store loaded successfully")
        return _vector_store

    # Extract all documents only if we need to create a new vector store
    logger.info("Creating new vector store (this may take a while)...")
    extract_documents(json_data)
    logger.info(f"Extracted {len(documents)} documents from SDMX data")

    # Generate unique IDs for each document to prevent duplicates
    ids = [f"sdmx_{doc.metadata.get('id', doc.metadata.get('code', i))}"
           for i, doc in enumerate(documents)]

    # Create fresh vector store with current data
    _vector_store = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=str(persist_path),
        ids=ids,
    )
    logger.info("Vector store created and persisted successfully")

    return _vector_store


def get_vectorstore() -> VectorStore | None:
    """Get the initialized vector store."""
    return _vector_store


def rebuild_vectorstore(
    json_data: list[dict[str, Any]],
    persist_directory: str = None,
    embedding_model: str = None,
) -> VectorStore:
    """
    Force rebuild the vector store (use when JSON data has changed).

    This deletes the existing vector store and creates a new one.
    """
    import shutil

    if persist_directory is None:
        persist_directory = str(settings.chroma_persist_dir)

    persist_path = Path(persist_directory)

    # Remove existing vector store
    if persist_path.exists():
        logger.info(f"Removing existing vector store at {persist_path}")
        shutil.rmtree(persist_path)

    # Reinitialize
    logger.info("Reinitializing vector store with new data")
    return initialize_rag_vectorstore(json_data, persist_directory, embedding_model)


# --- Tool argument schemas (Groq can validate strictly) ---
try:
    # Pydantic v2
    from pydantic import BaseModel, Field
    from typing import Union

    class _SemanticSearchArgs(BaseModel):
        question: str = Field(..., description="A question about statistics")
        k: Union[int, str] = Field(
            10,
            description="Number of results to return (int or a digit-string, e.g. 10 or '10')",
        )

    class _SearchWithScoreArgs(BaseModel):
        question: str = Field(..., description="A question about statistics")
        k: Union[int, str] = Field(
            10,
            description="Number of results to return (int or a digit-string)",
        )
        score_threshold: Union[float, str] = Field(
            0.7,
            description="Minimum similarity score (0-1). May be a float or a numeric string.",
        )

except (ImportError, AttributeError) as e:  # pragma: no cover
    logger.warning(f"Failed to create Pydantic argument schemas: {e}")
    _SemanticSearchArgs = None
    _SearchWithScoreArgs = None


@tool(args_schema=_SemanticSearchArgs) if _SemanticSearchArgs else tool
def search_sdmx_semantic(question: str, k: int = 10) -> str:
    """
    Search for SDMX IDs using semantic similarity (RAG-based).

    This tool uses vector embeddings to find statistically relevant indicators
    based on semantic meaning, not just keyword matching. Best for complex
    or nuanced questions about statistics.

    Args:
        question: A question about statistics
        k: Number of results to return (default: 10)

    Returns:
        Formatted string with matching SDMX IDs and their details
    """
    if _vector_store is None:
        return "Error: RAG vector store not initialized. Call initialize_rag_vectorstore first."

    # Defensive coercion: some models send tool args as strings (e.g., {"k": "10"}).
    try:
        if isinstance(k, str):
            k = int(k)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid k parameter '{k}', defaulting to 10: {e}")
        k = 10

    # Bound k to safe limits
    if k <= 0:
        k = 10
    if k > 50:
        k = 50

    # Perform semantic search
    results = _vector_store.similarity_search(question, k=k)

    if not results:
        return f"No matching SDMX IDs found for: '{question}'"

    # Format output
    output_lines = [f"Found {len(results)} semantically similar indicator(s):\n"]

    for idx, doc in enumerate(results, 1):
        metadata = doc.metadata
        output_lines.append(f"{idx}. **ID**: {metadata.get('id')}")
        output_lines.append(f"   **Code**: {metadata.get('code')}")
        output_lines.append(f"   **Name**: {metadata.get('name')}")
        if metadata.get('name_en'):
            output_lines.append(f"   **English**: {metadata.get('name_en')}")
        if metadata.get('period'):
            output_lines.append(f"   **Period**: {metadata.get('period')}")
        if metadata.get('status'):
            output_lines.append(f"   **Status**: {metadata.get('status')}")
        if metadata.get('path'):
            output_lines.append(f"   **Category Path**: {metadata.get('path')}")
        output_lines.append("")

    return "\n".join(output_lines)


@tool(args_schema=_SearchWithScoreArgs) if _SearchWithScoreArgs else tool
def search_sdmx_with_score(question: str, k: int = 10, score_threshold: float = 0.7) -> str:
    """Search for SDMX IDs with similarity scores."""
    if _vector_store is None:
        return "Error: RAG vector store not initialized. Call initialize_rag_vectorstore first."

    # Defensive coercion for tool-call args
    try:
        if isinstance(k, str):
            k = int(k)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid k parameter '{k}', defaulting to 10: {e}")
        k = 10

    try:
        if isinstance(score_threshold, str):
            score_threshold = float(score_threshold)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid score_threshold '{score_threshold}', defaulting to 0.7: {e}")
        score_threshold = 0.7

    if k <= 0:
        k = 10
    if k > 50:
        k = 50

    # Clamp threshold
    if score_threshold <= 0 or score_threshold > 1:
        score_threshold = 0.7

    # Perform similarity search with scores
    results = _vector_store.similarity_search_with_score(question, k=k)

    # Filter by score threshold
    filtered_results = [(doc, score) for doc, score in results if score <= (1 - score_threshold)]

    if not filtered_results:
        return f"No matching SDMX IDs found above threshold {score_threshold} for: '{question}'"

    # Format output
    output_lines = [
        f"Found {len(filtered_results)} indicator(s) above similarity threshold {score_threshold}:\n"
    ]

    for idx, (doc, score) in enumerate(filtered_results, 1):
        metadata = doc.metadata
        relevance = 1 - score  # Convert distance to similarity
        output_lines.append(f"{idx}. **Relevance**: {relevance:.2%}")
        output_lines.append(f"   **ID**: {metadata.get('id')}")
        output_lines.append(f"   **Code**: {metadata.get('code')}")
        output_lines.append(f"   **Name**: {metadata.get('name')}")
        if metadata.get('name_en'):
            output_lines.append(f"   **English**: {metadata.get('name_en')}")
        if metadata.get('period'):
            output_lines.append(f"   **Period**: {metadata.get('period')}")
        output_lines.append("")

    return "\n".join(output_lines)
