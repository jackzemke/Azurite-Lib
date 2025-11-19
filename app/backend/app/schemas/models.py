"""
Pydantic models for API validation.
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# Upload models
class UploadResponse(BaseModel):
    """Response for file upload."""
    saved: List[str] = Field(..., description="List of saved filenames")
    project_id: str


# Ingest models
class IngestRequest(BaseModel):
    """Request for document ingestion."""
    files: Optional[List[str]] = Field(None, description="Specific files to ingest (optional)")


class IngestResponse(BaseModel):
    """Response for ingestion."""
    project_id: str
    files_processed: int
    chunks_created: int
    errors: List[str] = Field(default_factory=list)
    duration_seconds: Optional[float] = None
    timestamp: str


# Query models
class Citation(BaseModel):
    """Citation for an answer."""
    project_id: str = Field(..., description="Which project this citation is from")
    file_path: str
    page: int
    chunk_id: str
    text_excerpt: str = Field(..., max_length=500)


class QueryRequest(BaseModel):
    """Request for Q&A query."""
    project_ids: Optional[List[str]] = Field(None, description="List of project IDs to search (empty/null = all projects)")
    query: str = Field(..., min_length=3, max_length=1000)
    k: int = Field(6, ge=1, le=20, description="Number of chunks to retrieve")


class QueryResponse(BaseModel):
    """Response for Q&A query."""
    answer: str
    citations: List[Citation]
    confidence: str = Field(..., pattern="^(high|medium|low)$")
    elapsed_ms: int
    stub_mode: bool = False


# Chunk models
class ChunkMetadata(BaseModel):
    """Metadata for a chunk."""
    chunk_id: str
    project_id: str
    file_path: str
    file_basename: str
    doc_type: str
    page_number: int
    bbox: Optional[List[float]] = None
    text: str
    tokens: int
    ocr_confidence: float = 0.0
    created_at: str


# Health models
class HealthResponse(BaseModel):
    """Health check response."""
    models_loaded: bool
    stub_mode: bool
    chroma_indexed_projects: List[str]
    uptime_seconds: int
    total_chunks: int
