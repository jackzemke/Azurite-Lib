"""
Health check endpoint.
"""

from fastapi import APIRouter
from pathlib import Path
import time
import logging

from ..config import settings
from ..schemas.models import HealthResponse
from ..core.indexer import Indexer
from ..core.llm_client import LLMClient

logger = logging.getLogger(__name__)
router = APIRouter()

# Track startup time
START_TIME = time.time()


@router.get("/projects")
async def list_projects():
    """
    Get list of all indexed projects.

    Returns list of project IDs with document counts.
    """
    try:
        indexer = Indexer(chroma_db_path=settings.chroma_db_path)
        
        # Get all projects
        projects = indexer.get_indexed_projects()
        
        # Get document count per project
        project_list = []
        for project_id in projects:
            # Get chunks for this project
            results = indexer.collection.get(
                where={"project_id": project_id},
                limit=10000  # Reasonable limit
            )
            doc_count = len(set(m.get("file_path") for m in results["metadatas"]))
            chunk_count = len(results["ids"])
            
            project_list.append({
                "project_id": project_id,
                "document_count": doc_count,
                "chunk_count": chunk_count
            })
        
        return {
            "projects": project_list,
            "total_projects": len(project_list)
        }
        
    except Exception as e:
        logger.error(f"Error listing projects: {e}")
        return {"projects": [], "total_projects": 0}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.

    Returns system status, indexed projects, and uptime.
    """
    try:
        # Check LLM status
        llm_client = LLMClient(settings.get_legacy_config_dict())
        models_loaded = not llm_client.is_stub_mode()
        stub_mode = llm_client.is_stub_mode()

        # Check Chroma status
        indexer = Indexer(chroma_db_path=settings.chroma_db_path)
        indexed_projects = indexer.get_indexed_projects()
        total_chunks = indexer.collection.count()

        # Calculate uptime
        uptime_seconds = int(time.time() - START_TIME)

        return HealthResponse(
            models_loaded=models_loaded,
            stub_mode=stub_mode,
            chroma_indexed_projects=indexed_projects,
            uptime_seconds=uptime_seconds,
            total_chunks=total_chunks,
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        # Return degraded status
        return HealthResponse(
            models_loaded=False,
            stub_mode=True,
            chroma_indexed_projects=[],
            uptime_seconds=int(time.time() - START_TIME),
            total_chunks=0,
        )
