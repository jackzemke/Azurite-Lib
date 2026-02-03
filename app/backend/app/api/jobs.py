"""
Jobs API for managing async ingestion jobs.

Provides endpoints for:
- Checking job status
- Listing all jobs
- Cancelling queued jobs
- Getting queue statistics
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List

from ..core.job_queue import (
    get_job_queue,
    JobStatus,
    JobListItem,
    JobState,
)

import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """
    Get the current status of a job.
    
    Returns detailed information about the job including:
    - Current state (queued, started, processing, finished, failed)
    - Progress percentage
    - Files processed / chunks created
    - Any errors encountered
    - Timestamps (created, started, ended)
    - Result (if finished)
    
    Use this endpoint to poll for job completion.
    Recommended polling interval: 2-5 seconds.
    """
    queue = get_job_queue()
    status = queue.get_job_status(job_id)
    
    if status.state == JobState.UNKNOWN:
        raise HTTPException(
            status_code=404,
            detail=f"Job not found: {job_id}"
        )
    
    return status


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """
    Attempt to cancel a queued job.
    
    Only jobs in the 'queued' state can be cancelled.
    Jobs that have already started cannot be cleanly cancelled.
    
    Returns:
        - success: Whether the cancellation was successful
        - message: Description of the result
    """
    queue = get_job_queue()
    
    # First check if job exists
    status = queue.get_job_status(job_id)
    if status.state == JobState.UNKNOWN:
        raise HTTPException(
            status_code=404,
            detail=f"Job not found: {job_id}"
        )
    
    if status.state != JobState.QUEUED:
        return {
            "success": False,
            "message": f"Cannot cancel job in state '{status.state.value}'. Only queued jobs can be cancelled.",
            "job_id": job_id,
            "current_state": status.state.value,
        }
    
    cancelled = queue.cancel_job(job_id)
    
    if cancelled:
        logger.info(f"Job {job_id} cancelled by user")
        return {
            "success": True,
            "message": "Job cancelled successfully",
            "job_id": job_id,
        }
    else:
        return {
            "success": False,
            "message": "Failed to cancel job",
            "job_id": job_id,
        }


@router.get("/jobs", response_model=List[JobListItem])
async def list_jobs(
    state: Optional[str] = Query(None, description="Filter by state: queued, started, processing, finished, failed"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of jobs to return"),
):
    """
    List jobs with optional filtering.
    
    Returns a list of job summaries sorted by creation time (newest first).
    
    Use query parameters to filter:
    - state: Filter by job state
    - project_id: Filter by project
    - limit: Maximum number of results (default 50)
    """
    queue = get_job_queue()
    
    # Parse state filter
    state_filter = None
    if state:
        try:
            state_filter = JobState(state)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid state: {state}. Valid states: {[s.value for s in JobState]}"
            )
    
    jobs = queue.list_jobs(
        state_filter=state_filter,
        project_id=project_id,
        limit=limit,
    )
    
    return jobs


@router.get("/jobs/queue/stats")
async def get_queue_stats():
    """
    Get queue statistics.
    
    Returns:
    - available: Whether the job queue is connected and operational
    - queued: Number of jobs waiting in queue
    - started: Number of jobs currently running
    - finished: Number of completed jobs
    - failed: Number of failed jobs
    - redis_host/port: Connection details
    """
    queue = get_job_queue()
    return queue.get_queue_stats()


@router.get("/jobs/queue/health")
async def check_queue_health():
    """
    Health check for the job queue.
    
    Returns:
    - healthy: Whether the queue is operational
    - message: Description of the health status
    - fallback_mode: Whether running in sync fallback mode (no Redis)
    """
    queue = get_job_queue()
    
    if queue.is_available:
        return {
            "healthy": True,
            "message": "Job queue is operational",
            "fallback_mode": False,
        }
    else:
        return {
            "healthy": True,  # Still "healthy" because fallback mode works
            "message": "Redis not connected - jobs will run synchronously",
            "fallback_mode": True,
        }
