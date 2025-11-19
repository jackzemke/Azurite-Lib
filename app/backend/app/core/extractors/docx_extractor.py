"""
DOCX (Word Document) Extractor.

Extracts text and metadata from Microsoft Word documents.
"""

from docx import Document
from pathlib import Path
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class DOCXExtractor:
    """Extract text and metadata from DOCX files."""

    def extract(self, file_path: Path) -> Dict:
        """
        Extract text from DOCX file, paragraph by paragraph.

        Args:
            file_path: Path to DOCX file

        Returns:
            Dict with:
                - pages: List of dicts (simulated pages, one per major section)
                - total_pages: int (number of sections)
                - requires_ocr: bool (always False for DOCX)
                - metadata: dict (core properties)
        """
        try:
            doc = Document(file_path)

            # Extract metadata
            core_props = doc.core_properties
            metadata = {
                "title": core_props.title or "",
                "author": core_props.author or "",
                "created": str(core_props.created) if core_props.created else None,
                "modified": str(core_props.modified) if core_props.modified else None,
            }

            # Extract paragraphs
            paragraphs = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    paragraphs.append(text)

            # Extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text.strip() for cell in row.cells)
                    if row_text:
                        paragraphs.append(f"[TABLE] {row_text}")

            # Simulate pages: group paragraphs (e.g., every 10 paragraphs = 1 page)
            page_size = 10
            pages = []
            for i in range(0, len(paragraphs), page_size):
                page_paragraphs = paragraphs[i:i + page_size]
                page_text = "\n\n".join(page_paragraphs)
                pages.append({
                    "page_num": (i // page_size) + 1,
                    "text": page_text,
                    "bbox_available": False,
                    "width": None,
                    "height": None,
                })

            # If no paragraphs, create one empty page
            if not pages:
                pages = [{
                    "page_num": 1,
                    "text": "",
                    "bbox_available": False,
                    "width": None,
                    "height": None,
                }]

            return {
                "pages": pages,
                "total_pages": len(pages),
                "requires_ocr": False,
                "metadata": metadata,
            }

        except Exception as e:
            logger.error(f"Failed to extract DOCX {file_path}: {e}")
            raise


# TODO: Extract images embedded in DOCX
# TODO: Preserve heading styles for better semantic chunking
