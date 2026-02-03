"""
Integration test for query endpoint.
"""

import pytest
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app" / "backend"))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    """Test health check endpoint."""
    response = client.get("/api/v1/health")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "models_loaded" in data
    assert "stub_mode" in data
    assert "chroma_indexed_projects" in data
    assert "uptime_seconds" in data
    assert "total_chunks" in data


def test_query_endpoint_structure():
    """Test query endpoint response structure (may run in stub mode)."""
    response = client.post(
        "/api/v1/query",
        json={
            "project_id": "test_proj",
            "query": "What is this project about?",
            "k": 3,
        }
    )
    
    # Should return 200 even in stub mode
    assert response.status_code == 200
    data = response.json()
    
    # Check response structure
    assert "answer" in data
    assert "citations" in data
    assert "confidence" in data
    assert "elapsed_ms" in data
    assert "stub_mode" in data
    
    # Check confidence value
    assert data["confidence"] in ["high", "medium", "low"]


def test_query_endpoint_validation():
    """Test query endpoint input validation."""
    # Missing required fields
    response = client.post(
        "/api/v1/query",
        json={}
    )
    
    assert response.status_code == 422  # Validation error
    
    # Query too short
    response = client.post(
        "/api/v1/query",
        json={
            "project_id": "test",
            "query": "ab",  # Less than 3 chars
            "k": 3,
        }
    )
    
    assert response.status_code == 422
    
    # Invalid k value
    response = client.post(
        "/api/v1/query",
        json={
            "project_id": "test",
            "query": "test query",
            "k": 0,  # Must be >= 1
        }
    )
    
    assert response.status_code == 422


def test_root_endpoint():
    """Test root endpoint."""
    response = client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "message" in data
    assert "version" in data
    assert "docs" in data


# ===========================================================================
# Vague Query Handling Tests (2/18 Pilot Stabilization)
# ===========================================================================

class TestVagueQueryHandling:
    """
    Test that vague, imperfect queries still return useful results.
    
    These tests validate the system tolerates:
    - Short/incomplete queries
    - Missing context
    - Imprecise terminology
    """
    
    def test_vague_client_query(self):
        """'who was the client' should return results, not fail."""
        response = client.post(
            "/api/v1/query",
            json={
                "query": "who was the client",
                "k": 5,
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return some answer (not empty error)
        assert "answer" in data
        assert len(data["answer"]) > 0
        
        # Confidence should be set (even if low)
        assert data["confidence"] in ["high", "medium", "low"]
    
    def test_vague_summary_query(self):
        """Single word 'summary' should return project overview."""
        response = client.post(
            "/api/v1/query",
            json={
                "query": "summary",
                "k": 5,
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "answer" in data
        assert data["confidence"] in ["high", "medium", "low"]
    
    def test_vague_location_query(self):
        """'where is this project' should return location info."""
        response = client.post(
            "/api/v1/query",
            json={
                "query": "where is this project located",
                "k": 5,
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "answer" in data
    
    def test_contextual_query_without_context(self):
        """Queries with 'this project' should not crash without explicit project_id."""
        response = client.post(
            "/api/v1/query",
            json={
                "query": "what is this project about",
                "k": 5,
            }
        )
        
        assert response.status_code == 200
        # Should gracefully handle missing context
    
    def test_imprecise_terminology(self):
        """Queries with non-technical terms should still work."""
        response = client.post(
            "/api/v1/query",
            json={
                "query": "environmental stuff",
                "k": 5,
            }
        )
        
        assert response.status_code == 200


class TestRetrievalQuality:
    """
    Test retrieval quality metrics.
    
    These tests ensure the retrieval pipeline returns relevant results.
    """
    
    def test_no_duplicate_citations(self):
        """Citations should not contain duplicates of same chunk."""
        response = client.post(
            "/api/v1/query",
            json={
                "query": "project scope and objectives",
                "k": 10,
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check for duplicate chunk_ids in citations
        if data.get("citations"):
            chunk_ids = [c["chunk_id"] for c in data["citations"]]
            assert len(chunk_ids) == len(set(chunk_ids)), "Duplicate chunk_ids in citations"
    
    def test_citations_always_present_or_low_confidence(self):
        """If no citations, confidence should be 'low'."""
        response = client.post(
            "/api/v1/query",
            json={
                "query": "extremely obscure topic unlikely to exist",
                "k": 5,
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # If no citations, confidence must be low
        if not data.get("citations") or len(data["citations"]) == 0:
            assert data["confidence"] == "low", "Empty citations should have low confidence"
    
    def test_graceful_no_results(self):
        """System should say 'I couldn't find that' instead of hallucinating."""
        response = client.post(
            "/api/v1/query",
            json={
                "query": "quantum chromodynamics particle physics",  # Unlikely in engineering docs
                "k": 5,
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should either have citations OR low confidence with appropriate message
        if not data.get("citations"):
            assert data["confidence"] == "low"


class TestQueryExpander:
    """Unit tests for query expansion logic."""
    
    def test_client_query_expansion(self):
        """Client queries should expand with owner/contractor terms."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "app" / "backend"))
        from app.core.query_expander import QueryExpander
        
        expander = QueryExpander()
        expanded = expander.expand_query("who was the client")
        
        # Should include expansion terms
        assert "client" in expanded.lower()
        assert any(term in expanded.lower() for term in ["owner", "contracted", "agreement"])
    
    def test_doc_type_hints(self):
        """Doc type hints should return relevant document types."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "app" / "backend"))
        from app.core.query_expander import QueryExpander
        
        expander = QueryExpander()
        hints = expander.get_doc_type_hints("who was the client")
        
        # Should suggest contracts/proposals for client queries
        assert any(doc_type in hints for doc_type in ["contract", "agreement", "proposal"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
