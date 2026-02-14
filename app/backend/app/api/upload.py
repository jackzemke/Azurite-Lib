"""
Upload endpoint for file uploads.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from typing import List
from pathlib import Path
import shutil
import logging

from ..config import settings
from ..schemas.models import UploadResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/projects/{project_id}/upload", response_model=UploadResponse)
async def upload_files(
    request: Request,
    project_id: str,
    files: List[UploadFile] = File(...),
):
    """
    Upload files for a project.

    Files are saved to /data/raw_docs/{project_id}/
    Supports both individual files and directory uploads (preserves subdirectory structure).
    """
    try:
        # Log upload info
        total_size = sum(file.size or 0 for file in files if hasattr(file, 'size'))
        logger.info(f"Uploading {len(files)} files for project {project_id} (total: {total_size / 1024 / 1024:.2f}MB)")

        # Get upload directory
        upload_dir = settings.raw_docs_path / project_id
        
        # Ensure directory exists
        try:
            upload_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create upload directory: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create upload directory: {str(e)}")

        saved_files = []
        supported_exts = {'.pdf', '.docx', '.doc', '.xlsx', '.xls', '.png', '.jpg', '.jpeg', '.tiff', '.bmp'}

        for file in files:
            file_ext = Path(file.filename).suffix.lower()
            if file_ext not in supported_exts:
                continue

            file_path = upload_dir / file.filename
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            saved_files.append(file.filename)

        logger.info(f"Saved {len(saved_files)} files for project {project_id}")
        return UploadResponse(
            saved=saved_files,
            project_id=project_id,
        )

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
