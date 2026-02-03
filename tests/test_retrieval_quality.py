"""
Retrieval quality tests for AAA pilot stabilization.

These tests validate that vague, natural language queries return
relevant results - critical for non-technical user adoption.

Run with: pytest tests/test_retrieval_quality.py -v
"""

import pytest
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app" / "backend"))

import yaml
from app.core.indexer import Indexer
from app.core.embedder import Embedder
from app.core.query_expander import QueryExpander


@pytest.fixture(scope="module")
def config():
    """Load config."""
    config_path = Path("/home/jack/lib/project-library/app/backend/config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def embedder(config):
    """Initialize embedder."""
    return Embedder(model_name=config["embedding"]["model_name"])


@pytest.fixture(scope="module")
def indexer(config):
    """Initialize indexer."""
    return Indexer(chroma_db_path=Path(config["paths"]["chroma_db"]))


@pytest.fixture(scope="module")
def query_expander():
    """Initialize query expander."""
    return QueryExpander()


class TestQueryExpansion:
    """Test query expansion for vague queries."""
    
    def test_client_query_expansion(self, query_expander):
        """Client queries should expand with contract-related terms."""
        query = "who was the client"
        expanded = query_expander.expand_query(query)
        
        assert "client" in expanded.lower()
        # Should add synonyms like owner, contracted by
        assert any(term in expanded.lower() for term in ["owner", "contracted", "agreement"])
    
    def test_location_query_expansion(self, query_expander):
        """Location queries should expand with address-related terms."""
        query = "where is the project located"
        expanded = query_expander.expand_query(query)
        
        assert any(term in expanded.lower() for term in ["location", "address", "site", "city"])
    
    def test_summary_query_expansion(self, query_expander):
        """Summary queries should expand with scope-related terms."""
        query = "give me a summary"
        expanded = query_expander.expand_query(query)
        
        assert any(term in expanded.lower() for term in ["scope", "description", "overview"])
    
    def test_doc_type_hints_for_client(self, query_expander):
        """Client queries should hint at contracts and proposals."""
        hints = query_expander.get_doc_type_hints("who was the client")
        
        assert len(hints) > 0
        assert any(h in hints for h in ["contract", "agreement", "proposal"])
    
    def test_doc_type_hints_for_cost(self, query_expander):
        """Cost queries should hint at invoices and proposals."""
        hints = query_expander.get_doc_type_hints("what was the project cost")
        
        assert len(hints) > 0
        assert any(h in hints for h in ["invoice", "proposal", "contract"])


class TestRetrievalQuality:
    """Test that retrieval returns relevant results for various query types."""
    
    def _query(self, embedder, indexer, query_expander, query, top_k=6):
        """Helper to run a query with expansion and doc hints."""
        expanded = query_expander.expand_query(query)
        doc_hints = query_expander.get_doc_type_hints(query)
        embedding = embedder.model.encode([expanded])[0].tolist()
        
        return indexer.query(
            query_embedding=embedding,
            top_k=top_k,
            doc_type_hints=doc_hints,
        )
    
    def test_vague_client_query_returns_results(self, embedder, indexer, query_expander):
        """Vague 'who was the client' should return contract-like documents."""
        results = self._query(embedder, indexer, query_expander, "who was the client")
        
        assert len(results) > 0, "No results for 'who was the client'"
        
        # Top result should have reasonable distance (< 0.6 is acceptable)
        top_distance = results[0].get("distance", 1.0)
        assert top_distance < 0.6, f"Top result distance {top_distance} too high"
    
    def test_vague_summary_query_returns_results(self, embedder, indexer, query_expander):
        """Vague 'summary' should return scope/overview documents."""
        results = self._query(embedder, indexer, query_expander, "summary")
        
        assert len(results) > 0, "No results for 'summary'"
        
        top_distance = results[0].get("distance", 1.0)
        assert top_distance < 0.5, f"Top result distance {top_distance} too high for summary"
    
    def test_vague_about_query_returns_results(self, embedder, indexer, query_expander):
        """Vague 'what is this project about' should return relevant docs."""
        results = self._query(embedder, indexer, query_expander, "what is this project about")
        
        assert len(results) > 0, "No results for 'what is this project about'"
        
        top_distance = results[0].get("distance", 1.0)
        assert top_distance < 0.5, f"Top result distance {top_distance} too high"
    
    def test_specific_technical_query(self, embedder, indexer, query_expander):
        """Specific technical queries should return highly relevant results."""
        results = self._query(embedder, indexer, query_expander, "environmental site assessment")
        
        assert len(results) > 0, "No results for technical query"
        
        # Technical queries should have better matches
        top_distance = results[0].get("distance", 1.0)
        assert top_distance < 0.45, f"Top result distance {top_distance} too high for technical query"


class TestDiversityFiltering:
    """Test that diversity filtering prevents duplicate-heavy results."""
    
    def test_no_excessive_duplicates_from_same_file(self, embedder, indexer, query_expander):
        """Results should not have more than 2 chunks from same file."""
        query = "project information"
        expanded = query_expander.expand_query(query)
        embedding = embedder.model.encode([expanded])[0].tolist()
        
        results = indexer.query(
            query_embedding=embedding,
            top_k=10,
            diversity=True,
            max_per_document=2,
        )
        
        # Count chunks per file
        file_counts = {}
        for r in results:
            file_path = r["metadata"].get("file_path", "")
            file_counts[file_path] = file_counts.get(file_path, 0) + 1
        
        # No file should have more than 2 chunks
        for file_path, count in file_counts.items():
            assert count <= 2, f"File {file_path} has {count} chunks (max 2)"
    
    def test_sibling_document_deduplication(self, embedder, indexer, query_expander):
        """Similar documents (e.g., multiple invoices) should be limited."""
        query = "invoice payment"
        expanded = query_expander.expand_query(query)
        embedding = embedder.model.encode([expanded])[0].tolist()
        
        results = indexer.query(
            query_embedding=embedding,
            top_k=10,
            diversity=True,
        )
        
        # Count how many "invoice" documents appear
        invoice_count = sum(
            1 for r in results 
            if "invoice" in r["metadata"].get("file_basename", "").lower()
        )
        
        # Should have variety, not all invoices
        # Allow up to 4 invoice chunks (2 files x 2 chunks max)
        assert invoice_count <= 4, f"Too many invoice chunks: {invoice_count}"


class TestDocTypeBoost:
    """Test that doc type hints boost relevant document types."""
    
    def test_contract_boosted_for_client_query(self, embedder, indexer, query_expander):
        """Contract documents should rank higher for client queries."""
        query = "who was the client"
        expanded = query_expander.expand_query(query)
        doc_hints = query_expander.get_doc_type_hints(query)
        embedding = embedder.model.encode([expanded])[0].tolist()
        
        # Query with hints
        results_with_hints = indexer.query(
            query_embedding=embedding,
            top_k=6,
            doc_type_hints=doc_hints,
        )
        
        # Query without hints
        results_without_hints = indexer.query(
            query_embedding=embedding,
            top_k=6,
            doc_type_hints=None,
        )
        
        # With hints, contract should appear in top 2
        top_2_files_with_hints = [
            r["metadata"].get("file_basename", "").lower() 
            for r in results_with_hints[:2]
        ]
        
        has_contract_in_top_2 = any(
            "contract" in f or "agreement" in f 
            for f in top_2_files_with_hints
        )
        
        assert has_contract_in_top_2, f"Contract not in top 2: {top_2_files_with_hints}"
