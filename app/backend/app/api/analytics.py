"""
Analytics endpoints for usage metrics and event tracking.

Provides:
- Query usage summary computed from queries.log
- Citation click event recording
- Aggregated metrics for the admin dashboard
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import Counter, defaultdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

ANALYTICS_EVENTS_LOG = settings.resolve_path("data/logs/analytics_events.log")


# ============================================================================
# Models
# ============================================================================

class AnalyticsEvent(BaseModel):
    """Event to record (e.g., citation click)."""
    event_type: str = Field(..., description="Event type: citation_click, etc.")
    project_id: Optional[str] = None
    file_path: Optional[str] = None
    page: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class QueryMetrics(BaseModel):
    """Aggregated query metrics."""
    total_queries: int = 0
    queries_last_7_days: int = 0
    queries_last_30_days: int = 0
    unique_projects_queried: int = 0
    avg_response_time_ms: float = 0
    confidence_distribution: Dict[str, int] = Field(default_factory=dict)
    top_projects: List[Dict[str, Any]] = Field(default_factory=list)
    avg_citations_per_query: float = 0
    queries_per_day: List[Dict[str, Any]] = Field(default_factory=list)


class CitationMetrics(BaseModel):
    """Citation click metrics."""
    total_clicks: int = 0
    clicks_last_7_days: int = 0
    top_clicked_files: List[Dict[str, Any]] = Field(default_factory=list)
    top_clicked_projects: List[Dict[str, Any]] = Field(default_factory=list)


class AnalyticsSummary(BaseModel):
    """Full analytics summary."""
    queries: QueryMetrics
    citations: CitationMetrics
    generated_at: str


# ============================================================================
# Log Parsing Helpers
# ============================================================================

def _parse_queries_log() -> List[Dict]:
    """Parse queries.log (JSON lines format)."""
    log_path = settings.queries_log_path

    if not log_path.exists():
        return []

    entries = []
    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    return entries


def _parse_analytics_events() -> List[Dict]:
    """Parse analytics_events.log (JSON lines format)."""
    if not ANALYTICS_EVENTS_LOG.exists():
        return []

    events = []
    with open(ANALYTICS_EVENTS_LOG, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    return events


def _compute_query_metrics(entries: List[Dict]) -> QueryMetrics:
    """Compute aggregated metrics from query log entries."""
    if not entries:
        return QueryMetrics()

    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    last_7 = 0
    last_30 = 0
    project_counter: Counter = Counter()
    confidence_counter: Counter = Counter()
    elapsed_times: List[float] = []
    citation_counts: List[int] = []
    daily_counts: Dict[str, int] = defaultdict(int)

    for entry in entries:
        ts_str = entry.get("timestamp", "")
        ts = None
        try:
            parsed = datetime.fromisoformat(ts_str.rstrip("Z"))
            # Make aware if naive
            if parsed.tzinfo is None:
                ts = parsed.replace(tzinfo=timezone.utc)
            else:
                ts = parsed
        except (ValueError, AttributeError):
            pass

        if ts:
            if ts >= seven_days_ago:
                last_7 += 1
            if ts >= thirty_days_ago:
                last_30 += 1
            daily_counts[ts.strftime("%Y-%m-%d")] += 1

        # Projects
        project_ids = entry.get("project_ids")
        if project_ids:
            if isinstance(project_ids, list):
                for pid in project_ids:
                    project_counter[pid] += 1
            elif isinstance(project_ids, str):
                project_counter[project_ids] += 1

        # Confidence
        confidence = entry.get("confidence", "unknown")
        confidence_counter[confidence] += 1

        # Response time
        elapsed = entry.get("elapsed_ms")
        if elapsed is not None:
            elapsed_times.append(float(elapsed))

        # Citations
        chunk_ids = entry.get("top_chunk_ids", [])
        citation_counts.append(len(chunk_ids) if isinstance(chunk_ids, list) else 0)

    avg_time = sum(elapsed_times) / len(elapsed_times) if elapsed_times else 0
    avg_cites = sum(citation_counts) / len(citation_counts) if citation_counts else 0

    top_projects = [
        {"project_id": pid, "query_count": count}
        for pid, count in project_counter.most_common(10)
    ]

    queries_per_day = sorted(
        [{"date": d, "count": c} for d, c in daily_counts.items()],
        key=lambda x: x["date"],
    )[-30:]

    return QueryMetrics(
        total_queries=len(entries),
        queries_last_7_days=last_7,
        queries_last_30_days=last_30,
        unique_projects_queried=len(project_counter),
        avg_response_time_ms=round(avg_time, 1),
        confidence_distribution=dict(confidence_counter),
        top_projects=top_projects,
        avg_citations_per_query=round(avg_cites, 2),
        queries_per_day=queries_per_day,
    )


def _compute_citation_metrics(events: List[Dict]) -> CitationMetrics:
    """Compute citation click metrics from events log."""
    citation_events = [e for e in events if e.get("event_type") == "citation_click"]

    if not citation_events:
        return CitationMetrics()

    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    last_7 = 0
    file_counter: Counter = Counter()
    project_counter: Counter = Counter()

    for event in citation_events:
        ts_str = event.get("timestamp", "")
        try:
            parsed = datetime.fromisoformat(ts_str.rstrip("Z"))
            if parsed.tzinfo is None:
                ts = parsed.replace(tzinfo=timezone.utc)
            else:
                ts = parsed
            if ts >= seven_days_ago:
                last_7 += 1
        except (ValueError, AttributeError):
            pass

        file_counter[event.get("file_path", "unknown")] += 1
        project_counter[event.get("project_id", "unknown")] += 1

    return CitationMetrics(
        total_clicks=len(citation_events),
        clicks_last_7_days=last_7,
        top_clicked_files=[
            {"file_path": fp, "click_count": c}
            for fp, c in file_counter.most_common(10)
        ],
        top_clicked_projects=[
            {"project_id": pid, "click_count": c}
            for pid, c in project_counter.most_common(10)
        ],
    )


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/analytics/summary", response_model=AnalyticsSummary)
async def get_analytics_summary():
    """
    Get comprehensive analytics summary.

    Parses queries.log and analytics_events.log to compute query counts,
    response times, confidence distribution, top projects, and citation clicks.
    """
    try:
        query_entries = _parse_queries_log()
        analytics_events = _parse_analytics_events()

        return AnalyticsSummary(
            queries=_compute_query_metrics(query_entries),
            citations=_compute_citation_metrics(analytics_events),
            generated_at=datetime.now(timezone.utc).isoformat() + "Z",
        )
    except Exception as e:
        logger.error(f"Failed to generate analytics summary: {e}")
        raise HTTPException(status_code=500, detail=f"Analytics error: {str(e)}")


@router.post("/analytics/events")
async def record_analytics_event(event: AnalyticsEvent):
    """
    Record an analytics event (e.g., citation click).

    Events are appended to data/logs/analytics_events.log as JSON lines.
    This is a fire-and-forget endpoint -- frontend should not block on this.
    """
    try:
        ANALYTICS_EVENTS_LOG.parent.mkdir(parents=True, exist_ok=True)

        event_record = {
            "event_type": event.event_type,
            "project_id": event.project_id,
            "file_path": event.file_path,
            "page": event.page,
            "metadata": event.metadata,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }

        with open(ANALYTICS_EVENTS_LOG, "a") as f:
            f.write(json.dumps(event_record) + "\n")

        return {"status": "recorded"}
    except Exception as e:
        logger.error(f"Failed to record analytics event: {e}")
        # Don't fail the request -- analytics is non-critical
        return {"status": "error", "detail": str(e)}
