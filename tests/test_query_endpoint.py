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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
