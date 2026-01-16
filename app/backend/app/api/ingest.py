"""
Ingest endpoint for document processing.
"""

from fastapi import APIRouter, HTTPException
from pathlib import Path
from typing import List, Dict
import json
import logging
import time
from datetime import datetime

from ..schemas.models import IngestRequest, IngestResponse
from ..core.extractors.pdf_extractor import PDFExtractor
from ..core.extractors.docx_extractor import DOCXExtractor
from ..core.extractors.image_ocr import ImageOCR
from ..core.normalizer import Normalizer
from ..core.chunker import Chunker
from ..core.embedder import Embedder
from ..core.indexer import Indexer

logger = logging.getLogger(__name__)
router = APIRouter()


def get_config():
    """Load config (simplified - would use dependency injection in production)."""
    import yaml
    config_path = Path("/home/jack/lib/project-library/app/backend/config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


@router.post("/projects/{project_id}/ingest", response_model=IngestResponse)
async def ingest_project(
    project_id: str,
    request: IngestRequest = IngestRequest(),
):
    """
    Ingest documents for a project.

    Steps:
    1. Extract text from documents
    2. Normalize text
    3. Chunk documents
    4. Generate embeddings
    5. Index in Chroma
    """
    start_time = time.time()

    try:
        config = get_config()

        # Get raw docs directory
        raw_docs_dir = Path(config["paths"]["raw_docs"]) / project_id
        if not raw_docs_dir.exists():
            raise HTTPException(status_code=404, detail=f"Project directory not found: {raw_docs_dir}")

        # Get list of files to process (recursively scan subdirectories)
        supported_exts = {'.pdf', '.docx', '.doc', '.xlsx', '.xls', '.png', '.jpg', '.jpeg', '.tiff', '.bmp'}
        
        if request.files:
            files_to_process = [raw_docs_dir / f for f in request.files]
        else:
            # Process all supported files in directory and subdirectories
            files_to_process = []
            for ext in supported_exts:
                files_to_process.extend(raw_docs_dir.rglob(f"*{ext}"))
            # Filter out temp files (Office lock files starting with ~$)
            files_to_process = [f for f in files_to_process if f.is_file() and not f.name.startswith('~$')]

        if not files_to_process:
            raise HTTPException(status_code=400, detail="No supported files found to process")

        logger.info(f"Ingesting {len(files_to_process)} files for project {project_id}")

        # Initialize components
        pdf_extractor = PDFExtractor(min_text_length=config["ocr"]["min_text_length"])
        docx_extractor = DOCXExtractor()
        image_ocr = ImageOCR(lang=config["ocr"]["tesseract_lang"])
        normalizer = Normalizer()
        chunker = Chunker(
            chunk_size_tokens=config["chunking"]["chunk_size_tokens"],
            chunk_overlap_tokens=config["chunking"]["chunk_overlap_tokens"],
            semantic=config["chunking"]["semantic"],
        )
        embedder = Embedder(
            model_name=config["embedding"]["model_name"],
            batch_size=config["embedding"]["batch_size"],
        )
        indexer = Indexer(
            chroma_db_path=Path(config["paths"]["chroma_db"]),
        )

        # Process files
        all_chunks = []
        errors = []

        for idx, file_path in enumerate(files_to_process, 1):
            try:
                logger.info(f"Processing {idx}/{len(files_to_process)}: {file_path.name}")

                # Extract
                doc_type = file_path.suffix.lower().lstrip('.')
                if doc_type == 'pdf':
                    extracted = pdf_extractor.extract(file_path)
                elif doc_type in ['docx', 'doc']:
                    extracted = docx_extractor.extract(file_path)
                elif doc_type in ['png', 'jpg', 'jpeg', 'tiff', 'bmp']:
                    extracted = image_ocr.extract_standalone_image(file_path)
                else:
                    logger.warning(f"Unsupported file type: {doc_type}")
                    errors.append(f"{file_path.name}: unsupported type")
                    continue

                # Normalize
                for page in extracted["pages"]:
                    page["text"], metadata = normalizer.normalize_text(page["text"])

                # Chunk
                chunks = chunker.chunk_document(
                    pages=extracted["pages"],
                    project_id=project_id,
                    file_path=file_path,
                    file_basename=file_path.name,
                    doc_type=doc_type,
                )

                # Save chunks to disk
                chunks_dir = Path(config["paths"]["chunks"]) / project_id
                chunks_dir.mkdir(parents=True, exist_ok=True)

                for chunk in chunks:
                    chunk_file = chunks_dir / f"{chunk['chunk_id']}.json"
                    with open(chunk_file, 'w') as f:
                        json.dump(chunk, f, indent=2)

                all_chunks.extend(chunks)
                if len(chunks) == 0:
                    logger.warning(f"⚠ Created 0 chunks from {file_path.name} (likely image-only or corrupted)")
                else:
                    logger.info(f"Created {len(chunks)} chunks from {file_path.name}")

            except Exception as e:
                logger.error(f"Failed to process {file_path.name}: {e}")
                errors.append(f"{file_path.name}: {str(e)}")

        # Generate embeddings
        if all_chunks:
            logger.info(f"✓ Extracted {len(files_to_process) - len(errors)} files, created {len(all_chunks)} chunks")
            logger.info(f"Generating embeddings for {len(all_chunks)} chunks (this may take a few minutes)...")
            embeddings = embedder.embed_chunks(all_chunks)

            # Save embeddings
            embeddings_file = Path(config["paths"]["embeddings"]) / f"{project_id}.parquet"
            embedder.save_embeddings(embeddings, embeddings_file)

            # Index in Chroma
            logger.info("Indexing chunks in ChromaDB vector store...")
            indexer.upsert_chunks(all_chunks, embeddings)
            logger.info(f"✓ Indexed {len(all_chunks)} chunks successfully")

        # Save ingestion report
        duration = time.time() - start_time
        report = {
            "project_id": project_id,
            "files_processed": len(files_to_process) - len(errors),
            "chunks_created": len(all_chunks),
            "errors": errors,
            "duration_seconds": round(duration, 2),
            "timestamp": datetime.utcnow().isoformat() + 'Z',
        }

        report_file = Path(config["paths"]["chunks"]).parent / "logs" / f"ingest_report_{project_id}.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)

        return IngestResponse(**report)

    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")
