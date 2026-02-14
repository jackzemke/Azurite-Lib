"""
Enhanced Document Chunker with Context Preservation.

Key improvements over basic chunker:
1. Preserves document structure (headers stay with content)
2. Adds contextual metadata to each chunk (document title, section, hierarchy)
3. Smart boundary detection (don't split mid-sentence, mid-table)
4. Table-aware splitting: Markdown tables are kept as atomic units
5. Accurate tokenization via tiktoken (cl100k_base encoding)
6. Correct page mapping via character offset tracking
"""

import re
import hashlib
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
import logging
import bisect

logger = logging.getLogger(__name__)

# Lazy-load tiktoken to avoid import cost if not needed
_tiktoken_encoding = None


def _get_encoding():
    """Get tiktoken encoding (cached)."""
    global _tiktoken_encoding
    if _tiktoken_encoding is None:
        try:
            import tiktoken
            _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            logger.warning("tiktoken not installed, falling back to whitespace tokenization")
            _tiktoken_encoding = "fallback"
    return _tiktoken_encoding


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken (accurate) or whitespace (fallback)."""
    enc = _get_encoding()
    if enc == "fallback":
        return len(text.split())
    return len(enc.encode(text, disallowed_special=()))


def _is_markdown_table_line(line: str) -> bool:
    """Check if a line is part of a Markdown table."""
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _extract_table_blocks(text: str) -> List[Tuple[int, int, str]]:
    """Find Markdown table blocks in text.

    Returns list of (start_pos, end_pos, table_text) tuples.
    """
    lines = text.split('\n')
    blocks = []
    table_start = None
    table_lines = []

    for i, line in enumerate(lines):
        if _is_markdown_table_line(line):
            if table_start is None:
                table_start = i
            table_lines.append(line)
        else:
            if table_start is not None and len(table_lines) >= 3:
                # Valid table (header + separator + at least 1 row)
                table_text = '\n'.join(table_lines)
                blocks.append((table_start, i - 1, table_text))
            table_start = None
            table_lines = []

    # Handle table at end of text
    if table_start is not None and len(table_lines) >= 3:
        table_text = '\n'.join(table_lines)
        blocks.append((table_start, len(lines) - 1, table_text))

    return blocks


@dataclass
class ChunkContext:
    """Context information for a chunk."""
    document_title: Optional[str] = None
    section_hierarchy: List[str] = field(default_factory=list)
    document_type: Optional[str] = None
    is_header: bool = False
    has_table: bool = False
    has_list: bool = False


class EnhancedChunker:
    """
    Enhanced document chunker with context preservation.

    Features:
    - Keeps section headers attached to their content
    - Preserves Markdown tables as atomic units
    - Adds document context prefix to each chunk for better retrieval
    - Accurate token counting via tiktoken (cl100k_base)
    - Correct page mapping via character offset tracking
    """

    # Document type detection patterns
    DOC_TYPE_PATTERNS = {
        'proposal': [r'proposal', r'rfp\s*response', r'statement\s*of\s*qualifications', r'soq'],
        'report': [r'report', r'assessment', r'study', r'analysis', r'investigation'],
        'plan': [r'plan', r'design', r'specification'],
        'correspondence': [r'letter', r'memo', r'email', r'transmittal'],
        'permit': [r'permit', r'application', r'regulatory'],
    }

    # Section header patterns (ordered by priority)
    HEADER_PATTERNS = [
        # Markdown headings (from DOCX extractor)
        (r'^(#{1,6})\s+(.+)$', 'markdown'),
        # Numbered sections: "1.0", "1.2.3", "Section 1"
        (r'^(\d+(?:\.\d+)*\.?)\s+(.+)$', 'numbered'),
        # ALL CAPS headers
        (r'^([A-Z][A-Z\s]{4,})$', 'caps'),
        # Title case with colon
        (r'^([A-Z][a-zA-Z\s]+):\s*$', 'title_colon'),
        # Common section keywords
        (r'^(Executive\s+Summary|Introduction|Background|Scope|Methodology|Results|Conclusions?|Recommendations?|References|Appendix)',
         'keyword'),
    ]

    def __init__(
        self,
        chunk_size_tokens: int = 750,
        chunk_overlap_tokens: int = 150,
        min_chunk_size: int = 50,
        max_chunk_size: int = 1500,
        add_context_prefix: bool = True,
        preserve_tables: bool = True,
    ):
        """
        Initialize enhanced chunker.

        Args:
            chunk_size_tokens: Target chunk size in tokens
            chunk_overlap_tokens: Overlap between chunks in tokens
            min_chunk_size: Don't create chunks smaller than this (tokens)
            max_chunk_size: Force split if chunk exceeds this (tokens)
            add_context_prefix: Add document/section context to each chunk
            preserve_tables: Keep Markdown tables as atomic units
        """
        self.chunk_size_tokens = chunk_size_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.add_context_prefix = add_context_prefix
        self.preserve_tables = preserve_tables

    def chunk_document(
        self,
        pages: List[Dict],
        project_id: str,
        file_path: Path,
        file_id: Optional[str] = None,
        project_key: Optional[str] = None,
        doc_type: Optional[str] = None,
    ) -> List[Dict]:
        """
        Chunk a document with enhanced metadata.

        Args:
            pages: List of page dicts from extractor
            project_id: Project folder name (ChromaDB filter key)
            file_path: Source file path
            file_id: File system ID (if known)
            project_key: Ajera project key (if known)
            doc_type: Document type hint

        Returns:
            List of chunk dicts with enhanced metadata
        """
        file_basename = file_path.name

        # Detect document type from filename
        detected_doc_type = self._detect_document_type(file_basename) or doc_type or "document"

        # Extract document title (usually first significant text)
        document_title = self._extract_document_title(pages)

        # Build page character offset map for accurate page mapping
        page_char_offsets = []
        running_offset = 0
        for page in pages:
            page_char_offsets.append(running_offset)
            running_offset += len(page.get("text", "")) + 1  # +1 for joining newline

        # Combine all pages
        full_text = "\n".join(page.get("text", "") for page in pages)

        # Parse document structure
        sections = self._parse_sections(full_text)

        # Generate chunks with context
        chunks = []
        chunk_counter = 0

        # Track character position in full_text for page mapping
        char_pos = 0

        for section in sections:
            section_chunks = self._chunk_section(
                section_text=section["text"],
                section_header=section.get("header"),
                section_level=section.get("level", 0),
            )

            for chunk_text, context in section_chunks:
                chunk_counter += 1

                # Find page by locating chunk text in full_text
                page_num = self._find_page_by_offset(
                    chunk_text, full_text, char_pos, page_char_offsets, pages
                )

                # Update char_pos for next chunk (move forward)
                found_at = full_text.find(chunk_text[:80], char_pos)
                if found_at >= 0:
                    char_pos = found_at

                # Build context prefix
                context_prefix = ""
                if self.add_context_prefix:
                    context_prefix = self._build_context_prefix(
                        document_title=document_title,
                        section_header=section.get("header"),
                        doc_type=detected_doc_type,
                    )

                # Generate unique chunk ID
                path_hash = hashlib.md5(str(file_path).encode()).hexdigest()[:8]
                chunk_id = f"{project_id}_{path_hash}_p{page_num}_c{chunk_counter:04d}"

                # Build the final chunk text
                final_text = f"{context_prefix}\n\n{chunk_text}" if context_prefix else chunk_text

                chunk = {
                    "chunk_id": chunk_id,
                    "project_id": project_id,
                    "file_id": file_id,
                    "project_key": project_key,
                    "file_path": str(file_path),
                    "file_basename": file_basename,
                    "doc_type": detected_doc_type,
                    "page_number": page_num,
                    "text": final_text,
                    "raw_text": chunk_text,
                    "tokens": _count_tokens(final_text),
                    "document_title": document_title,
                    "section_header": section.get("header"),
                    "section_level": section.get("level", 0),
                    "context_prefix": context_prefix,
                    "has_table": context.has_table,
                    "has_list": context.has_list,
                    "ocr_confidence": self._get_page_ocr_confidence(pages, page_num),
                    "created_at": datetime.utcnow().isoformat() + 'Z',
                }

                chunks.append(chunk)

        logger.info(f"Created {len(chunks)} chunks from {file_basename} (type: {detected_doc_type})")
        return chunks

    def _detect_document_type(self, filename: str) -> Optional[str]:
        """Detect document type from filename."""
        filename_lower = filename.lower()

        for doc_type, patterns in self.DOC_TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, filename_lower, re.IGNORECASE):
                    return doc_type

        return None

    def _extract_document_title(self, pages: List[Dict]) -> Optional[str]:
        """Extract document title from first page."""
        if not pages:
            return None

        first_page_text = pages[0].get("text", "")
        lines = first_page_text.split('\n')

        for line in lines[:10]:
            line = line.strip()
            if len(line) < 5:
                continue
            if re.match(r'^(page\s*\d|draft|confidential|\d+/\d+/\d+)', line, re.IGNORECASE):
                continue
            # Strip Markdown heading markers for title
            if line.startswith('#'):
                line = line.lstrip('#').strip()
            if len(line) > 10:
                return line[:200] if len(line) > 200 else line

        return None

    def _parse_sections(self, text: str) -> List[Dict]:
        """Parse document into sections based on headers."""
        lines = text.split('\n')
        sections = []
        current_section = {
            "header": None,
            "level": 0,
            "lines": []
        }

        for line in lines:
            line_stripped = line.strip()
            header_match = self._detect_header(line_stripped)

            if header_match:
                if current_section["lines"]:
                    current_section["text"] = '\n'.join(current_section["lines"])
                    del current_section["lines"]
                    sections.append(current_section)

                current_section = {
                    "header": header_match["text"],
                    "level": header_match["level"],
                    "lines": []
                }
            else:
                current_section["lines"].append(line)

        if current_section["lines"]:
            current_section["text"] = '\n'.join(current_section["lines"])
            del current_section["lines"]
            sections.append(current_section)

        if not sections:
            sections = [{"header": None, "level": 0, "text": text}]

        return sections

    def _detect_header(self, line: str) -> Optional[Dict]:
        """Detect if a line is a section header."""
        if not line or len(line) < 3:
            return None

        for pattern, pattern_type in self.HEADER_PATTERNS:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                if pattern_type == 'markdown':
                    level = len(match.group(1))
                    header_text = match.group(2).strip()
                elif pattern_type == 'numbered':
                    level = match.group(1).count('.') + 1
                    header_text = line
                elif pattern_type == 'caps':
                    level = 1
                    header_text = match.group(1).strip()
                elif pattern_type == 'keyword':
                    level = 1
                    header_text = match.group(1).strip()
                else:
                    level = 2
                    header_text = match.group(1).strip()

                return {"text": header_text, "level": level}

        return None

    def _chunk_section(
        self,
        section_text: str,
        section_header: Optional[str],
        section_level: int,
    ) -> List[Tuple[str, ChunkContext]]:
        """Chunk a section, keeping tables as atomic units."""
        if not section_text.strip():
            return []

        # Detect tables and lists
        has_table = bool(re.search(r'^\|.*\|.*\|', section_text, re.MULTILINE))
        has_list = bool(re.search(r'^[\s]*[-\u2022*]\s', section_text, re.MULTILINE) or
                       re.search(r'^[\s]*\d+[.)]\s', section_text, re.MULTILINE))

        context = ChunkContext(
            section_hierarchy=[section_header] if section_header else [],
            has_table=has_table,
            has_list=has_list,
        )

        token_count = _count_tokens(section_text)

        # If section fits in one chunk, return as-is
        if token_count <= self.chunk_size_tokens:
            return [(section_text.strip(), context)]

        # Split into segments, preserving tables as atomic units
        segments = self._split_preserving_tables(section_text)

        # Build chunks from segments
        chunks = []
        current_parts = []
        current_tokens = 0

        for segment in segments:
            seg_tokens = _count_tokens(segment)

            # If a single table exceeds chunk size, split by rows (preserving header)
            if seg_tokens > self.max_chunk_size and _is_markdown_table_line(segment.split('\n')[0]):
                # Flush current
                if current_parts:
                    chunk_text = '\n\n'.join(current_parts).strip()
                    if _count_tokens(chunk_text) >= self.min_chunk_size:
                        chunks.append((chunk_text, context))
                    current_parts = []
                    current_tokens = 0

                # Split large table
                table_chunks = self._split_large_table(segment)
                for tc in table_chunks:
                    chunks.append((tc, context))
                continue

            # If adding this segment exceeds target, flush
            if (current_tokens + seg_tokens > self.chunk_size_tokens
                and current_tokens >= self.min_chunk_size):
                chunk_text = '\n\n'.join(current_parts).strip()
                chunks.append((chunk_text, context))

                # Overlap: keep last segment for context
                overlap_text = current_parts[-1] if current_parts else ""
                overlap_tokens = _count_tokens(overlap_text)
                if overlap_tokens <= self.chunk_overlap_tokens:
                    current_parts = [overlap_text]
                    current_tokens = overlap_tokens
                else:
                    current_parts = []
                    current_tokens = 0

            current_parts.append(segment)
            current_tokens += seg_tokens

        # Final chunk
        if current_parts:
            chunk_text = '\n\n'.join(current_parts).strip()
            if _count_tokens(chunk_text) >= self.min_chunk_size or not chunks:
                chunks.append((chunk_text, context))
            elif chunks:
                # Append to previous chunk if too small
                prev_text, prev_ctx = chunks[-1]
                chunks[-1] = (prev_text + '\n\n' + chunk_text, prev_ctx)

        return chunks

    def _split_preserving_tables(self, text: str) -> List[str]:
        """Split text into segments, keeping Markdown tables intact.

        Returns a list of text segments where each table is a single segment
        and non-table text is split on paragraph boundaries.
        """
        lines = text.split('\n')
        segments = []
        current_non_table = []
        in_table = False
        table_lines = []

        for line in lines:
            if _is_markdown_table_line(line):
                if not in_table:
                    # Flush non-table text
                    if current_non_table:
                        non_table_text = '\n'.join(current_non_table).strip()
                        if non_table_text:
                            # Split by paragraph within non-table text
                            paragraphs = re.split(r'\n\n+', non_table_text)
                            segments.extend(p.strip() for p in paragraphs if p.strip())
                        current_non_table = []
                    in_table = True
                table_lines.append(line)
            else:
                if in_table:
                    # Flush table
                    if len(table_lines) >= 3:
                        segments.append('\n'.join(table_lines))
                    else:
                        # Too few lines — not a real table
                        current_non_table.extend(table_lines)
                    table_lines = []
                    in_table = False
                current_non_table.append(line)

        # Handle trailing table
        if table_lines and len(table_lines) >= 3:
            segments.append('\n'.join(table_lines))
        elif table_lines:
            current_non_table.extend(table_lines)

        # Handle trailing non-table text
        if current_non_table:
            non_table_text = '\n'.join(current_non_table).strip()
            if non_table_text:
                paragraphs = re.split(r'\n\n+', non_table_text)
                segments.extend(p.strip() for p in paragraphs if p.strip())

        return segments

    def _split_large_table(self, table_text: str) -> List[str]:
        """Split a large Markdown table into chunks, preserving header.

        Each chunk gets the header row and separator, then a subset of data rows.
        """
        lines = table_text.split('\n')
        if len(lines) < 3:
            return [table_text]

        header = lines[0]
        separator = lines[1]
        data_rows = lines[2:]

        chunks = []
        current_rows = []
        current_tokens = _count_tokens(header + '\n' + separator)

        for row in data_rows:
            row_tokens = _count_tokens(row)
            if (current_tokens + row_tokens > self.chunk_size_tokens
                and current_rows):
                chunk = '\n'.join([header, separator] + current_rows)
                chunks.append(chunk)
                current_rows = []
                current_tokens = _count_tokens(header + '\n' + separator)

            current_rows.append(row)
            current_tokens += row_tokens

        if current_rows:
            chunk = '\n'.join([header, separator] + current_rows)
            chunks.append(chunk)

        return chunks

    def _build_context_prefix(
        self,
        document_title: Optional[str],
        section_header: Optional[str],
        doc_type: Optional[str],
    ) -> str:
        """Build context prefix for chunk."""
        parts = []

        if doc_type:
            parts.append(f"[Document Type: {doc_type}]")

        if document_title:
            title = document_title[:100] + "..." if len(document_title) > 100 else document_title
            parts.append(f"[Document: {title}]")

        if section_header:
            parts.append(f"[Section: {section_header}]")

        return ' '.join(parts)

    def _find_page_by_offset(
        self,
        chunk_text: str,
        full_text: str,
        search_from: int,
        page_offsets: List[int],
        pages: List[Dict],
    ) -> int:
        """Find which page a chunk belongs to using character offsets.

        Uses binary search on pre-computed page character offsets for O(log n).
        """
        # Find where chunk text appears in full_text
        snippet = chunk_text[:80]
        pos = full_text.find(snippet, search_from)
        if pos < 0:
            pos = full_text.find(snippet)
        if pos < 0:
            return pages[0].get("page_num", 1) if pages else 1

        # Binary search: find the page that contains this position
        page_idx = bisect.bisect_right(page_offsets, pos) - 1
        page_idx = max(0, min(page_idx, len(pages) - 1))

        return pages[page_idx].get("page_num", page_idx + 1)

    def _get_page_ocr_confidence(self, pages: List[Dict], page_num: int) -> float:
        """Get OCR confidence for a specific page."""
        for page in pages:
            if page.get("page_num") == page_num:
                return page.get("ocr_confidence", 0.0)
        return 0.0
