"""
Async Job Queue Infrastructure using Redis Queue (RQ).

This module provides background job processing for long-running tasks
like document ingestion, allowing users to queue jobs and check status
without blocking the request.

Key Components:
- JobQueue: Main interface for enqueueing and managing jobs
- JobStatus: Pydantic model for job status responses
- IngestJob: The actual ingestion job that runs in background

Usage:
    queue = JobQueue()
    job_id = queue.enqueue_ingest(project_id="demo_project")
    status = queue.get_job_status(job_id)
"""

import os
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from enum import Enum

from pydantic import BaseModel, Field

# Redis Queue imports - graceful fallback if Redis not available
try:
    from redis import Redis
    from rq import Queue, Worker
    from rq.job import Job
    from rq.registry import FinishedJobRegistry, FailedJobRegistry, StartedJobRegistry
    RQ_AVAILABLE = True
except ImportError:
    RQ_AVAILABLE = False
    Redis = None
    Queue = None
    Job = None


logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
QUEUE_NAME = "ingestion"
JOB_TIMEOUT = 3600  # 1 hour max for ingestion jobs
RESULT_TTL = 86400  # Keep job results for 24 hours


# ============================================================================
# Models
# ============================================================================

class JobState(str, Enum):
    """Job execution states."""
    QUEUED = "queued"
    STARTED = "started"
    PROCESSING = "processing"  # Custom state for progress updates
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEFERRED = "deferred"
    UNKNOWN = "unknown"


class JobStatus(BaseModel):
    """Job status response model."""
    job_id: str
    state: JobState
    project_id: Optional[str] = None
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    message: str = ""
    files_total: int = 0
    files_processed: int = 0
    chunks_created: int = 0
    errors: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    result: Optional[Dict[str, Any]] = None


class JobListItem(BaseModel):
    """Summary item for job listing."""
    job_id: str
    state: JobState
    project_id: Optional[str] = None
    progress: float = 0.0
    created_at: Optional[str] = None


# ============================================================================
# Job Queue Manager
# ============================================================================

class JobQueue:
    """
    Manager for async job queue operations.
    
    Provides methods to enqueue jobs, check status, and manage job lifecycle.
    Falls back to synchronous execution if Redis is not available.
    """
    
    def __init__(self, redis_host: str = REDIS_HOST, redis_port: int = REDIS_PORT):
        self._redis_conn: Optional[Redis] = None
        self._queue: Optional[Queue] = None
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._connected = False
        
        self._connect()
    
    def _connect(self):
        """Establish Redis connection."""
        if not RQ_AVAILABLE:
            logger.warning("Redis Queue not available - jobs will run synchronously")
            return
        
        try:
            self._redis_conn = Redis(
                host=self._redis_host,
                port=self._redis_port,
                db=REDIS_DB,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # Test connection
            self._redis_conn.ping()
            self._queue = Queue(QUEUE_NAME, connection=self._redis_conn)
            self._connected = True
            logger.info(f"Connected to Redis at {self._redis_host}:{self._redis_port}")
        except Exception as e:
            logger.warning(f"Could not connect to Redis: {e}. Jobs will run synchronously.")
            self._redis_conn = None
            self._queue = None
            self._connected = False
    
    @property
    def is_available(self) -> bool:
        """Check if async job queue is available."""
        return self._connected and self._queue is not None
    
    def enqueue_ingest(
        self,
        project_id: str,
        files: Optional[List[str]] = None,
    ) -> str:
        """
        Enqueue an ingestion job for background processing.
        
        Args:
            project_id: The project folder name
            files: Optional list of specific files to process
        
        Returns:
            job_id: Unique identifier for tracking the job
        """
        from .ingest_worker import run_ingest_job  # Import here to avoid circular deps
        
        if not self.is_available:
            # Fallback: Run synchronously and return a fake job ID
            logger.warning("Redis not available, running ingest synchronously")
            result = run_ingest_job(project_id, files)
            # Store result in memory for retrieval (limited fallback)
            return f"sync_{project_id}_{int(time.time())}"
        
        job = self._queue.enqueue(
            run_ingest_job,
            args=(project_id, files),
            job_timeout=JOB_TIMEOUT,
            result_ttl=RESULT_TTL,
            meta={
                "project_id": project_id,
                "files_total": len(files) if files else 0,
                "files_processed": 0,
                "chunks_created": 0,
                "progress": 0.0,
                "message": "Job queued",
                "errors": [],
            }
        )
        
        logger.info(f"Enqueued ingest job {job.id} for project {project_id}")
        return job.id
    
    def get_job_status(self, job_id: str) -> JobStatus:
        """
        Get the current status of a job.
        
        Args:
            job_id: The job identifier
        
        Returns:
            JobStatus with current state and progress
        """
        if not self.is_available:
            return JobStatus(
                job_id=job_id,
                state=JobState.UNKNOWN,
                message="Job queue not available - Redis not connected",
            )
        
        try:
            job = Job.fetch(job_id, connection=self._redis_conn)
        except Exception as e:
            return JobStatus(
                job_id=job_id,
                state=JobState.UNKNOWN,
                message=f"Job not found: {e}",
            )
        
        # Map RQ status to our states
        state = self._map_job_state(job)
        
        # Get metadata (progress, files, etc.)
        meta = job.meta or {}
        
        # Calculate duration
        duration = None
        if job.started_at:
            end_time = job.ended_at or datetime.now(timezone.utc)
            if hasattr(end_time, 'timestamp') and hasattr(job.started_at, 'timestamp'):
                duration = (end_time - job.started_at).total_seconds()
        
        return JobStatus(
            job_id=job_id,
            state=state,
            project_id=meta.get("project_id"),
            progress=meta.get("progress", 0.0),
            message=meta.get("message", ""),
            files_total=meta.get("files_total", 0),
            files_processed=meta.get("files_processed", 0),
            chunks_created=meta.get("chunks_created", 0),
            errors=meta.get("errors", []),
            created_at=job.created_at.isoformat() if job.created_at else None,
            started_at=job.started_at.isoformat() if job.started_at else None,
            ended_at=job.ended_at.isoformat() if job.ended_at else None,
            duration_seconds=round(duration, 2) if duration else None,
            result=job.result if job.is_finished else None,
        )
    
    def _map_job_state(self, job: Job) -> JobState:
        """Map RQ job status to our JobState enum."""
        status = job.get_status()
        
        if status == "queued":
            return JobState.QUEUED
        elif status == "started":
            # Check if we have progress updates
            if job.meta and job.meta.get("progress", 0) > 0:
                return JobState.PROCESSING
            return JobState.STARTED
        elif status == "finished":
            return JobState.FINISHED
        elif status == "failed":
            return JobState.FAILED
        elif status == "deferred":
            return JobState.DEFERRED
        elif status == "canceled":
            return JobState.CANCELLED
        else:
            return JobState.UNKNOWN
    
    def cancel_job(self, job_id: str) -> bool:
        """
        Attempt to cancel a queued job.
        
        Note: Jobs that are already running cannot be cancelled cleanly.
        
        Returns:
            True if job was cancelled, False otherwise
        """
        if not self.is_available:
            return False
        
        try:
            job = Job.fetch(job_id, connection=self._redis_conn)
            status = job.get_status()
            
            if status == "queued":
                job.cancel()
                logger.info(f"Cancelled job {job_id}")
                return True
            else:
                logger.warning(f"Cannot cancel job {job_id} in state {status}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")
            return False
    
    def list_jobs(
        self,
        state_filter: Optional[JobState] = None,
        project_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[JobListItem]:
        """
        List jobs with optional filtering.
        
        Args:
            state_filter: Filter by job state
            project_id: Filter by project
            limit: Maximum number of jobs to return
        
        Returns:
            List of job summaries
        """
        if not self.is_available:
            return []
        
        jobs = []
        
        # Get jobs from various registries
        try:
            # Queued jobs
            for job in self._queue.jobs[:limit]:
                jobs.append(self._job_to_list_item(job))
            
            # Started jobs
            started_registry = StartedJobRegistry(queue=self._queue)
            for job_id in started_registry.get_job_ids()[:limit]:
                try:
                    job = Job.fetch(job_id, connection=self._redis_conn)
                    jobs.append(self._job_to_list_item(job))
                except:
                    pass
            
            # Finished jobs
            finished_registry = FinishedJobRegistry(queue=self._queue)
            for job_id in finished_registry.get_job_ids()[:limit]:
                try:
                    job = Job.fetch(job_id, connection=self._redis_conn)
                    jobs.append(self._job_to_list_item(job))
                except:
                    pass
            
            # Failed jobs
            failed_registry = FailedJobRegistry(queue=self._queue)
            for job_id in failed_registry.get_job_ids()[:limit]:
                try:
                    job = Job.fetch(job_id, connection=self._redis_conn)
                    jobs.append(self._job_to_list_item(job))
                except:
                    pass
        except Exception as e:
            logger.error(f"Error listing jobs: {e}")
        
        # Apply filters
        if state_filter:
            jobs = [j for j in jobs if j.state == state_filter]
        
        if project_id:
            jobs = [j for j in jobs if j.project_id == project_id]
        
        # Sort by creation time (newest first)
        jobs.sort(key=lambda j: j.created_at or "", reverse=True)
        
        return jobs[:limit]
    
    def _job_to_list_item(self, job: Job) -> JobListItem:
        """Convert a Job to a JobListItem."""
        meta = job.meta or {}
        return JobListItem(
            job_id=job.id,
            state=self._map_job_state(job),
            project_id=meta.get("project_id"),
            progress=meta.get("progress", 0.0),
            created_at=job.created_at.isoformat() if job.created_at else None,
        )
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        if not self.is_available:
            return {
                "available": False,
                "message": "Redis not connected",
            }
        
        try:
            finished_registry = FinishedJobRegistry(queue=self._queue)
            failed_registry = FailedJobRegistry(queue=self._queue)
            started_registry = StartedJobRegistry(queue=self._queue)
            
            return {
                "available": True,
                "redis_host": self._redis_host,
                "redis_port": self._redis_port,
                "queue_name": QUEUE_NAME,
                "queued": len(self._queue),
                "started": len(started_registry),
                "finished": len(finished_registry),
                "failed": len(failed_registry),
            }
        except Exception as e:
            return {
                "available": False,
                "error": str(e),
            }


# ============================================================================
# Singleton instance
# ============================================================================

_job_queue_instance: Optional[JobQueue] = None


def get_job_queue() -> JobQueue:
    """Get the singleton JobQueue instance."""
    global _job_queue_instance
    if _job_queue_instance is None:
        _job_queue_instance = JobQueue()
    return _job_queue_instance


def update_job_progress(
    job: Job,
    progress: float,
    message: str = "",
    files_processed: int = None,
    chunks_created: int = None,
    errors: List[str] = None,
):
    """
    Update job progress metadata.
    
    Call this from within a running job to report progress.
    
    Args:
        job: The current RQ job (use rq.get_current_job())
        progress: Percentage complete (0-100)
        message: Human-readable status message
        files_processed: Number of files completed
        chunks_created: Total chunks created so far
        errors: List of error messages
    """
    if job is None:
        return
    
    meta = job.meta or {}
    meta["progress"] = min(100.0, max(0.0, progress))
    meta["message"] = message
    
    if files_processed is not None:
        meta["files_processed"] = files_processed
    if chunks_created is not None:
        meta["chunks_created"] = chunks_created
    if errors is not None:
        meta["errors"] = errors
    
    job.meta = meta
    job.save_meta()
