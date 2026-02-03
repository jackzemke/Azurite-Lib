"""
FastAPI Main Application.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import logging
from pathlib import Path

from .api import upload, ingest, ingest_v2, query, health, ajera, jobs, admin
from .core.ajera_loader import init_ajera_data
from .core.project_mapper import init_project_mapper
from .core.project_resolver import init_project_resolver

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Project Library API",
    description="Citation-aware Q&A system for engineering project documents",
    version="0.1.0",
)

# CORS middleware (for frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Ajera data and Project Mapper on startup
@app.on_event("startup")
async def startup_event():
    """Initialize Ajera data and project mappings on app startup."""
    # Initialize Ajera employee-project time tracking data
    ajera_path = Path("/home/jack/lib/project-library/data/ajera_unified.json")
    init_ajera_data(str(ajera_path))
    logger.info("✓ Initialized Ajera data with enriched metadata")
    
    # Initialize Project ID mapper (Ajera ProjectKey <-> File System ID)
    mapper_path = Path("/home/jack/lib/project-library/data/mappings/project_lookup.csv")
    init_project_mapper(str(mapper_path))
    logger.info("✓ Initialized Project ID mapper")
    
    # Initialize Unified Project Resolver (combines all sources)
    init_project_resolver()
    logger.info("✓ Initialized Unified Project Resolver")

# Include routers
app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
# Use enhanced ingestion (v2) - keeps old endpoint for backwards compatibility
app.include_router(ingest_v2.router, prefix="/api/v1", tags=["ingest"])
app.include_router(ingest.router, prefix="/api/v1/legacy", tags=["ingest-legacy"])
app.include_router(query.router, prefix="/api/v1", tags=["query"])
app.include_router(ajera.router, prefix="/api/v1", tags=["ajera"])
app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])

# Import and include documents router
from .api import documents, projects
app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
app.include_router(projects.router, prefix="/api/v1", tags=["projects"])
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Project Library API",
        "version": "0.1.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
