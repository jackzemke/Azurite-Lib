"""
Ajera API client and data sync logic.

Connects to the Ajera REST API to fetch employee timesheet data,
transforms it into the ajera_unified.json format, and reloads
the in-memory AjeraData singleton.

The API client methods are scaffolded with placeholder implementations
that should be completed once the exact Ajera API documentation is available.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class AjeraAPIClient:
    """
    Client for the Ajera REST API.

    The Ajera API uses session-based authentication. The flow is:
    1. POST to authenticate and get a session token
    2. Use token for subsequent data requests
    3. Close session when done
    """

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session_token: Optional[str] = None
        self._client = httpx.Client(timeout=30.0)

    def authenticate(self) -> bool:
        """
        Authenticate with Ajera API and obtain session token.

        TODO: Implement once Ajera API documentation is available.
        The authenticate endpoint likely accepts username/password
        and returns a session token or cookie.

        Returns:
            True if authentication succeeded
        """
        try:
            # PLACEHOLDER: Replace with actual Ajera auth endpoint
            # Expected pattern:
            # response = self._client.post(f"{self.base_url}", json={
            #     "DbiUsername": self.username,
            #     "DbiPassword": self.password,
            #     "Method": "Authenticate",
            # })
            # data = response.json()
            # self.session_token = data.get("SessionToken")
            # return self.session_token is not None
            logger.warning("Ajera API authentication not yet implemented - using placeholder")
            return False
        except Exception as e:
            logger.error(f"Ajera authentication failed: {e}")
            return False

    def fetch_employees(self) -> List[Dict[str, Any]]:
        """
        Fetch employee list from Ajera.

        TODO: Implement once Ajera API schema is known.

        Returns:
            List of employee dicts: [{"id": "123", "name": "John Doe"}, ...]
        """
        logger.warning("Ajera fetch_employees not yet implemented")
        return []

    def fetch_timesheets(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch timesheet entries from Ajera.

        TODO: Implement once Ajera API schema is known.

        Args:
            start_date: ISO date string (YYYY-MM-DD), defaults to all time
            end_date: ISO date string (YYYY-MM-DD), defaults to today

        Returns:
            List of timesheet entry dicts with project/employee/hours data
        """
        logger.warning("Ajera fetch_timesheets not yet implemented")
        return []

    def fetch_projects(self) -> List[Dict[str, Any]]:
        """
        Fetch project list with metadata from Ajera.

        TODO: Implement once Ajera API schema is known.

        Returns:
            List of project dicts with id, name, metadata
        """
        logger.warning("Ajera fetch_projects not yet implemented")
        return []

    def close(self):
        """Close the HTTP client."""
        self._client.close()


def transform_to_unified_format(
    employees: List[Dict],
    projects: List[Dict],
    timesheets: List[Dict],
) -> Dict[str, Any]:
    """
    Transform raw Ajera API data into the ajera_unified.json format.

    TODO: Map the actual Ajera API field names to this structure
    once the API schema is documented.
    """
    unified: Dict[str, Any] = {
        "metadata": {
            "source": "ajera_api",
            "synced_at": datetime.now(timezone.utc).isoformat() + "Z",
            "employee_count": len(employees),
            "project_count": len(projects),
            "timesheet_entries": len(timesheets),
        },
        "employee_to_projects": {},
        "project_to_employees": {},
    }

    # PLACEHOLDER: Transform logic goes here once field mappings are known.
    # Pattern: iterate timesheets, group by employee and project,
    # sum hours, build bidirectional mappings.

    return unified


def run_ajera_sync() -> Dict[str, Any]:
    """
    Execute a full Ajera data sync cycle.

    Steps:
    1. Connect to Ajera API
    2. Fetch employees, projects, timesheets
    3. Transform to unified format
    4. Write to ajera_unified.json
    5. Reload in-memory AjeraData singleton

    Returns:
        Dict with sync results (status, counts, duration)
    """
    start_time = time.time()
    result: Dict[str, Any] = {
        "status": "pending",
        "started_at": datetime.now(timezone.utc).isoformat() + "Z",
        "employees": 0,
        "projects": 0,
        "timesheets": 0,
        "duration_seconds": 0,
        "error": None,
    }

    # Validate config
    if not settings.ajera_api_url:
        result["status"] = "skipped"
        result["error"] = "AAA_AJERA_API_URL not configured"
        logger.warning("Ajera sync skipped: API URL not configured")
        return result

    client = AjeraAPIClient(
        base_url=settings.ajera_api_url,
        username=settings.ajera_api_username,
        password=settings.ajera_api_password,
    )

    try:
        # Step 1: Authenticate
        if not client.authenticate():
            result["status"] = "failed"
            result["error"] = "Authentication failed (API client not yet implemented)"
            return result

        # Step 2: Fetch data
        employees = client.fetch_employees()
        projects = client.fetch_projects()
        timesheets = client.fetch_timesheets()

        result["employees"] = len(employees)
        result["projects"] = len(projects)
        result["timesheets"] = len(timesheets)

        # Step 3: Transform
        unified_data = transform_to_unified_format(employees, projects, timesheets)

        # Step 4: Write to file (atomic: write tmp then rename)
        output_path = settings.ajera_data_path_resolved
        output_path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = output_path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(unified_data, f, indent=2)
        tmp_path.rename(output_path)

        logger.info(f"Wrote Ajera data to {output_path}")

        # Step 5: Reload in-memory data
        try:
            from .ajera_loader import get_ajera_data
            ajera = get_ajera_data()
            ajera.reload()
            logger.info("Reloaded in-memory Ajera data")
        except Exception as reload_err:
            logger.warning(f"Could not reload Ajera data in memory: {reload_err}")

        result["status"] = "success"

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        logger.error(f"Ajera sync failed: {e}", exc_info=True)
    finally:
        client.close()
        result["duration_seconds"] = round(time.time() - start_time, 2)

    return result
