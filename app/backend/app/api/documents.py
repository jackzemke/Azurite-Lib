"""
Document serving endpoint for viewing cited files.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/projects/{project_id}/documents/{file_path:path}")
async def get_document(project_id: str, file_path: str):
    """
    Serve a document file for viewing.
    
    Args:
        project_id: Project ID
        file_path: Relative path to file within project directory
    
    Returns:
        File response with appropriate content type
    """
    try:
        # Construct absolute path
        base_dir = Path("/home/jack/lib/project-library/data/raw_docs")
        full_path = base_dir / project_id / file_path
        
        # Security: ensure path doesn't escape project directory
        if not full_path.resolve().is_relative_to(base_dir / project_id):
            raise HTTPException(status_code=403, detail="Access denied: path traversal detected")
        
        # Check if file exists
        if not full_path.exists() or not full_path.is_file():
            raise HTTPException(status_code=404, detail=f"Document not found: {file_path}")
        
        logger.info(f"Serving document: {project_id}/{file_path}")
        
        # Determine content type
        suffix = full_path.suffix.lower()
        content_type_map = {
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.tiff': 'image/tiff',
            '.bmp': 'image/bmp',
        }
        
        media_type = content_type_map.get(suffix, 'application/octet-stream')
        
        # For PDFs, set Content-Disposition to 'inline' so browser displays instead of downloads
        headers = {}
        if suffix == '.pdf':
            headers["Content-Disposition"] = f'inline; filename="{full_path.name}"'
        
        return FileResponse(
            path=str(full_path),
            media_type=media_type,
            headers=headers if headers else None,
            filename=full_path.name if suffix != '.pdf' else None  # Don't set filename param for PDFs (conflicts with inline)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve document {project_id}/{file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to serve document: {str(e)}")
