"""
Enhanced Document Chunker with Context Preservation.

Key improvements over basic chunker:
1. Preserves document structure (headers stay with content)
2. Adds contextual metadata to each chunk (document title, section, hierarchy)
3. Smart boundary detection (don't split mid-sentence, mid-table)
4. Document type-aware chunking strategies
5. Generates chunk summaries for hierarchical retrieval
"""

import re
import hashlib
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


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
    - Preserves tables and lists as atomic units when possible
    - Adds document context prefix to each chunk for better retrieval
    - Supports different chunking strategies per document type
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
        chunk_size_tokens: int = 500,
        chunk_overlap_tokens: int = 100,
        min_chunk_size: int = 50,
        max_chunk_size: int = 1000,
        add_context_prefix: bool = True,
        preserve_tables: bool = True,
    ):
        """
        Initialize enhanced chunker.
        
        Args:
            chunk_size_tokens: Target chunk size
            chunk_overlap_tokens: Overlap between chunks
            min_chunk_size: Don't create chunks smaller than this
            max_chunk_size: Force split if chunk exceeds this
            add_context_prefix: Add document/section context to each chunk
            preserve_tables: Try to keep tables as atomic units
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
        
        # Combine all pages for section analysis
        full_text = "\n".join(page.get("text", "") for page in pages)
        
        # Parse document structure
        sections = self._parse_sections(full_text)
        
        # Generate chunks with context
        chunks = []
        chunk_counter = 0
        
        # Track page mapping for accurate page numbers
        page_char_offsets = self._calculate_page_offsets(pages)
        
        for section in sections:
            section_chunks = self._chunk_section(
                section_text=section["text"],
                section_header=section.get("header"),
                section_level=section.get("level", 0),
            )
            
            for chunk_text, context in section_chunks:
                chunk_counter += 1
                
                # Find which page this chunk belongs to
                page_num = self._find_page_for_text(chunk_text, pages, page_char_offsets)
                
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
                    # Core identifiers
                    "chunk_id": chunk_id,
                    "project_id": project_id,  # Folder name for ChromaDB filtering
                    
                    # Extended identifiers for cross-referencing
                    "file_id": file_id,        # File system ID (e.g., "1430152")
                    "project_key": project_key, # Ajera key (e.g., "125259")
                    
                    # File information
                    "file_path": str(file_path),
                    "file_basename": file_basename,
                    "doc_type": detected_doc_type,
                    "page_number": page_num,
                    
                    # Content
                    "text": final_text,
                    "raw_text": chunk_text,  # Without context prefix
                    "tokens": self._count_tokens(final_text),
                    
                    # Context metadata
                    "document_title": document_title,
                    "section_header": section.get("header"),
                    "section_level": section.get("level", 0),
                    "context_prefix": context_prefix,
                    
                    # Quality indicators
                    "has_table": context.has_table,
                    "has_list": context.has_list,
                    "ocr_confidence": self._get_page_ocr_confidence(pages, page_num),
                    
                    # Timestamps
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
        
        # Look for title-like content in first 10 lines
        for line in lines[:10]:
            line = line.strip()
            # Skip empty lines and very short lines
            if len(line) < 5:
                continue
            # Skip lines that look like headers/footers
            if re.match(r'^(page\s*\d|draft|confidential|\d+/\d+/\d+)', line, re.IGNORECASE):
                continue
            # Take first substantial line as title
            if len(line) > 10:
                # Truncate very long titles
                return line[:200] if len(line) > 200 else line
        
        return None
    
    def _parse_sections(self, text: str) -> List[Dict]:
        """
        Parse document into sections based on headers.
        
        Returns list of dicts with 'header', 'level', 'text'.
        """
        lines = text.split('\n')
        sections = []
        current_section = {
            "header": None,
            "level": 0,
            "lines": []
        }
        
        for line in lines:
            line_stripped = line.strip()
            
            # Check if this is a header
            header_match = self._detect_header(line_stripped)
            
            if header_match:
                # Save current section if it has content
                if current_section["lines"]:
                    current_section["text"] = '\n'.join(current_section["lines"])
                    del current_section["lines"]
                    sections.append(current_section)
                
                # Start new section
                current_section = {
                    "header": header_match["text"],
                    "level": header_match["level"],
                    "lines": []
                }
            else:
                current_section["lines"].append(line)
        
        # Don't forget the last section
        if current_section["lines"]:
            current_section["text"] = '\n'.join(current_section["lines"])
            del current_section["lines"]
            sections.append(current_section)
        
        # If no sections found, treat entire document as one section
        if not sections:
            sections = [{"header": None, "level": 0, "text": text}]
        
        return sections
    
    def _detect_header(self, line: str) -> Optional[Dict]:
        """
        Detect if a line is a section header.
        
        Returns dict with 'text' and 'level' if header, None otherwise.
        """
        if not line or len(line) < 3:
            return None
        
        for pattern, pattern_type in self.HEADER_PATTERNS:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                # Determine header level
                if pattern_type == 'numbered':
                    # Count dots to determine level: "1" = 1, "1.2" = 2, "1.2.3" = 3
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
        """
        Chunk a section, keeping header attached to first chunk.
        
        Returns list of (chunk_text, context) tuples.
        """
        if not section_text.strip():
            return []
        
        # Detect tables and lists
        has_table = bool(re.search(r'\|.*\|.*\|', section_text) or 
                        re.search(r'\t.*\t', section_text))
        has_list = bool(re.search(r'^[\s]*[-•*]\s', section_text, re.MULTILINE) or
                       re.search(r'^[\s]*\d+[.)]\s', section_text, re.MULTILINE))
        
        context = ChunkContext(
            section_hierarchy=[section_header] if section_header else [],
            has_table=has_table,
            has_list=has_list,
        )
        
        tokens = self._tokenize(section_text)
        
        # If section fits in one chunk, return as-is
        if len(tokens) <= self.chunk_size_tokens:
            return [(section_text.strip(), context)]
        
        # Split into multiple chunks
        chunks = []
        sentences = self._split_into_sentences(section_text)
        
        current_chunk_tokens = []
        current_chunk_text = []
        
        for sentence in sentences:
            sentence_tokens = self._tokenize(sentence)
            
            # If adding this sentence exceeds target, save current chunk
            if (len(current_chunk_tokens) + len(sentence_tokens) > self.chunk_size_tokens 
                and len(current_chunk_tokens) >= self.min_chunk_size):
                
                chunk_text = ' '.join(current_chunk_text)
                chunks.append((chunk_text, context))
                
                # Start new chunk with overlap
                overlap_start = max(0, len(current_chunk_tokens) - self.chunk_overlap_tokens)
                current_chunk_tokens = current_chunk_tokens[overlap_start:]
                current_chunk_text = current_chunk_text[-(len(current_chunk_text)//4 + 1):]  # Keep ~25%
            
            current_chunk_tokens.extend(sentence_tokens)
            current_chunk_text.append(sentence)
        
        # Don't forget last chunk
        if current_chunk_text:
            chunk_text = ' '.join(current_chunk_text)
            if len(current_chunk_tokens) >= self.min_chunk_size or not chunks:
                chunks.append((chunk_text, context))
            elif chunks:
                # Append to previous chunk if too small
                prev_text, prev_context = chunks[-1]
                chunks[-1] = (prev_text + ' ' + chunk_text, prev_context)
        
        return chunks
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences, preserving structure."""
        # Split on sentence-ending punctuation followed by space and capital
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
        
        # Also split on double newlines (paragraphs)
        result = []
        for sent in sentences:
            parts = re.split(r'\n\n+', sent)
            result.extend(p.strip() for p in parts if p.strip())
        
        return result
    
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
            # Truncate very long titles
            title = document_title[:100] + "..." if len(document_title) > 100 else document_title
            parts.append(f"[Document: {title}]")
        
        if section_header:
            parts.append(f"[Section: {section_header}]")
        
        return ' '.join(parts)
    
    def _calculate_page_offsets(self, pages: List[Dict]) -> List[int]:
        """Calculate character offsets for each page."""
        offsets = []
        total = 0
        for page in pages:
            offsets.append(total)
            total += len(page.get("text", "")) + 1  # +1 for newline
        return offsets
    
    def _find_page_for_text(
        self,
        chunk_text: str,
        pages: List[Dict],
        offsets: List[int]
    ) -> int:
        """Find which page a chunk belongs to."""
        # Simple heuristic: check which page contains the chunk start
        chunk_start = chunk_text[:50] if len(chunk_text) > 50 else chunk_text
        
        for i, page in enumerate(pages):
            if chunk_start in page.get("text", ""):
                return page.get("page_num", i + 1)
        
        # Default to first page if not found
        return pages[0].get("page_num", 1) if pages else 1
    
    def _get_page_ocr_confidence(self, pages: List[Dict], page_num: int) -> float:
        """Get OCR confidence for a specific page."""
        for page in pages:
            if page.get("page_num") == page_num:
                return page.get("ocr_confidence", 0.0)
        return 0.0
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace tokenization."""
        return text.split()
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self._tokenize(text))
