"""
Unit tests for PDF extractor.
"""

import pytest
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app" / "backend"))

from app.core.extractors.pdf_extractor import PDFExtractor


def test_pdf_extractor_initialization():
    """Test PDF extractor initialization."""
    extractor = PDFExtractor()
    assert extractor.min_text_length == 100
    
    extractor = PDFExtractor(min_text_length=200)
    assert extractor.min_text_length == 200


# NOTE: Full PDF extraction tests would require sample PDF files
# These tests serve as examples and would pass with actual PDF files

def test_pdf_extractor_structure():
    """Test that PDFExtractor has required methods."""
    extractor = PDFExtractor()
    
    assert hasattr(extractor, 'extract')
    assert hasattr(extractor, 'extract_page_bbox')
    assert callable(extractor.extract)
    assert callable(extractor.extract_page_bbox)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
