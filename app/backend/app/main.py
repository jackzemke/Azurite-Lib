"""
FastAPI Main Application.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from .config import settings
from .api import upload, ingest, ingest_v2, query, health, ajera, jobs, admin, analytics
from .core.ajera_loader import init_ajera_data
from .core.project_mapper import init_project_mapper
from .core.project_resolver import init_project_resolver

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug_mode else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Azurite Archive Assistant API",
    description="Citation-aware Q&A system for engineering project documents",
    version="0.3.0",
)

# CORS middleware (for frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url] if settings.frontend_url else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Optional API key middleware
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Require X-API-Key header when AAA_API_KEY is configured."""
    # Skip auth if no API key configured (dev mode)
    if not settings.api_key:
        return await call_next(request)

    # Skip auth for docs, openapi schema, root, and health
    skip_paths = {"/", "/docs", "/redoc", "/openapi.json", "/api/v1/health"}
    if request.url.path in skip_paths:
        return await call_next(request)

    # Check API key
    provided_key = request.headers.get("X-API-Key", "")
    if provided_key != settings.api_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key"},
        )

    return await call_next(request)


# Initialize services on startup
@app.on_event("startup")
async def startup_event():
    """Initialize Ajera data, project mappings, and core services on app startup."""
    if settings.api_key:
        logger.info("API key authentication enabled")
    else:
        logger.info("API key authentication disabled (dev mode)")

    # Initialize Ajera employee-project time tracking data
    ajera_path = settings.ajera_data_path_resolved
    if ajera_path.exists():
        init_ajera_data(str(ajera_path))
        logger.info("Initialized Ajera data with enriched metadata")
    else:
        logger.warning(f"Ajera data not found at {ajera_path}, skipping")

    # Initialize Project ID mapper (Ajera ProjectKey <-> File System ID)
    mapper_path = settings.project_lookup_path_resolved
    if mapper_path.exists():
        init_project_mapper(str(mapper_path))
        logger.info("Initialized Project ID mapper")
    else:
        logger.warning(f"Project lookup CSV not found at {mapper_path}, skipping")

    # Initialize Unified Project Resolver (combines all sources)
    init_project_resolver()
    logger.info("Initialized Unified Project Resolver")

    # Auto-index project metadata into ChromaDB
    metadata_path = settings.metadata_index_path_resolved
    if metadata_path.exists():
        from .services import get_metadata_indexer, get_embedder
        metadata_indexer = get_metadata_indexer()
        if metadata_indexer.needs_reindex():
            embedder = get_embedder()
            result = metadata_indexer.index_metadata(embedder)
            logger.info(f"Metadata auto-index: {result}")
        else:
            logger.info(
                f"Metadata index up-to-date ({metadata_indexer.collection.count()} projects)"
            )
    else:
        logger.warning(f"Metadata index not found at {metadata_path}, skipping auto-index")

    # Log directory index configuration status
    if settings.network_drives_config:
        logger.info(f"Network drives configured: {len(settings.network_drives_config)} drives")
        for drive in settings.network_drives_config:
            logger.info(f"  - {drive.get('name', '?')}: {drive.get('mount_path', '?')} ({drive.get('drive_letter', '?')}:)")
    else:
        logger.info("No network drives configured (directory index disabled)")

    # Initialize scheduled Ajera sync (if configured)
    if settings.ajera_api_url and settings.ajera_sync_interval_hours > 0:
        import threading
        import time as _time

        def _scheduled_sync():
            """Run Ajera sync on a recurring schedule."""
            from .core.ajera_sync import run_ajera_sync
            interval_seconds = settings.ajera_sync_interval_hours * 3600
            while True:
                _time.sleep(interval_seconds)
                try:
                    logger.info("Starting scheduled Ajera sync...")
                    result = run_ajera_sync()
                    logger.info(f"Scheduled Ajera sync completed: {result.get('status')}")
                except Exception as e:
                    logger.error(f"Scheduled Ajera sync failed: {e}")

        sync_thread = threading.Thread(target=_scheduled_sync, daemon=True, name="ajera-sync")
        sync_thread.start()
        logger.info(f"Started Ajera sync scheduler (every {settings.ajera_sync_interval_hours}h)")
    else:
        logger.info("Ajera API sync not configured or disabled")

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
app.include_router(analytics.router, prefix="/api/v1", tags=["analytics"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Azurite Archive Assistant API",
        "version": "0.3.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
