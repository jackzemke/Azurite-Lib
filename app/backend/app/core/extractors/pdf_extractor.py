"""
PDF Text Extractor using pdfplumber.

Handles digital PDFs with text extraction and falls back to OCR for scanned PDFs.
"""

import pdfplumber
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class PDFExtractor:
    """Extract text and metadata from PDF files."""

    def __init__(self, min_text_length: int = 100):
        """
        Initialize PDF extractor.

        Args:
            min_text_length: Minimum text length to consider extraction successful.
                           If less, triggers OCR.
        """
        self.min_text_length = min_text_length

    def extract(self, file_path: Path) -> Dict:
        """
        Extract text from PDF, page by page.

        Args:
            file_path: Path to PDF file

        Returns:
            Dict with:
                - pages: List of dicts with {page_num, text, bbox_available}
                - total_pages: int
                - requires_ocr: bool (if extraction yielded little text)
                - metadata: dict (title, author, etc.)
        """
        try:
            with pdfplumber.open(file_path) as pdf:
                metadata = pdf.metadata or {}
                total_pages = len(pdf.pages)
                pages = []

                for i, page in enumerate(pdf.pages):
                    page_num = i + 1
                    text = page.extract_text() or ""
                    
                    # Extract words with bounding boxes (for highlighting)
                    words = page.extract_words()
                    bbox_available = len(words) > 0

                    pages.append({
                        "page_num": page_num,
                        "text": text.strip(),
                        "bbox_available": bbox_available,
                        "width": page.width,
                        "height": page.height,
                    })

                # Check if OCR needed (overall text too short)
                total_text = " ".join(p["text"] for p in pages)
                requires_ocr = len(total_text) < self.min_text_length

                return {
                    "pages": pages,
                    "total_pages": total_pages,
                    "requires_ocr": requires_ocr,
                    "metadata": metadata,
                }

        except Exception as e:
            logger.error(f"Failed to extract PDF {file_path}: {e}")
            raise

    def extract_page_bbox(self, file_path: Path, page_num: int) -> List[Dict]:
        """
        Extract word-level bounding boxes for a specific page.

        Args:
            file_path: Path to PDF
            page_num: Page number (1-indexed)

        Returns:
            List of dicts: {text, x0, y0, x1, y1}
        """
        try:
            with pdfplumber.open(file_path) as pdf:
                if page_num < 1 or page_num > len(pdf.pages):
                    return []

                page = pdf.pages[page_num - 1]
                words = page.extract_words()

                return [
                    {
                        "text": w["text"],
                        "x0": w["x0"],
                        "y0": w["top"],
                        "x1": w["x1"],
                        "y1": w["bottom"],
                    }
                    for w in words
                ]

        except Exception as e:
            logger.error(f"Failed to extract bbox from {file_path} page {page_num}: {e}")
            return []


# TODO: Consider adding table extraction with pdfplumber.extract_tables()
# TODO: Handle encrypted PDFs with password parameter
