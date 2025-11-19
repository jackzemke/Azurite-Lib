"""
Unit tests for the chunker module.
"""

import pytest
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app" / "backend"))

from app.core.chunker import Chunker


def test_chunker_initialization():
    """Test chunker initialization with default parameters."""
    chunker = Chunker()
    assert chunker.chunk_size_tokens == 500
    assert chunker.chunk_overlap_tokens == 100
    assert chunker.semantic is True


def test_chunker_with_custom_params():
    """Test chunker with custom parameters."""
    chunker = Chunker(chunk_size_tokens=300, chunk_overlap_tokens=50, semantic=False)
    assert chunker.chunk_size_tokens == 300
    assert chunker.chunk_overlap_tokens == 50
    assert chunker.semantic is False


def test_fixed_window_chunking_short_text():
    """Test fixed window chunking with text shorter than chunk size."""
    chunker = Chunker(chunk_size_tokens=100)
    text = "This is a short text."
    
    chunks = chunker._fixed_window_chunk(text)
    
    assert len(chunks) == 1
    assert chunks[0] == text


def test_fixed_window_chunking_long_text():
    """Test fixed window chunking with text longer than chunk size."""
    chunker = Chunker(chunk_size_tokens=20, chunk_overlap_tokens=5)
    
    # Create text with 50 tokens
    text = " ".join([f"word{i}" for i in range(50)])
    
    chunks = chunker._fixed_window_chunk(text)
    
    # Should create multiple chunks
    assert len(chunks) > 1
    
    # Check overlap exists (first word of chunk N should appear in chunk N-1)
    for i in range(1, len(chunks)):
        prev_words = set(chunks[i-1].split())
        curr_words = set(chunks[i].split())
        overlap_words = prev_words & curr_words
        assert len(overlap_words) > 0, "Chunks should have overlap"


def test_split_by_headings_with_all_caps():
    """Test semantic splitting with ALL CAPS headings."""
    chunker = Chunker(semantic=True)
    
    text = """INTRODUCTION

This is the introduction section with some content.

METHODOLOGY

This is the methodology section with different content.

RESULTS

And here are the results."""
    
    sections = chunker._split_by_headings(text)
    
    # Should split into multiple sections
    assert len(sections) > 1
    
    # Each section should contain the heading
    assert any("INTRODUCTION" in s for s in sections)
    assert any("METHODOLOGY" in s for s in sections)


def test_split_by_headings_with_numbered():
    """Test semantic splitting with numbered headings."""
    chunker = Chunker(semantic=True)
    
    text = """1. Introduction

Content for section 1.

2. Background

Content for section 2.

3.1 Subsection

Content for subsection 3.1."""
    
    sections = chunker._split_by_headings(text)
    
    assert len(sections) > 1
    assert any("Introduction" in s for s in sections)
    assert any("Background" in s for s in sections)


def test_split_by_headings_fallback():
    """Test that semantic splitting falls back to full text if no headings."""
    chunker = Chunker(semantic=True)
    
    text = "This is just plain text without any headings or structure."
    
    sections = chunker._split_by_headings(text)
    
    # Should return single section (fallback)
    assert len(sections) == 1
    assert sections[0] == text


def test_chunk_document_simple():
    """Test chunking a simple document."""
    chunker = Chunker(chunk_size_tokens=50, semantic=False)
    
    pages = [
        {
            "page_num": 1,
            "text": "This is page 1 content. " * 30,  # Long text
            "ocr_confidence": 0.95,
        }
    ]
    
    chunks = chunker.chunk_document(
        pages=pages,
        project_id="test_proj",
        file_path=Path("/test/doc.pdf"),
        file_basename="doc.pdf",
        doc_type="pdf",
    )
    
    # Should create multiple chunks
    assert len(chunks) > 0
    
    # Check chunk structure
    chunk = chunks[0]
    assert "chunk_id" in chunk
    assert chunk["project_id"] == "test_proj"
    assert chunk["file_basename"] == "doc.pdf"
    assert chunk["doc_type"] == "pdf"
    assert chunk["page_number"] == 1
    assert chunk["tokens"] > 0
    assert "text" in chunk
    assert "created_at" in chunk


def test_chunk_document_multiple_pages():
    """Test chunking a multi-page document."""
    chunker = Chunker(chunk_size_tokens=50, semantic=False)
    
    pages = [
        {"page_num": 1, "text": "Page 1 content. " * 20},
        {"page_num": 2, "text": "Page 2 content. " * 20},
        {"page_num": 3, "text": "Page 3 content. " * 20},
    ]
    
    chunks = chunker.chunk_document(
        pages=pages,
        project_id="test_proj",
        file_path=Path("/test/doc.pdf"),
        file_basename="doc.pdf",
        doc_type="pdf",
    )
    
    # Should have chunks from all pages
    page_numbers = [c["page_number"] for c in chunks]
    assert 1 in page_numbers
    assert 2 in page_numbers
    assert 3 in page_numbers


def test_chunk_document_empty_page():
    """Test that empty pages are skipped."""
    chunker = Chunker()
    
    pages = [
        {"page_num": 1, "text": "Page 1 content."},
        {"page_num": 2, "text": ""},  # Empty page
        {"page_num": 3, "text": "Page 3 content."},
    ]
    
    chunks = chunker.chunk_document(
        pages=pages,
        project_id="test_proj",
        file_path=Path("/test/doc.pdf"),
        file_basename="doc.pdf",
        doc_type="pdf",
    )
    
    # Should only have chunks from non-empty pages
    page_numbers = [c["page_number"] for c in chunks]
    assert 2 not in page_numbers


def test_token_counting():
    """Test token counting."""
    chunker = Chunker()
    
    text = "This is a test with ten words in this sentence."
    token_count = chunker._count_tokens(text)
    
    assert token_count == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
