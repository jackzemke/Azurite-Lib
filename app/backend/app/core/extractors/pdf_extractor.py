"""
PDF Text Extractor using pdfplumber.

Handles digital PDFs with text extraction, table extraction (as Markdown),
and falls back to OCR for scanned PDFs.
"""

import pdfplumber
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def _table_to_markdown(table: List[List]) -> str:
    """Convert a pdfplumber table (list of rows) to Markdown format.

    Args:
        table: List of rows, where each row is a list of cell values.
               First row is treated as headers.

    Returns:
        Markdown table string, or empty string if table is empty/invalid.
    """
    if not table or len(table) < 2:
        return ""

    # Clean cells: replace None with empty string, strip whitespace
    cleaned = []
    for row in table:
        cleaned.append([str(cell).strip() if cell is not None else "" for cell in row])

    # Skip tables where all cells are empty
    if all(all(c == "" for c in row) for row in cleaned):
        return ""

    # Determine column count from the widest row
    n_cols = max(len(row) for row in cleaned)

    # Pad rows to uniform width
    for row in cleaned:
        while len(row) < n_cols:
            row.append("")

    # Build header
    header = cleaned[0]
    separator = ["---"] * n_cols
    body = cleaned[1:]

    lines = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(separator) + " |")
    for row in body:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


class PDFExtractor:
    """Extract text and tables from PDF files."""

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
        Extract text and tables from PDF, page by page.

        Tables are detected via pdfplumber.extract_tables() and converted to
        Markdown format, then appended to the page text. This preserves table
        structure through the chunking pipeline.

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

                    # Extract tables and convert to Markdown
                    tables = page.extract_tables() or []
                    table_markdowns = []
                    for table in tables:
                        md = _table_to_markdown(table)
                        if md:
                            table_markdowns.append(md)

                    # Combine text and tables
                    # Tables are appended after the page text with a separator
                    if table_markdowns:
                        tables_block = "\n\n".join(table_markdowns)
                        if text.strip():
                            combined = f"{text.strip()}\n\n{tables_block}"
                        else:
                            combined = tables_block
                    else:
                        combined = text.strip()

                    # Extract words with bounding boxes (for highlighting)
                    words = page.extract_words()
                    bbox_available = len(words) > 0

                    pages.append({
                        "page_num": page_num,
                        "text": combined,
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
