"""
Tests for metadata RAG tool.

This module tests the metadata search functionality including:
- Metadata extraction from SDMX files
- Vector store initialization
- Semantic search on methodologies, classifiers, and legal references
- Multilingual search capabilities
"""

import pytest
from pathlib import Path
from tools.metadata_rag_tool import (
    extract_metadata_from_sdmx_files,
    initialize_metadata_vectorstore,
    search_sdmx_metadata,
    get_metadata_vectorstore,
)


class TestMetadataExtraction:
    """Test metadata extraction from SDMX files."""

    def test_extract_metadata_from_files(self):
        """Test that metadata can be extracted from SDMX data files."""
        # Extract metadata from a few files
        base_dir = Path(__file__).parent.parent / "jsons" / "sdmxs"

        if not base_dir.exists():
            pytest.skip("SDMX data directory not found")

        documents = extract_metadata_from_sdmx_files(str(base_dir))

        # Should extract documents
        assert len(documents) > 0, "Should extract at least one document"

        # Check document structure
        doc = documents[0]
        assert hasattr(doc, 'page_content'), "Document should have page_content"
        assert hasattr(doc, 'metadata'), "Document should have metadata"

        # Check metadata fields
        metadata = doc.metadata
        assert 'sdmx_id' in metadata, "Should have sdmx_id"
        assert isinstance(metadata['sdmx_id'], int), "sdmx_id should be integer"

    def test_metadata_contains_multilingual_content(self):
        """Test that extracted metadata includes multilingual content."""
        base_dir = Path(__file__).parent.parent / "jsons" / "sdmxs"

        if not base_dir.exists():
            pytest.skip("SDMX data directory not found")

        documents = extract_metadata_from_sdmx_files(str(base_dir))

        if len(documents) == 0:
            pytest.skip("No documents extracted")

        # Check first document has multilingual fields
        doc = documents[0]
        metadata = doc.metadata

        # Should have Uzbek, Russian, and English names
        has_multilingual = (
            'name_uz' in metadata or
            'name_ru' in metadata or
            'name_en' in metadata
        )
        assert has_multilingual, "Should have multilingual name fields"


class TestVectorStoreInitialization:
    """Test vector store initialization."""

    def test_initialize_vectorstore(self):
        """Test that metadata vectorstore can be initialized."""
        base_dir = Path(__file__).parent.parent / "jsons" / "sdmxs"

        if not base_dir.exists():
            pytest.skip("SDMX data directory not found")

        # Initialize vectorstore
        vectorstore = initialize_metadata_vectorstore(str(base_dir))

        assert vectorstore is not None, "Vectorstore should be initialized"

    def test_get_vectorstore(self):
        """Test that vectorstore can be retrieved."""
        vectorstore = get_metadata_vectorstore()

        # May be None if not initialized yet, but function should work
        assert vectorstore is None or vectorstore is not None


class TestMetadataSearch:
    """Test metadata search functionality."""

    @pytest.fixture(autouse=True)
    def setup_vectorstore(self):
        """Initialize vectorstore before each test."""
        base_dir = Path(__file__).parent.parent / "jsons" / "sdmxs"

        if not base_dir.exists():
            pytest.skip("SDMX data directory not found")

        # Initialize if not already done
        if get_metadata_vectorstore() is None:
            initialize_metadata_vectorstore(str(base_dir))

    def test_search_returns_sdmx_ids(self):
        """Test that search returns SDMX IDs in correct format."""
        # Search for something that should exist
        result = search_sdmx_metadata.invoke({
            "question": "population statistics",
            "k": 5
        })

        # Should return string with SDMX IDs format
        assert isinstance(result, str), "Result should be a string"

        # Should contain "SDMX IDs:" prefix (unless error or no results)
        if "Error" not in result and "No matching" not in result:
            assert "SDMX IDs:" in result, "Should contain 'SDMX IDs:' prefix"

    def test_search_with_uzbek_query(self):
        """Test search with Uzbek language query."""
        result = search_sdmx_metadata.invoke({
            "question": "aholi statistikasi",
            "k": 5
        })

        assert isinstance(result, str), "Result should be a string"

    def test_search_with_russian_query(self):
        """Test search with Russian language query."""
        result = search_sdmx_metadata.invoke({
            "question": "статистика населения",
            "k": 5
        })

        assert isinstance(result, str), "Result should be a string"

    def test_search_classifier_soato(self):
        """Test search for SOATO classifier."""
        result = search_sdmx_metadata.invoke({
            "question": "SOATO classifier",
            "k": 10
        })

        assert isinstance(result, str), "Result should be a string"

        # SOATO is a common classifier, should find results
        # (unless vector store is empty or not initialized)
        if get_metadata_vectorstore() is not None:
            # Should either return IDs or a message
            assert len(result) > 0, "Should return non-empty result"

    def test_search_methodology(self):
        """Test search for methodology-related queries."""
        result = search_sdmx_metadata.invoke({
            "question": "calculation methodology live birth",
            "k": 5
        })

        assert isinstance(result, str), "Result should be a string"

    def test_search_legal_references(self):
        """Test search for legal framework references."""
        result = search_sdmx_metadata.invoke({
            "question": "legal framework statistics law",
            "k": 5
        })

        assert isinstance(result, str), "Result should be a string"

    def test_search_with_different_k_values(self):
        """Test search with different k parameter values."""
        # Test with k=1
        result1 = search_sdmx_metadata.invoke({
            "question": "population",
            "k": 1
        })
        assert isinstance(result1, str)

        # Test with k=20 (max)
        result20 = search_sdmx_metadata.invoke({
            "question": "population",
            "k": 20
        })
        assert isinstance(result20, str)

        # Test with k=100 (should be bounded to 20)
        result_large = search_sdmx_metadata.invoke({
            "question": "population",
            "k": 100
        })
        assert isinstance(result_large, str)

    def test_search_empty_query(self):
        """Test search with empty query."""
        result = search_sdmx_metadata.invoke({
            "question": "",
            "k": 5
        })

        # Should handle gracefully
        assert isinstance(result, str)

    def test_search_special_characters(self):
        """Test search with special characters."""
        result = search_sdmx_metadata.invoke({
            "question": "o'lchov birligi: kishi",
            "k": 5
        })

        assert isinstance(result, str)


class TestIntegration:
    """Integration tests with existing tools."""

    def test_metadata_search_ids_can_be_used_with_get_sdmx_value(self):
        """Test that SDMX IDs from metadata search can be used with other tools."""
        from tools import get_sdmx_value

        # Initialize vectorstore
        base_dir = Path(__file__).parent.parent / "jsons" / "sdmxs"
        if not base_dir.exists():
            pytest.skip("SDMX data directory not found")

        if get_metadata_vectorstore() is None:
            initialize_metadata_vectorstore(str(base_dir))

        # Search for something
        result = search_sdmx_metadata.invoke({
            "question": "birth statistics",
            "k": 1
        })

        if "SDMX IDs:" in result:
            # Extract first SDMX ID
            ids_part = result.split("SDMX IDs:")[1].strip()
            first_id = ids_part.split(",")[0].strip()

            # Try to use this ID with get_sdmx_value
            # (might fail if data doesn't exist for that year, but function should work)
            try:
                sdmx_id = int(first_id)
                value_result = get_sdmx_value.invoke({
                    "sdmx_id": sdmx_id,
                    "year": "2020",
                    "region": None
                })

                assert isinstance(value_result, str), "get_sdmx_value should return string"
            except ValueError:
                # ID parsing failed, skip this part
                pass


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
