"""
Text Chunker with Semantic-First Strategy.

Splits documents into chunks using semantic boundaries (headings) when possible,
with fallback to fixed-window chunking.
"""

import re
from typing import List, Dict
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class Chunker:
    """Chunk documents into token-sized pieces with overlap."""

    def __init__(
        self,
        chunk_size_tokens: int = 500,
        chunk_overlap_tokens: int = 100,
        semantic: bool = True,
    ):
        """
        Initialize chunker.

        Args:
            chunk_size_tokens: Target chunk size in tokens
            chunk_overlap_tokens: Overlap between chunks
            semantic: Try semantic chunking first (split at headings)
        """
        self.chunk_size_tokens = chunk_size_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens
        self.semantic = semantic

    def chunk_document(
        self,
        pages: List[Dict],
        project_id: str,
        file_path: Path,
        file_basename: str,
        doc_type: str,
    ) -> List[Dict]:
        """
        Chunk a document into overlapping pieces.

        Args:
            pages: List of page dicts from extractor
            project_id: Project ID
            file_path: Source file path
            file_basename: Source filename
            doc_type: pdf|docx|image|etc.

        Returns:
            List of chunk dicts with schema from Section 6
        """
        chunks = []
        chunk_counter = 0

        for page in pages:
            page_num = page["page_num"]
            page_text = page["text"]
            ocr_confidence = page.get("ocr_confidence", 0.0)

            if not page_text.strip():
                continue

            # Try semantic chunking first
            if self.semantic:
                sections = self._split_by_headings(page_text)
            else:
                sections = [page_text]

            # For each section, apply fixed-window chunking if needed
            for section in sections:
                section_chunks = self._fixed_window_chunk(section)

                for chunk_text in section_chunks:
                    chunk_counter += 1
                    chunk_id = f"{project_id}_{file_basename}_p{page_num}_c{chunk_counter:04d}"

                    token_count = self._count_tokens(chunk_text)

                    chunk = {
                        "chunk_id": chunk_id,
                        "project_id": project_id,
                        "file_path": str(file_path),
                        "file_basename": file_basename,
                        "doc_type": doc_type,
                        "page_number": page_num,
                        "bbox": page.get("bbox", None),
                        "text": chunk_text,
                        "tokens": token_count,
                        "ocr_confidence": ocr_confidence,
                        "created_at": self._get_timestamp(),
                    }

                    chunks.append(chunk)

        return chunks

    def _split_by_headings(self, text: str) -> List[str]:
        """
        Split text at semantic boundaries (headings).

        Detects:
        - ALL CAPS lines (e.g., "SECTION 3: DRAINAGE")
        - Numbered headings (e.g., "1. Introduction", "3.2.1 Scope")
        - Common heading keywords (e.g., "Background", "Summary")
        """
        # Patterns for headings
        heading_patterns = [
            r'^[A-Z][A-Z\s]{3,}$',  # ALL CAPS line (min 4 chars)
            r'^\d+(\.\d+)*\.?\s+[A-Z]',  # Numbered heading (e.g., "1.2.3 Title")
            r'^(Background|Introduction|Summary|Conclusion|Discussion|Methods|Results|Scope|Purpose|Objective)s?:?\s*$',
        ]

        lines = text.split('\n')
        sections = []
        current_section = []

        for line in lines:
            line_stripped = line.strip()

            # Check if this line is a heading
            is_heading = False
            for pattern in heading_patterns:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    is_heading = True
                    break

            if is_heading and current_section:
                # Save current section and start new one
                sections.append('\n'.join(current_section))
                current_section = [line]
            else:
                current_section.append(line)

        # Add final section
        if current_section:
            sections.append('\n'.join(current_section))

        # If only one section found, fall back to full text
        if len(sections) <= 1:
            return [text]

        return sections

    def _fixed_window_chunk(self, text: str) -> List[str]:
        """
        Apply fixed-window chunking with overlap.

        Args:
            text: Text to chunk

        Returns:
            List of chunk strings
        """
        tokens = self._tokenize(text)

        if len(tokens) <= self.chunk_size_tokens:
            return [text]

        chunks = []
        start = 0

        while start < len(tokens):
            end = start + self.chunk_size_tokens
            chunk_tokens = tokens[start:end]
            chunk_text = ' '.join(chunk_tokens)
            chunks.append(chunk_text)

            # Move start forward, accounting for overlap
            start += self.chunk_size_tokens - self.chunk_overlap_tokens

            # Prevent infinite loop
            if start <= len(tokens) - self.chunk_size_tokens:
                continue
            elif start < len(tokens):
                # Last chunk
                chunk_tokens = tokens[start:]
                chunk_text = ' '.join(chunk_tokens)
                chunks.append(chunk_text)
                break
            else:
                break

        return chunks

    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace tokenization (approximation)."""
        return text.split()

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self._tokenize(text))

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO 8601 format."""
        from datetime import datetime
        return datetime.utcnow().isoformat() + 'Z'


# TODO: Use tiktoken for more accurate token counting (matches LLM tokenizer)
# TODO: Preserve code blocks and tables as atomic units (don't split)
