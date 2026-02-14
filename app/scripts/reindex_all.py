#!/usr/bin/env python3
"""
Re-index all projects with the new pipeline.

Necessary when the embedding model changes (384-dim -> 768-dim) since
the old vectors are incompatible with the new model. Creates a new
ChromaDB collection, re-processes all documents, and swaps on success.

Usage:
    python -m app.scripts.reindex_all
    python -m app.scripts.reindex_all --project demo_project
    python -m app.scripts.reindex_all --dry-run
"""

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.core.extractors.pdf_extractor import PDFExtractor
from app.core.extractors.docx_extractor import DOCXExtractor
from app.core.extractors.image_ocr import ImageOCR
from app.core.normalizer import Normalizer
from app.core.enhanced_chunker import EnhancedChunker
from app.core.embedder import Embedder
from app.core.indexer import Indexer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("reindex")

SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


def discover_projects(raw_docs_path: Path) -> list[str]:
    """Find all project directories under raw_docs."""
    projects = []
    if not raw_docs_path.exists():
        return projects
    for child in sorted(raw_docs_path.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            projects.append(child.name)
    return projects


def discover_files(project_dir: Path) -> list[Path]:
    """Find all supported files in a project directory."""
    files = []
    for ext in SUPPORTED_EXTS:
        files.extend(project_dir.rglob(f"*{ext}"))
    # Filter temp files
    files = [f for f in files if f.is_file() and not f.name.startswith("~$")]
    return sorted(files)


def process_file(
    file_path: Path,
    project_id: str,
    pdf_extractor: PDFExtractor,
    docx_extractor: DOCXExtractor,
    image_ocr: ImageOCR,
    normalizer: Normalizer,
    chunker: EnhancedChunker,
) -> list[dict]:
    """Extract and chunk a single file. Returns list of chunks."""
    doc_type = file_path.suffix.lower().lstrip(".")

    if doc_type == "pdf":
        extracted = pdf_extractor.extract(file_path)
    elif doc_type in ("docx", "doc"):
        extracted = docx_extractor.extract(file_path)
    elif doc_type in ("png", "jpg", "jpeg", "tiff", "bmp"):
        extracted = image_ocr.extract_standalone_image(file_path)
    else:
        return []

    # Normalize (extraction-only, text unchanged)
    for page in extracted["pages"]:
        page["text"], _ = normalizer.normalize_text(page["text"])

    # Chunk
    chunks = chunker.chunk_document(
        pages=extracted["pages"],
        project_id=project_id,
        file_path=file_path,
        file_id=None,
        project_key=None,
        doc_type=doc_type,
    )

    return chunks


def reindex_project(
    project_id: str,
    raw_docs_path: Path,
    pdf_extractor: PDFExtractor,
    docx_extractor: DOCXExtractor,
    image_ocr: ImageOCR,
    normalizer: Normalizer,
    chunker: EnhancedChunker,
    embedder: Embedder,
    indexer: Indexer,
    dry_run: bool = False,
) -> dict:
    """Re-index a single project. Returns stats dict."""
    project_dir = raw_docs_path / project_id
    files = discover_files(project_dir)

    stats = {
        "project_id": project_id,
        "files_found": len(files),
        "files_processed": 0,
        "files_failed": 0,
        "chunks_created": 0,
        "errors": [],
    }

    if not files:
        logger.warning(f"  No files found for {project_id}")
        return stats

    all_chunks = []

    for i, file_path in enumerate(files, 1):
        try:
            chunks = process_file(
                file_path, project_id,
                pdf_extractor, docx_extractor, image_ocr,
                normalizer, chunker,
            )
            all_chunks.extend(chunks)
            stats["files_processed"] += 1
            logger.info(f"  [{i}/{len(files)}] {file_path.name}: {len(chunks)} chunks")
        except Exception as e:
            stats["files_failed"] += 1
            stats["errors"].append(f"{file_path.name}: {e}")
            logger.error(f"  [{i}/{len(files)}] FAILED {file_path.name}: {e}")

    stats["chunks_created"] = len(all_chunks)

    if dry_run:
        logger.info(f"  [DRY RUN] Would embed and index {len(all_chunks)} chunks")
        return stats

    if all_chunks:
        logger.info(f"  Embedding {len(all_chunks)} chunks...")
        embeddings = embedder.embed_chunks(all_chunks)

        logger.info(f"  Indexing {len(all_chunks)} chunks in ChromaDB...")
        indexer.upsert_chunks(all_chunks, embeddings)

    return stats


def main():
    parser = argparse.ArgumentParser(description="Re-index all projects with new pipeline")
    parser.add_argument("--project", type=str, help="Re-index only this project")
    parser.add_argument("--dry-run", action="store_true", help="Process files but don't embed or index")
    parser.add_argument("--collection", type=str, default="project_docs_v2",
                        help="Name for new collection (default: project_docs_v2)")
    parser.add_argument("--swap", action="store_true",
                        help="After successful re-index, delete old collection and rename new one")
    args = parser.parse_args()

    raw_docs_path = settings.raw_docs_path
    chroma_db_path = settings.chroma_db_path

    logger.info("=" * 60)
    logger.info("AAA Re-indexing Script")
    logger.info(f"  Raw docs: {raw_docs_path}")
    logger.info(f"  ChromaDB: {chroma_db_path}")
    logger.info(f"  Collection: {args.collection}")
    logger.info(f"  Dry run: {args.dry_run}")
    logger.info("=" * 60)

    # Discover projects
    if args.project:
        projects = [args.project]
    else:
        projects = discover_projects(raw_docs_path)

    if not projects:
        logger.error("No projects found")
        return

    logger.info(f"Found {len(projects)} projects to re-index")

    # Backup old index
    backup_path = chroma_db_path.parent / f"chroma_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not args.dry_run and chroma_db_path.exists():
        logger.info(f"Backing up current index to {backup_path}")
        shutil.copytree(chroma_db_path, backup_path)

    # Initialize components
    logger.info("Initializing pipeline components...")
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

    # Create new collection (alongside old one)
    indexer = Indexer(
        chroma_db_path=chroma_db_path,
        collection_name=args.collection,
    )

    logger.info(f"Embedding model: {embedder.model_name} ({embedder.embedding_dim}-dim)")

    # Process all projects
    start_time = time.time()
    all_stats = []

    for i, project_id in enumerate(projects, 1):
        logger.info(f"\n[{i}/{len(projects)}] Processing project: {project_id}")
        stats = reindex_project(
            project_id, raw_docs_path,
            pdf_extractor, docx_extractor, image_ocr,
            normalizer, chunker, embedder, indexer,
            dry_run=args.dry_run,
        )
        all_stats.append(stats)

    # Summary
    duration = time.time() - start_time
    total_files = sum(s["files_processed"] for s in all_stats)
    total_failed = sum(s["files_failed"] for s in all_stats)
    total_chunks = sum(s["chunks_created"] for s in all_stats)
    total_errors = [e for s in all_stats for e in s["errors"]]

    logger.info("\n" + "=" * 60)
    logger.info("RE-INDEXING SUMMARY")
    logger.info(f"  Projects: {len(projects)}")
    logger.info(f"  Files processed: {total_files}")
    logger.info(f"  Files failed: {total_failed}")
    logger.info(f"  Total chunks: {total_chunks}")
    logger.info(f"  Duration: {duration:.1f}s")

    if total_errors:
        logger.warning(f"  Errors ({len(total_errors)}):")
        for err in total_errors[:20]:
            logger.warning(f"    - {err}")

    if not args.dry_run:
        logger.info(f"  New collection: {args.collection} ({indexer.collection.count()} chunks)")
        if backup_path.exists():
            logger.info(f"  Backup: {backup_path}")

    # Swap collections if requested
    if args.swap and not args.dry_run and args.collection != "project_docs":
        logger.info("\nSwapping collections...")
        try:
            # Delete old collection
            try:
                indexer.client.delete_collection("project_docs")
                logger.info("  Deleted old 'project_docs' collection")
            except Exception:
                logger.info("  No existing 'project_docs' collection to delete")

            # ChromaDB doesn't support rename, so we create a new one and copy
            # The new collection is already usable as-is; just update config
            logger.info(f"  New collection '{args.collection}' is ready")
            logger.info(f"  Update your indexer to use collection_name='{args.collection}'")
            logger.info(f"  Or re-run with --collection project_docs to use the default name")
        except Exception as e:
            logger.error(f"  Swap failed: {e}")
            logger.info(f"  Backup available at: {backup_path}")

    # Save report
    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "duration_seconds": round(duration, 2),
        "collection": args.collection,
        "dry_run": args.dry_run,
        "embedding_model": embedder.model_name,
        "embedding_dim": embedder.embedding_dim,
        "projects": all_stats,
        "totals": {
            "projects": len(projects),
            "files_processed": total_files,
            "files_failed": total_failed,
            "chunks_created": total_chunks,
        },
    }
    report_path = settings.chunks_path.parent / "logs" / "reindex_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
