"""
Background Ingest Worker for document processing.

This module contains the actual ingestion logic that runs as a background job.
It's designed to be executed by RQ workers and provides progress updates
throughout the process.

Usage (from RQ worker):
    rq worker ingestion --with-scheduler

The job will:
1. Validate project directory
2. Discover files to process
3. Extract, chunk, and embed each file (with progress updates)
4. Index all chunks in ChromaDB
5. Generate and save a detailed report
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

# RQ imports for progress updates
try:
    from rq import get_current_job
    RQ_AVAILABLE = True
except ImportError:
    RQ_AVAILABLE = False
    def get_current_job():
        return None

from ..config import settings

logger = logging.getLogger(__name__)


class ProcessingStatus(Enum):
    """Document processing status."""
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class FileProcessingResult:
    """Result of processing a single file."""
    file_name: str
    file_path: str
    status: ProcessingStatus
    chunks_created: int = 0
    skip_reason: Optional[str] = None
    error_message: Optional[str] = None
    quality: Optional[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def update_progress(
    progress: float,
    message: str,
    files_processed: int = 0,
    chunks_created: int = 0,
    errors: List[str] = None,
):
    """Update job progress if running in RQ context."""
    job = get_current_job()
    if job is None:
        # Not running in RQ context, just log
        logger.info(f"Progress: {progress:.1f}% - {message}")
        return
    
    meta = job.meta or {}
    meta["progress"] = min(100.0, max(0.0, progress))
    meta["message"] = message
    meta["files_processed"] = files_processed
    meta["chunks_created"] = chunks_created
    if errors is not None:
        meta["errors"] = errors
    
    job.meta = meta
    job.save_meta()


def run_ingest_job(
    project_id: str,
    files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Execute document ingestion as a background job.
    
    This is the main entry point for async ingestion. It performs the full
    pipeline: validation → extraction → chunking → embedding → indexing.
    
    Args:
        project_id: Project folder name (e.g., "demo_project")
        files: Optional list of specific files to process
    
    Returns:
        Dict with ingestion results including counts and any errors
    """
    start_time = time.time()
    errors = []
    
    # Initialize job metadata
    job = get_current_job()
    if job:
        job.meta = {
            "project_id": project_id,
            "files_total": 0,
            "files_processed": 0,
            "chunks_created": 0,
            "progress": 0.0,
            "message": "Initializing...",
            "errors": [],
        }
        job.save_meta()
    
    try:
        # Import here to avoid circular dependencies and ensure fresh imports
        from ..core.extractors.pdf_extractor import PDFExtractor
        from ..core.extractors.docx_extractor import DOCXExtractor
        from ..core.extractors.image_ocr import ImageOCR
        from ..core.normalizer import Normalizer
        from ..core.enhanced_chunker import EnhancedChunker
        from ..core.embedder import Embedder
        from ..core.indexer import Indexer
        from ..core.document_validator import DocumentValidator
        from ..core.project_mapper import get_project_mapper
        from ..core.filesystem_scanner import FileSystemProjectScanner

        update_progress(1, "Loading configuration...")
        
        # Validate project directory
        raw_docs_dir = settings.raw_docs_path / project_id
        if not raw_docs_dir.exists():
            raise ValueError(
                f"Project directory not found: {raw_docs_dir}. "
                f"Upload files first using POST /projects/{project_id}/upload"
            )
        
        update_progress(2, "Resolving project identifiers...")
        
        # Resolve project identifiers
        project_ids = _resolve_project_identifiers(project_id, settings.raw_docs_path)
        logger.info(f"Project identifiers: {project_ids}")
        
        update_progress(5, "Initializing components...")
        
        # Initialize components
        validator = DocumentValidator(
            min_text_length=settings.ocr_min_text_length,
            min_ocr_confidence=0.6,
            min_words=20,
        )
        
        pdf_extractor = PDFExtractor(min_text_length=settings.ocr_min_text_length)
        docx_extractor = DOCXExtractor()
        image_ocr = ImageOCR(lang=settings.ocr_tesseract_lang)
        normalizer = Normalizer()
        
        chunker = EnhancedChunker(
            chunk_size_tokens=settings.chunking_chunk_size_tokens,
            chunk_overlap_tokens=settings.chunking_chunk_overlap_tokens,
            add_context_prefix=True,
            preserve_tables=True,
        )
        
        embedder = Embedder(
            model_name=settings.embedding_model_name,
            batch_size=settings.embedding_batch_size,
        )
        
        indexer = Indexer(
            chroma_db_path=settings.chroma_db_path,
        )
        
        update_progress(8, "Discovering files...")
        
        # Discover files
        supported_exts = {'.pdf', '.docx', '.doc', '.xlsx', '.xls', '.png', '.jpg', '.jpeg', '.tiff', '.bmp'}
        
        if files:
            files_to_process = [raw_docs_dir / f for f in files]
        else:
            files_to_process = []
            for ext in supported_exts:
                files_to_process.extend(raw_docs_dir.rglob(f"*{ext}"))
            # Filter temp files
            files_to_process = [f for f in files_to_process if f.is_file() and not f.name.startswith('~$')]
        
        files_to_process = sorted(files_to_process)
        total_files = len(files_to_process)
        
        if total_files == 0:
            raise ValueError(
                f"No supported files found in {raw_docs_dir}. "
                f"Supported formats: {', '.join(supported_exts)}"
            )
        
        # Update job with file count
        if job:
            job.meta["files_total"] = total_files
            job.save_meta()
        
        logger.info(f"Found {total_files} files to process for project {project_id}")
        update_progress(10, f"Found {total_files} files to process")
        
        # Process files (10% - 80% of progress)
        all_chunks = []
        processing_results: List[FileProcessingResult] = []
        
        for idx, file_path in enumerate(files_to_process, 1):
            # Calculate progress (10% - 80% range for file processing)
            file_progress = 10 + (idx / total_files) * 70
            update_progress(
                file_progress,
                f"Processing {idx}/{total_files}: {file_path.name}",
                files_processed=idx - 1,
                chunks_created=len(all_chunks),
                errors=errors,
            )
            
            result = FileProcessingResult(
                file_name=file_path.name,
                file_path=str(file_path),
                status=ProcessingStatus.FAILED,
            )
            
            try:
                logger.info(f"Processing {idx}/{total_files}: {file_path.name}")
                
                # Pre-validation
                pre_validation = validator.validate_file(file_path)
                
                if not pre_validation.should_index:
                    result.status = ProcessingStatus.SKIPPED
                    result.skip_reason = pre_validation.skip_reason.value if pre_validation.skip_reason else "unknown"
                    result.quality = pre_validation.quality.value
                    result.warnings = pre_validation.warnings
                    processing_results.append(result)
                    logger.info(f"  ⏭ Skipped: {result.skip_reason}")
                    continue
                
                # Extract text
                doc_type = file_path.suffix.lower().lstrip('.')
                
                if doc_type == 'pdf':
                    extracted = pdf_extractor.extract(file_path)
                elif doc_type in ['docx', 'doc']:
                    extracted = docx_extractor.extract(file_path)
                elif doc_type in ['png', 'jpg', 'jpeg', 'tiff', 'bmp']:
                    extracted = image_ocr.extract_standalone_image(file_path)
                else:
                    result.skip_reason = "unsupported_type"
                    result.status = ProcessingStatus.SKIPPED
                    processing_results.append(result)
                    continue
                
                # Post-extraction validation
                post_validation = validator.validate_extracted_content(
                    file_path, 
                    extracted["pages"],
                    pre_validation
                )
                
                if not post_validation.should_index:
                    result.status = ProcessingStatus.SKIPPED
                    result.skip_reason = post_validation.skip_reason.value if post_validation.skip_reason else "unknown"
                    result.quality = post_validation.quality.value
                    result.warnings = post_validation.warnings
                    processing_results.append(result)
                    logger.info(f"  ⏭ Skipped after extraction: {result.skip_reason}")
                    continue
                
                result.quality = post_validation.quality.value
                result.warnings = post_validation.warnings
                
                # Normalize text
                for page in extracted["pages"]:
                    page["text"], _ = normalizer.normalize_text(page["text"])
                
                # Chunk with enhanced context
                chunks = chunker.chunk_document(
                    pages=extracted["pages"],
                    project_id=project_ids["folder_name"],
                    file_path=file_path,
                    file_id=project_ids["file_id"],
                    project_key=project_ids["project_key"],
                    doc_type=doc_type,
                )
                
                if not chunks:
                    result.status = ProcessingStatus.SKIPPED
                    result.skip_reason = "no_chunks_created"
                    processing_results.append(result)
                    logger.warning(f"  ⚠ No chunks created from {file_path.name}")
                    continue
                
                # Save chunks to disk
                chunks_dir = settings.chunks_path / project_id
                chunks_dir.mkdir(parents=True, exist_ok=True)
                
                for chunk in chunks:
                    chunk_file = chunks_dir / f"{chunk['chunk_id']}.json"
                    with open(chunk_file, 'w') as f:
                        json.dump(chunk, f, indent=2)
                
                all_chunks.extend(chunks)
                
                result.status = ProcessingStatus.SUCCESS
                result.chunks_created = len(chunks)
                processing_results.append(result)
                
                logger.info(f"  ✓ Created {len(chunks)} chunks (quality: {result.quality})")
                
            except Exception as e:
                result.status = ProcessingStatus.FAILED
                result.error_message = str(e)
                processing_results.append(result)
                errors.append(f"{file_path.name}: {str(e)}")
                logger.error(f"  ✗ Failed to process {file_path.name}: {e}")
        
        # Generate embeddings and index (80% - 95%)
        update_progress(
            80,
            f"Generating embeddings for {len(all_chunks)} chunks...",
            files_processed=total_files,
            chunks_created=len(all_chunks),
            errors=errors,
        )
        
        if all_chunks:
            logger.info(f"Generating embeddings for {len(all_chunks)} chunks...")
            embeddings = embedder.embed_chunks(all_chunks)
            
            update_progress(90, "Saving embeddings...")
            
            # Save embeddings
            embeddings_file = settings.embeddings_path / f"{project_id}.parquet"
            embeddings_file.parent.mkdir(parents=True, exist_ok=True)
            embedder.save_embeddings(embeddings, embeddings_file)
            
            update_progress(92, "Indexing chunks in ChromaDB...")
            
            # Index in ChromaDB
            logger.info("Indexing chunks in ChromaDB...")
            indexer.upsert_chunks(all_chunks, embeddings)
            logger.info(f"✓ Indexed {len(all_chunks)} chunks successfully")
        
        update_progress(95, "Generating report...")
        
        # Calculate stats
        duration = time.time() - start_time
        success_count = sum(1 for r in processing_results if r.status == ProcessingStatus.SUCCESS)
        skipped_count = sum(1 for r in processing_results if r.status == ProcessingStatus.SKIPPED)
        failed_count = sum(1 for r in processing_results if r.status == ProcessingStatus.FAILED)
        
        # Build report
        def serialize_result(r):
            d = asdict(r)
            d['status'] = r.status.value
            return d
        
        report = {
            "project_id": project_id,
            "project_identifiers": project_ids,
            "files_found": total_files,
            "files_processed": success_count,
            "files_skipped": skipped_count,
            "files_failed": failed_count,
            "chunks_created": len(all_chunks),
            "duration_seconds": round(duration, 2),
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "file_details": [serialize_result(r) for r in processing_results],
            "skip_reasons": {},
            "errors": errors,
        }
        
        # Summarize skip reasons
        for r in processing_results:
            if r.status == ProcessingStatus.SKIPPED and r.skip_reason:
                report["skip_reasons"][r.skip_reason] = report["skip_reasons"].get(r.skip_reason, 0) + 1
        
        # Save report
        report_file = settings.chunks_path.parent / "logs" / f"ingest_report_{project_id}.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        update_progress(
            100,
            f"✓ Complete: {success_count} processed, {skipped_count} skipped, {failed_count} failed",
            files_processed=success_count,
            chunks_created=len(all_chunks),
            errors=errors,
        )
        
        logger.info(f"✓ Ingestion complete: {success_count} processed, {skipped_count} skipped, {failed_count} failed")
        
        return {
            "success": True,
            "project_id": project_id,
            "files_processed": success_count,
            "files_skipped": skipped_count,
            "files_failed": failed_count,
            "chunks_created": len(all_chunks),
            "errors": errors,
            "duration_seconds": round(duration, 2),
            "timestamp": report["timestamp"],
        }
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Ingestion job failed: {e}", exc_info=True)
        
        update_progress(
            0,
            f"Failed: {error_msg}",
            errors=[error_msg],
        )
        
        return {
            "success": False,
            "project_id": project_id,
            "error": error_msg,
            "duration_seconds": round(time.time() - start_time, 2),
        }


def _resolve_project_identifiers(project_folder: str, raw_docs_path: Path) -> Dict[str, Optional[str]]:
    """
    Resolve all project identifiers for a folder.
    
    Args:
        project_folder: The folder name
        raw_docs_path: Base path to raw_docs
    
    Returns:
        Dict with 'folder_name', 'file_id', 'project_key'
    """
    from ..core.project_mapper import get_project_mapper
    from ..core.filesystem_scanner import FileSystemProjectScanner
    
    result = {
        "folder_name": project_folder,
        "file_id": None,
        "project_key": None,
    }
    
    try:
        scanner = FileSystemProjectScanner(str(raw_docs_path))
        scanner.scan()
        
        project_info = scanner.projects.get(project_folder)
        if project_info and project_info.get("file_ids"):
            result["file_id"] = project_info["file_ids"][0]
        
        try:
            mapper = get_project_mapper()
            if result["file_id"]:
                result["project_key"] = mapper.get_project_key(result["file_id"])
        except RuntimeError:
            pass
        
    except Exception as e:
        logger.warning(f"Could not resolve all project identifiers: {e}")
    
    return result
