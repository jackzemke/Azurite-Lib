"""
Enhanced Ingest endpoint for document processing.

Key improvements:
1. Document quality validation before processing
2. Standardized project identification (folder_name, file_id, project_key)
3. Enhanced chunking with context preservation
4. Resilient error handling with partial success
5. Detailed ingestion reports
"""

from fastapi import APIRouter, HTTPException
from pathlib import Path
from typing import List, Dict, Optional, Any
import json
import logging
import time
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

from ..schemas.models import IngestRequest, IngestResponse, AsyncIngestResponse
from ..core.extractors.pdf_extractor import PDFExtractor
from ..core.extractors.docx_extractor import DOCXExtractor
from ..core.extractors.image_ocr import ImageOCR
from ..core.normalizer import Normalizer
from ..core.enhanced_chunker import EnhancedChunker
from ..core.embedder import Embedder
from ..core.indexer import Indexer
from ..core.document_validator import DocumentValidator, DocumentQuality, SkipReason
from ..core.project_mapper import get_project_mapper
from ..core.filesystem_scanner import FileSystemProjectScanner
from ..core.job_queue import get_job_queue

logger = logging.getLogger(__name__)
router = APIRouter()


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


def get_config():
    """Load config."""
    import yaml
    config_path = Path("/home/jack/lib/project-library/app/backend/config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def resolve_project_identifiers(project_folder: str, raw_docs_path: Path) -> Dict[str, Optional[str]]:
    """
    Resolve all project identifiers for a folder.
    
    Args:
        project_folder: The folder name (what user provides)
        raw_docs_path: Base path to raw_docs
    
    Returns:
        Dict with 'folder_name', 'file_id', 'project_key'
    """
    result = {
        "folder_name": project_folder,
        "file_id": None,
        "project_key": None,
    }
    
    try:
        # Use file system scanner to extract IDs from folder structure
        scanner = FileSystemProjectScanner(str(raw_docs_path))
        scanner.scan()
        
        project_info = scanner.projects.get(project_folder)
        if project_info and project_info.get("file_ids"):
            result["file_id"] = project_info["file_ids"][0]
        
        # Use project mapper to get Ajera key
        try:
            mapper = get_project_mapper()
            if result["file_id"]:
                result["project_key"] = mapper.get_project_key(result["file_id"])
        except RuntimeError:
            # Mapper not initialized - that's okay
            pass
        
    except Exception as e:
        logger.warning(f"Could not resolve all project identifiers: {e}")
    
    return result


@router.post("/projects/{project_id}/ingest/async", response_model=AsyncIngestResponse)
async def ingest_project_async(
    project_id: str,
    request: IngestRequest = IngestRequest(),
):
    """
    Queue document ingestion as a background job.
    
    This endpoint returns immediately with a job_id that can be used
    to track progress. Use GET /api/v1/jobs/{job_id} to check status.
    
    This is the recommended endpoint for large projects with many files,
    as it doesn't block the request while processing.
    
    Process:
    1. Validate project folder exists
    2. Queue ingestion job for background processing
    3. Return job_id immediately
    
    The background job will:
    - Discover and validate documents
    - Extract text from valid documents
    - Chunk with context preservation
    - Generate embeddings
    - Index in ChromaDB
    - Generate detailed report
    
    Poll GET /api/v1/jobs/{job_id} to check:
    - Progress percentage
    - Files processed so far
    - Any errors encountered
    - Final result when complete
    """
    config = get_config()
    
    # Validate project directory exists before queuing
    raw_docs_dir = Path(config["paths"]["raw_docs"]) / project_id
    if not raw_docs_dir.exists():
        raise HTTPException(
            status_code=404, 
            detail=f"Project directory not found: {raw_docs_dir}. "
                   f"Upload files first using POST /projects/{project_id}/upload"
        )
    
    # Check for files
    supported_exts = {'.pdf', '.docx', '.doc', '.xlsx', '.xls', '.png', '.jpg', '.jpeg', '.tiff', '.bmp'}
    files_to_process = []
    for ext in supported_exts:
        files_to_process.extend(raw_docs_dir.rglob(f"*{ext}"))
    files_to_process = [f for f in files_to_process if f.is_file() and not f.name.startswith('~$')]
    
    if not files_to_process:
        raise HTTPException(
            status_code=400,
            detail=f"No supported files found in {raw_docs_dir}. "
                   f"Supported formats: {', '.join(supported_exts)}"
        )
    
    # Queue the job
    queue = get_job_queue()
    job_id = queue.enqueue_ingest(
        project_id=project_id,
        files=request.files,
    )
    
    logger.info(f"Queued async ingest job {job_id} for project {project_id} ({len(files_to_process)} files)")
    
    return AsyncIngestResponse(
        job_id=job_id,
        project_id=project_id,
        message=f"Ingestion queued for {len(files_to_process)} files. Poll status URL for progress.",
        status_url=f"/api/v1/jobs/{job_id}",
    )


@router.post("/projects/{project_id}/ingest", response_model=IngestResponse)
async def ingest_project(
    project_id: str,
    request: IngestRequest = IngestRequest(),
):
    """
    Ingest documents for a project with enhanced processing (SYNCHRONOUS).
    
    NOTE: For large projects, consider using POST /projects/{project_id}/ingest/async
    which returns immediately and processes in the background.

    Process:
    1. Validate project folder exists
    2. Resolve project identifiers (folder_name, file_id, project_key)
    3. Discover and validate documents
    4. Extract text from valid documents
    5. Chunk with context preservation
    6. Generate embeddings
    7. Index in ChromaDB with rich metadata
    8. Generate detailed report

    Features:
    - Skips low-quality documents (insufficient text, corrupted)
    - Detects and skips duplicates
    - Preserves document structure in chunks
    - Adds context to each chunk for better retrieval
    - Continues processing even if some files fail
    """
    start_time = time.time()
    
    try:
        config = get_config()
        
        # Validate project directory
        raw_docs_dir = Path(config["paths"]["raw_docs"]) / project_id
        if not raw_docs_dir.exists():
            raise HTTPException(
                status_code=404, 
                detail=f"Project directory not found: {raw_docs_dir}. "
                       f"Upload files first using POST /projects/{project_id}/upload"
            )
        
        # Resolve all project identifiers
        project_ids = resolve_project_identifiers(project_id, Path(config["paths"]["raw_docs"]))
        logger.info(f"Project identifiers: {project_ids}")
        
        # Initialize components
        validator = DocumentValidator(
            min_text_length=config["ocr"]["min_text_length"],
            min_ocr_confidence=0.6,
            min_words=20,
        )
        
        pdf_extractor = PDFExtractor(min_text_length=config["ocr"]["min_text_length"])
        docx_extractor = DOCXExtractor()
        image_ocr = ImageOCR(lang=config["ocr"]["tesseract_lang"])
        normalizer = Normalizer()
        
        chunker = EnhancedChunker(
            chunk_size_tokens=config["chunking"]["chunk_size_tokens"],
            chunk_overlap_tokens=config["chunking"]["chunk_overlap_tokens"],
            add_context_prefix=True,
            preserve_tables=True,
        )
        
        embedder = Embedder(
            model_name=config["embedding"]["model_name"],
            batch_size=config["embedding"]["batch_size"],
        )
        
        indexer = Indexer(
            chroma_db_path=Path(config["paths"]["chroma_db"]),
        )
        
        # Discover files - prioritize text-rich formats for faster ingestion
        # For pilot: Focus on PDFs and DOCX which have the best Q&A value
        primary_exts = {'.pdf', '.docx', '.doc'}  # High-value, fast to process
        image_exts = {'.png', '.jpg', '.jpeg', '.tiff', '.bmp'}  # Slow OCR, often low value
        
        # Folders to skip (usually contain images/CAD with minimal Q&A value)
        skip_folder_patterns = ['/Photos/', '/photos/', '/Images/', '/images/', '/CAD/', '/cad/']
        
        # Max image size to process (skip large site photos)
        max_image_size_mb = 2.0
        
        if request.files:
            files_to_process = [raw_docs_dir / f for f in request.files]
        else:
            files_to_process = []
            
            # First, get all primary documents (PDFs, DOCX)
            for ext in primary_exts:
                files_to_process.extend(raw_docs_dir.rglob(f"*{ext}"))
            
            # Then, selectively add images (skip large photos and image folders)
            for ext in image_exts:
                for f in raw_docs_dir.rglob(f"*{ext}"):
                    # Skip files in image/photo folders
                    if any(pattern in str(f) for pattern in skip_folder_patterns):
                        logger.debug(f"Skipping image in excluded folder: {f.name}")
                        continue
                    # Skip large images (likely site photos)
                    try:
                        size_mb = f.stat().st_size / (1024 * 1024)
                        if size_mb > max_image_size_mb:
                            logger.debug(f"Skipping large image ({size_mb:.1f}MB): {f.name}")
                            continue
                    except:
                        pass
                    files_to_process.append(f)
            
            # Filter temp files
            files_to_process = [f for f in files_to_process if f.is_file() and not f.name.startswith('~$')]
        
        supported_exts = primary_exts | image_exts
        if not files_to_process:
            raise HTTPException(
                status_code=400, 
                detail=f"No supported files found in {raw_docs_dir}. "
                       f"Supported formats: {', '.join(supported_exts)}"
            )
        
        logger.info(f"Found {len(files_to_process)} files to process for project {project_id} (skipped large images and photo folders)")
        
        # Process files
        all_chunks = []
        processing_results: List[FileProcessingResult] = []
        
        for idx, file_path in enumerate(files_to_process, 1):
            result = FileProcessingResult(
                file_name=file_path.name,
                file_path=str(file_path),
                status=ProcessingStatus.FAILED,
            )
            
            try:
                logger.info(f"Processing {idx}/{len(files_to_process)}: {file_path.name}")
                
                # Step 1: Pre-validation
                pre_validation = validator.validate_file(file_path)
                
                if not pre_validation.should_index:
                    result.status = ProcessingStatus.SKIPPED
                    result.skip_reason = pre_validation.skip_reason.value if pre_validation.skip_reason else "unknown"
                    result.quality = pre_validation.quality.value
                    result.warnings = pre_validation.warnings
                    processing_results.append(result)
                    logger.info(f"  ⏭ Skipped: {result.skip_reason}")
                    continue
                
                # Step 2: Extract text
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
                
                # Step 3: Post-extraction validation
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
                
                # Step 4: Normalize text
                for page in extracted["pages"]:
                    page["text"], _ = normalizer.normalize_text(page["text"])
                
                # Step 5: Chunk with enhanced context
                chunks = chunker.chunk_document(
                    pages=extracted["pages"],
                    project_id=project_ids["folder_name"],  # Use folder name for ChromaDB
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
                
                # Step 6: Save chunks to disk
                chunks_dir = Path(config["paths"]["chunks"]) / project_id
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
                logger.error(f"  ✗ Failed to process {file_path.name}: {e}")
        
        # Generate embeddings and index
        if all_chunks:
            logger.info(f"Generating embeddings for {len(all_chunks)} chunks...")
            embeddings = embedder.embed_chunks(all_chunks)
            
            # Save embeddings
            embeddings_file = Path(config["paths"]["embeddings"]) / f"{project_id}.parquet"
            embeddings_file.parent.mkdir(parents=True, exist_ok=True)
            embedder.save_embeddings(embeddings, embeddings_file)
            
            # Index in ChromaDB
            logger.info("Indexing chunks in ChromaDB...")
            indexer.upsert_chunks(all_chunks, embeddings)
            logger.info(f"✓ Indexed {len(all_chunks)} chunks successfully")
        
        # Calculate stats
        duration = time.time() - start_time
        success_count = sum(1 for r in processing_results if r.status == ProcessingStatus.SUCCESS)
        skipped_count = sum(1 for r in processing_results if r.status == ProcessingStatus.SKIPPED)
        failed_count = sum(1 for r in processing_results if r.status == ProcessingStatus.FAILED)
        
        # Build detailed report
        def serialize_result(r):
            """Convert FileProcessingResult to JSON-serializable dict."""
            d = asdict(r)
            d['status'] = r.status.value  # Convert enum to string
            return d
        
        report = {
            "project_id": project_id,
            "project_identifiers": project_ids,
            "files_found": len(files_to_process),
            "files_processed": success_count,
            "files_skipped": skipped_count,
            "files_failed": failed_count,
            "chunks_created": len(all_chunks),
            "duration_seconds": round(duration, 2),
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "file_details": [serialize_result(r) for r in processing_results],
            "skip_reasons": {},
            "errors": [],
        }
        
        # Summarize skip reasons
        for r in processing_results:
            if r.status == ProcessingStatus.SKIPPED and r.skip_reason:
                report["skip_reasons"][r.skip_reason] = report["skip_reasons"].get(r.skip_reason, 0) + 1
            if r.status == ProcessingStatus.FAILED and r.error_message:
                report["errors"].append(f"{r.file_name}: {r.error_message}")
        
        # Save report
        report_file = Path(config["paths"]["chunks"]).parent / "logs" / f"ingest_report_{project_id}.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"✓ Ingestion complete: {success_count} processed, {skipped_count} skipped, {failed_count} failed")
        
        return IngestResponse(
            project_id=project_id,
            files_processed=success_count,
            chunks_created=len(all_chunks),
            errors=report["errors"],
            duration_seconds=round(duration, 2),
            timestamp=report["timestamp"],
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@router.delete("/projects/{project_id}/index")
async def clear_project_index(project_id: str):
    """
    Clear indexed chunks for a project from ChromaDB.
    
    Use this before re-ingesting to avoid duplicates.
    Does NOT delete the original documents or chunk JSON files.
    """
    try:
        config = get_config()
        indexer = Indexer(chroma_db_path=Path(config["paths"]["chroma_db"]))
        
        # Get count before deletion
        results = indexer.collection.get(
            where={"project_id": project_id},
            include=[]
        )
        count_before = len(results["ids"]) if results["ids"] else 0
        
        if count_before == 0:
            return {"message": f"No chunks found for project {project_id}", "deleted": 0}
        
        # Delete chunks
        indexer.collection.delete(
            where={"project_id": project_id}
        )
        
        logger.info(f"Deleted {count_before} chunks for project {project_id}")
        
        return {
            "message": f"Successfully cleared index for project {project_id}",
            "deleted": count_before
        }
    
    except Exception as e:
        logger.error(f"Failed to clear index: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear index: {str(e)}")


@router.get("/projects/{project_id}/index/stats")
async def get_project_index_stats(project_id: str):
    """
    Get indexing statistics for a project.
    
    Returns chunk counts, document coverage, and quality metrics.
    """
    try:
        config = get_config()
        indexer = Indexer(chroma_db_path=Path(config["paths"]["chroma_db"]))
        
        # Get all chunks for project
        results = indexer.collection.get(
            where={"project_id": project_id},
            include=["metadatas"]
        )
        
        if not results["ids"]:
            return {
                "project_id": project_id,
                "indexed": False,
                "chunk_count": 0,
            }
        
        # Analyze metadata
        files = set()
        doc_types = {}
        
        for meta in results["metadatas"]:
            files.add(meta.get("file_basename", "unknown"))
            doc_type = meta.get("doc_type", "unknown")
            doc_types[doc_type] = doc_types.get(doc_type, 0) + 1
        
        return {
            "project_id": project_id,
            "indexed": True,
            "chunk_count": len(results["ids"]),
            "file_count": len(files),
            "doc_types": doc_types,
            "files": list(files)[:20],  # First 20 files
        }
    
    except Exception as e:
        logger.error(f"Failed to get index stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get index stats: {str(e)}")
