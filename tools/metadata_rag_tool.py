"""
Metadata RAG-based SDMX Search Tool.

This tool uses vector embeddings and semantic search to find
SDMX IDs based on metadata fields including methodologies,
classifiers, legal references, and definitions.
"""

import json
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_ollama import OllamaEmbeddings
from langchain_chroma.vectorstores import Chroma
from langchain_core.vectorstores import VectorStore

from core.settings import settings, BASE_DIR
from core.logger import setup_logger

logger = setup_logger(__name__)

# Global variable to store metadata vector store
_metadata_vector_store: VectorStore | None = None


def extract_metadata_from_sdmx_files(base_dir: str = "jsons/sdmxs") -> list[Document]:
    """
    Extract metadata from all SDMX data files.

    Args:
        base_dir: Directory containing sdmx_data_*.json files

    Returns:
        List of LangChain documents for vector store
    """
    logger.info(f"Extracting metadata from SDMX files in {base_dir}")

    base_path = Path(base_dir)
    if not base_path.exists():
        logger.error(f"Directory {base_dir} does not exist")
        return []

    documents = []
    file_count = 0
    error_count = 0

    # Iterate through all sdmx_data_*.json files
    for file_path in sorted(base_path.glob("sdmx_data_*.json")):
        try:
            # Extract SDMX ID from filename
            filename = file_path.stem  # e.g., "sdmx_data_225"
            sdmx_id = int(filename.split("_")[-1])

            # Load JSON file
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Extract metadata array
            if not data or not isinstance(data, list) or len(data) == 0:
                logger.warning(f"Invalid data structure in {file_path}")
                error_count += 1
                continue

            metadata_array = data[0].get('metadata', [])
            if not metadata_array:
                logger.warning(f"No metadata found in {file_path}")
                error_count += 1
                continue

            # Parse metadata fields
            metadata_dict = {}
            for item in metadata_array:
                name_en = item.get('name_en', '').lower()
                metadata_dict[name_en] = item

            # Helper function to get metadata value
            def get_metadata_value(field_name: str, lang: str = 'uz') -> str:
                for item in metadata_array:
                    name_en = item.get('name_en', '').lower()
                    if field_name.lower() in name_en:
                        return item.get(f'value_{lang}', '') or ''
                return ''

            # Extract key fields
            dataset_name_uz = get_metadata_value('data set name', 'uz') or get_metadata_value('dataset name', 'uz')
            dataset_name_ru = get_metadata_value('data set name', 'ru') or get_metadata_value('dataset name', 'ru')
            dataset_name_en = get_metadata_value('data set name', 'en') or get_metadata_value('dataset name', 'en')

            methodology_uz = get_metadata_value('calculation methodology', 'uz')
            methodology_ru = get_metadata_value('calculation methodology', 'ru')
            methodology_en = get_metadata_value('calculation methodology', 'en')

            classifiers_uz = get_metadata_value('classifiers', 'uz')
            classifiers_ru = get_metadata_value('classifiers', 'ru')
            classifiers_en = get_metadata_value('classifiers', 'en')

            note_uz = get_metadata_value('note', 'uz')
            note_ru = get_metadata_value('note', 'ru')
            note_en = get_metadata_value('note', 'en')

            source_uz = get_metadata_value('primary', 'uz')
            source_ru = get_metadata_value('primary', 'ru')
            source_en = get_metadata_value('primary', 'en')

            code = get_metadata_value('code', 'uz') or get_metadata_value('identification', 'uz')
            unit_uz = get_metadata_value('unit', 'uz')
            department_uz = get_metadata_value('department', 'uz')
            periodicity_uz = get_metadata_value('periodicity', 'uz')

            # Build searchable content
            content_parts = []

            if dataset_name_uz or dataset_name_ru or dataset_name_en:
                content_parts.append(f"Dataset: {dataset_name_uz} / {dataset_name_ru} / {dataset_name_en}")

            if methodology_uz or methodology_ru or methodology_en:
                # Use excerpts for long methodology fields (first 500 chars)
                method_uz_excerpt = methodology_uz[:500] if len(methodology_uz) > 500 else methodology_uz
                method_ru_excerpt = methodology_ru[:500] if len(methodology_ru) > 500 else methodology_ru
                method_en_excerpt = methodology_en[:500] if len(methodology_en) > 500 else methodology_en
                content_parts.append(f"Methodology: {method_uz_excerpt} / {method_ru_excerpt} / {method_en_excerpt}")

            if classifiers_uz or classifiers_ru or classifiers_en:
                content_parts.append(f"Classifiers: {classifiers_uz} / {classifiers_ru} / {classifiers_en}")

            if note_uz or note_ru or note_en:
                # Use excerpts for long note fields (first 300 chars)
                note_uz_excerpt = note_uz[:300] if len(note_uz) > 300 else note_uz
                note_ru_excerpt = note_ru[:300] if len(note_ru) > 300 else note_ru
                note_en_excerpt = note_en[:300] if len(note_en) > 300 else note_en
                content_parts.append(f"Note: {note_uz_excerpt} / {note_ru_excerpt} / {note_en_excerpt}")

            if source_uz or source_ru or source_en:
                content_parts.append(f"Source: {source_uz} / {source_ru} / {source_en}")

            # Create document
            page_content = "\n\n".join(content_parts)

            doc = Document(
                page_content=page_content,
                metadata={
                    'sdmx_id': sdmx_id,
                    'code': code,
                    'name_uz': dataset_name_uz,
                    'name_ru': dataset_name_ru,
                    'name_en': dataset_name_en,
                    'methodology_uz': methodology_uz,
                    'methodology_ru': methodology_ru,
                    'methodology_en': methodology_en,
                    'classifiers_uz': classifiers_uz,
                    'classifiers_ru': classifiers_ru,
                    'classifiers_en': classifiers_en,
                    'note_uz': note_uz,
                    'note_ru': note_ru,
                    'note_en': note_en,
                    'source_uz': source_uz,
                    'source_ru': source_ru,
                    'source_en': source_en,
                    'unit_uz': unit_uz,
                    'department_uz': department_uz,
                    'periodicity_uz': periodicity_uz,
                }
            )

            documents.append(doc)
            file_count += 1

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            error_count += 1
            continue

    logger.info(f"Extracted metadata from {file_count} files ({error_count} errors)")
    return documents


def initialize_metadata_vectorstore(
    base_dir: str = "jsons/sdmxs",
    persist_directory: str = None,
    embedding_model: str = None,
) -> VectorStore:
    """
    Initialize the metadata RAG vector store from SDMX data files.

    Args:
        base_dir: Directory containing sdmx_data_*.json files
        persist_directory: Directory to persist the vector store
        embedding_model: Ollama embedding model to use

    Returns:
        Initialized vector store
    """
    global _metadata_vector_store

    logger.info("Initializing metadata RAG vector store")

    if persist_directory is None:
        persist_directory = str(BASE_DIR / "metadata_chroma_db")

    if embedding_model is None:
        embedding_model = settings.ollama_embedding_model

    logger.info(f"Using embedding model: {embedding_model}")

    # Create embeddings
    embeddings = OllamaEmbeddings(
        model=embedding_model,
        base_url=settings.ollama_base_url,
    )

    persist_path = Path(persist_directory)

    # Check if vector store already exists - load it instead of recreating
    if persist_path.exists() and (persist_path / "chroma.sqlite3").exists():
        logger.info("Loading existing metadata vector store from disk")
        _metadata_vector_store = Chroma(
            persist_directory=str(persist_path),
            embedding_function=embeddings,
            collection_name="sdmx_metadata",
        )
        logger.info(f"Metadata vector store loaded successfully")
        return _metadata_vector_store

    # Extract metadata from all files
    logger.info("Creating new metadata vector store (this may take a while)...")
    documents = extract_metadata_from_sdmx_files(base_dir)

    if not documents:
        logger.error("No documents extracted, cannot create vector store")
        return None

    logger.info(f"Extracted {len(documents)} metadata documents")

    # Generate unique IDs for each document
    ids = [f"sdmx_metadata_{doc.metadata['sdmx_id']}" for doc in documents]

    # Create fresh vector store with current data
    _metadata_vector_store = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=str(persist_path),
        collection_name="sdmx_metadata",
        ids=ids,
    )
    logger.info("Metadata vector store created and persisted successfully")

    return _metadata_vector_store


def get_metadata_vectorstore() -> VectorStore | None:
    """Get the initialized metadata vector store."""
    return _metadata_vector_store


def rebuild_metadata_vectorstore(
    base_dir: str = "jsons/sdmxs",
    persist_directory: str = None,
    embedding_model: str = None,
) -> VectorStore:
    """
    Force rebuild the metadata vector store (use when SDMX data has changed).

    This deletes the existing vector store and creates a new one.

    Args:
        base_dir: Directory containing sdmx_data_*.json files
        persist_directory: Directory to persist the vector store
        embedding_model: Ollama embedding model to use

    Returns:
        Rebuilt vector store
    """
    import shutil

    if persist_directory is None:
        persist_directory = str(settings.BASE_DIR / "metadata_chroma_db")

    persist_path = Path(persist_directory)

    # Remove existing vector store
    if persist_path.exists():
        logger.info(f"Removing existing metadata vector store at {persist_path}")
        shutil.rmtree(persist_path)

    # Reinitialize
    logger.info("Reinitializing metadata vector store with new data")
    return initialize_metadata_vectorstore(base_dir, persist_directory, embedding_model)


# --- Tool argument schemas ---
try:
    from pydantic import BaseModel, Field
    from typing import Union

    class _MetadataSearchArgs(BaseModel):
        question: str = Field(..., description="Search query about methodology, classifiers, or legal framework")
        k: Union[int, str] = Field(
            10,
            description="Number of results to return (int or digit-string, e.g. 10 or '10')",
        )

except (ImportError, AttributeError) as e:
    logger.warning(f"Failed to create Pydantic argument schemas: {e}")
    _MetadataSearchArgs = None


@tool(args_schema=_MetadataSearchArgs) if _MetadataSearchArgs else tool
def search_sdmx_metadata(question: str, k: int = 10) -> str:
    """
    Search SDMX metadata using semantic search on methodologies, definitions,
    legal references, and classification systems.

    Use this tool to find SDMX IDs based on:
    - Calculation methodologies and definitions
    - Legal frameworks and regulatory references
    - Classification systems and criteria (e.g., SOATO, OKVED)
    - Methodological documentation

    Args:
        question: Search query about methodology, definitions, or legal framework
        k: Number of results to return (default: 10)

    Returns:
        Comma-separated list of SDMX IDs

    Example:
        search_sdmx_metadata("indicators using SOATO classifier")
        Returns: "SDMX IDs: 225, 226, 227, 228, 229"
    """
    if _metadata_vector_store is None:
        return "Error: Metadata vector store not initialized. Call initialize_metadata_vectorstore first."

    # Defensive coercion: some models send tool args as strings
    try:
        if isinstance(k, str):
            k = int(k)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid k parameter '{k}', defaulting to 10: {e}")
        k = 10

    # Bound k to safe limits
    k = max(1, min(k, 20))

    # Perform semantic search
    logger.info(f"Searching metadata for: '{question}' (k={k})")
    results = _metadata_vector_store.similarity_search(question, k=k)

    if not results:
        return f"No matching SDMX IDs found for: '{question}'"

    # Extract SDMX IDs
    sdmx_ids = [doc.metadata['sdmx_id'] for doc in results]

    # Return simple comma-separated list
    return f"SDMX IDs: {', '.join(map(str, sdmx_ids))}"
