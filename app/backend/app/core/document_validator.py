"""
Document Quality Validator.

Validates documents before ingestion to ensure they're suitable for indexing.
Filters out:
- Corrupted files
- Image-only PDFs with low OCR confidence
- Documents with insufficient text content
- Duplicate files
- Unsupported formats
"""

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DocumentQuality(Enum):
    """Document quality classification."""
    HIGH = "high"           # Good text extraction, structured content
    MEDIUM = "medium"       # Acceptable but may have issues
    LOW = "low"             # Poor quality, may not be useful
    SKIP = "skip"           # Should not be indexed


class SkipReason(Enum):
    """Reasons for skipping a document."""
    INSUFFICIENT_TEXT = "insufficient_text"
    LOW_OCR_CONFIDENCE = "low_ocr_confidence"
    CORRUPT_FILE = "corrupt_file"
    DUPLICATE = "duplicate"
    UNSUPPORTED_FORMAT = "unsupported_format"
    TEMP_FILE = "temp_file"
    EMPTY_FILE = "empty_file"
    BINARY_ONLY = "binary_only"


@dataclass
class ValidationResult:
    """Result of document validation."""
    quality: DocumentQuality
    skip_reason: Optional[SkipReason] = None
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def should_index(self) -> bool:
        """Whether document should be indexed."""
        return self.quality != DocumentQuality.SKIP


class DocumentValidator:
    """
    Validates documents for ingestion quality.
    
    Configuration thresholds:
    - min_text_length: Minimum characters for indexing (default 100)
    - min_ocr_confidence: Minimum OCR confidence to trust text (default 0.6)
    - min_words: Minimum words per document (default 20)
    """
    
    # Supported file extensions and their types
    SUPPORTED_EXTENSIONS = {
        '.pdf': 'document',
        '.docx': 'document',
        '.doc': 'document',
        '.xlsx': 'spreadsheet',
        '.xls': 'spreadsheet',
        '.png': 'image',
        '.jpg': 'image',
        '.jpeg': 'image',
        '.tiff': 'image',
        '.tif': 'image',
        '.bmp': 'image',
    }
    
    # Files to always skip (temp files, system files)
    SKIP_PATTERNS = [
        r'^~\$',           # Office temp files
        r'^\.DS_Store$',   # macOS
        r'^Thumbs\.db$',   # Windows
        r'^desktop\.ini$', # Windows
        r'^\.',            # Hidden files
    ]
    
    # Document types that are typically less useful for Q&A
    LOW_VALUE_PATTERNS = [
        r'cover\s*letter',
        r'transmittal',
        r'signature\s*page',
        r'table\s*of\s*contents',
        r'^toc$',
    ]
    
    def __init__(
        self,
        min_text_length: int = 100,
        min_ocr_confidence: float = 0.6,
        min_words: int = 20,
        check_duplicates: bool = True,
    ):
        """
        Initialize validator.
        
        Args:
            min_text_length: Minimum characters for indexing
            min_ocr_confidence: Minimum OCR confidence (0-1)
            min_words: Minimum words per document
            check_duplicates: Whether to track and skip duplicates
        """
        self.min_text_length = min_text_length
        self.min_ocr_confidence = min_ocr_confidence
        self.min_words = min_words
        self.check_duplicates = check_duplicates
        
        # Track seen content hashes for duplicate detection
        self._content_hashes: Dict[str, str] = {}  # hash -> file_path
    
    def validate_file(self, file_path: Path) -> ValidationResult:
        """
        Validate a file before processing.
        
        Args:
            file_path: Path to file
        
        Returns:
            ValidationResult with quality assessment
        """
        warnings = []
        metadata = {
            "file_name": file_path.name,
            "file_size": file_path.stat().st_size if file_path.exists() else 0,
        }
        
        # Check file exists
        if not file_path.exists():
            return ValidationResult(
                quality=DocumentQuality.SKIP,
                skip_reason=SkipReason.CORRUPT_FILE,
                metadata=metadata
            )
        
        # Check for temp/system files
        for pattern in self.SKIP_PATTERNS:
            if re.match(pattern, file_path.name, re.IGNORECASE):
                return ValidationResult(
                    quality=DocumentQuality.SKIP,
                    skip_reason=SkipReason.TEMP_FILE,
                    metadata=metadata
                )
        
        # Check supported extension
        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            return ValidationResult(
                quality=DocumentQuality.SKIP,
                skip_reason=SkipReason.UNSUPPORTED_FORMAT,
                metadata=metadata
            )
        
        metadata["doc_category"] = self.SUPPORTED_EXTENSIONS[ext]
        
        # Check file size
        if metadata["file_size"] == 0:
            return ValidationResult(
                quality=DocumentQuality.SKIP,
                skip_reason=SkipReason.EMPTY_FILE,
                metadata=metadata
            )
        
        # Check for low-value document types based on filename
        name_lower = file_path.name.lower()
        for pattern in self.LOW_VALUE_PATTERNS:
            if re.search(pattern, name_lower, re.IGNORECASE):
                warnings.append(f"Filename suggests low-value content: {pattern}")
        
        # File-level validation passed - content validation happens after extraction
        quality = DocumentQuality.HIGH if not warnings else DocumentQuality.MEDIUM
        
        return ValidationResult(
            quality=quality,
            warnings=warnings,
            metadata=metadata
        )
    
    def validate_extracted_content(
        self,
        file_path: Path,
        pages: List[Dict],
        pre_validation: ValidationResult
    ) -> ValidationResult:
        """
        Validate extracted content quality.
        
        Args:
            file_path: Original file path
            pages: Extracted pages with text and metadata
            pre_validation: Result from validate_file()
        
        Returns:
            Updated ValidationResult
        """
        warnings = list(pre_validation.warnings)
        metadata = dict(pre_validation.metadata)
        
        # Calculate total text and stats
        total_text = ""
        total_chars = 0
        total_words = 0
        avg_ocr_confidence = 0.0
        ocr_page_count = 0
        
        for page in pages:
            text = page.get("text", "")
            total_text += text + "\n"
            total_chars += len(text)
            total_words += len(text.split())
            
            if page.get("ocr_confidence", 0) > 0:
                avg_ocr_confidence += page["ocr_confidence"]
                ocr_page_count += 1
        
        if ocr_page_count > 0:
            avg_ocr_confidence /= ocr_page_count
        
        metadata["total_chars"] = total_chars
        metadata["total_words"] = total_words
        metadata["page_count"] = len(pages)
        metadata["avg_ocr_confidence"] = round(avg_ocr_confidence, 3)
        
        # Check minimum text requirements
        if total_chars < self.min_text_length:
            return ValidationResult(
                quality=DocumentQuality.SKIP,
                skip_reason=SkipReason.INSUFFICIENT_TEXT,
                warnings=warnings,
                metadata=metadata
            )
        
        if total_words < self.min_words:
            return ValidationResult(
                quality=DocumentQuality.SKIP,
                skip_reason=SkipReason.INSUFFICIENT_TEXT,
                warnings=warnings,
                metadata=metadata
            )
        
        # Check OCR confidence for image-based documents
        if ocr_page_count > 0 and avg_ocr_confidence < self.min_ocr_confidence:
            # Low confidence but some text - mark as low quality, don't skip
            warnings.append(f"Low OCR confidence: {avg_ocr_confidence:.2f}")
            return ValidationResult(
                quality=DocumentQuality.LOW,
                warnings=warnings,
                metadata=metadata
            )
        
        # Check for duplicate content
        if self.check_duplicates:
            content_hash = hashlib.md5(total_text.encode()).hexdigest()
            if content_hash in self._content_hashes:
                original = self._content_hashes[content_hash]
                warnings.append(f"Duplicate of: {original}")
                return ValidationResult(
                    quality=DocumentQuality.SKIP,
                    skip_reason=SkipReason.DUPLICATE,
                    warnings=warnings,
                    metadata=metadata
                )
            self._content_hashes[content_hash] = str(file_path)
        
        # Determine final quality
        if warnings:
            quality = DocumentQuality.MEDIUM
        elif total_words > 100 and (ocr_page_count == 0 or avg_ocr_confidence > 0.8):
            quality = DocumentQuality.HIGH
        else:
            quality = DocumentQuality.MEDIUM
        
        return ValidationResult(
            quality=quality,
            warnings=warnings,
            metadata=metadata
        )
    
    def reset_duplicate_tracking(self) -> None:
        """Reset duplicate tracking for new ingestion batch."""
        self._content_hashes.clear()
    
    def get_duplicate_stats(self) -> Dict[str, int]:
        """Get stats about tracked documents."""
        return {
            "unique_documents": len(self._content_hashes)
        }
