"""
Upload endpoint for file uploads.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import List
from pathlib import Path
import shutil
import logging

from ..schemas.models import UploadResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/projects/{project_id}/upload", response_model=UploadResponse)
async def upload_files(
    project_id: str,
    files: List[UploadFile] = File(...),
):
    """
    Upload files for a project.

    Files are saved to /data/raw_docs/{project_id}/
    """
    try:
        # Get upload directory from config (would be injected in production)
        upload_dir = Path(f"/home/jack/lib/project-library/data/raw_docs/{project_id}")
        upload_dir.mkdir(parents=True, exist_ok=True)

        saved_files = []

        for file in files:
            # Save file
            file_path = upload_dir / file.filename
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            saved_files.append(file.filename)
            logger.info(f"Saved {file.filename} to {file_path}")

        return UploadResponse(
            saved=saved_files,
            project_id=project_id,
        )

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
