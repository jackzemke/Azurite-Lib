"""
Ajera hybrid sync: REST API + ODBC.

Uses the Ajera REST API (v1) for employee names (ListEmployees)
and HDP ODBC for project metadata (AxProject) and timesheet
transactions (AxTransaction). This hybrid approach is necessary
because:
  - The REST API user (jzemke_ai) has limited timesheet permissions
    (sees only 1 employee), while ODBC has full access to AxTransaction.
  - ODBC doesn't expose an employee name table, while REST API does.
  - ODBC gives direct SQL access to AxProject (135K+) and
    AxTransaction (6M+) which is faster than batched REST calls.

Environment setup for ODBC:
  TZ=Etc/UTC  (required by HDP driver)
  ODBCSYSINI=<path to dir containing odbcinst.ini>
  ODBCINI=<path to odbc.ini>
  LD_LIBRARY_PATH must include the HDP driver lib dir
"""

import csv
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_YEARS = 2
_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

# HDP ODBC driver install path (set by installer)
_HDP_DIR = Path.home() / "Progress" / "DataDirect" / "Hybrid_Data_Pipeline_for_ODBC_4_6"


# ---------------------------------------------------------------------------
# REST API client (kept for ListEmployees only)
# ---------------------------------------------------------------------------

class AjeraAPIError(Exception):
    def __init__(self, message: str, response_code: int = 0, errors: list = None):
        super().__init__(message)
        self.response_code = response_code
        self.errors = errors or []


class AjeraAPIClient:
    """Minimal REST client — only used for ListEmployees (API v1)."""

    def __init__(self, api_url: str, username: str, password: str):
        self.api_url = api_url
        self.username = username
        self.password = password
        self.session_token: Optional[str] = None
        self._client = httpx.Client(timeout=60.0)

    def _request(self, payload: dict) -> dict:
        if self.session_token and "SessionToken" not in payload:
            payload["SessionToken"] = self.session_token
        resp = self._client.post(self.api_url, json=payload, headers=_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ResponseCode") != 200:
            raise AjeraAPIError(
                data.get("Message", "Unknown API error"),
                data.get("ResponseCode", 0),
                data.get("Errors", []),
            )
        return data

    def authenticate(self, api_version: int = 1) -> str:
        data = self._request({
            "Method": "CreateAPISession",
            "Username": self.username,
            "Password": self.password,
            "APIVersion": api_version,
            "UseSessionCookie": False,
        })
        self.session_token = data["Content"]["SessionToken"]
        company = data["Content"].get("CompanyName", "unknown")
        logger.info(f"[AJERA] REST authenticated to '{company}' (v{api_version})")
        return self.session_token

    def end_session(self):
        if self.session_token:
            try:
                self._request({
                    "Method": "EndAPISession",
                    "SessionToken": self.session_token,
                })
            except Exception:
                pass
            self.session_token = None

    def list_employees(self) -> List[Dict[str, Any]]:
        data = self._request({
            "Method": "ListEmployees",
            "MethodArguments": {},
        })
        return data["Content"].get("Employees", [])

    def close(self):
        self.end_session()
        self._client.close()


# ---------------------------------------------------------------------------
# ODBC helpers
# ---------------------------------------------------------------------------

def _setup_odbc_env():
    """Set environment variables required by the HDP ODBC driver."""
    if not os.environ.get("TZ"):
        os.environ["TZ"] = "Etc/UTC"

    hdp_dir = _HDP_DIR
    if hdp_dir.exists():
        lib_dir = str(hdp_dir / "lib")
        os.environ.setdefault("ODBCSYSINI", str(hdp_dir))
        os.environ.setdefault("ODBCINI", str(hdp_dir / "odbc.ini"))
        ld_path = os.environ.get("LD_LIBRARY_PATH", "")
        if lib_dir not in ld_path:
            os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{ld_path}" if ld_path else lib_dir


def _get_odbc_connection():
    """Create an ODBC connection to Ajera via HDP DSN."""
    import pyodbc

    _setup_odbc_env()

    dsn = settings.db_dsn or "AjeraHDP"
    uid = settings.db_username
    pwd = settings.db_password

    conn_str = f"DSN={dsn}"
    if uid:
        conn_str += f";UID={uid};PWD={pwd}"

    logger.info(f"[AJERA] Connecting via ODBC DSN={dsn}")
    conn = pyodbc.connect(conn_str, timeout=30, autocommit=True)
    logger.info("[AJERA] ODBC connected")
    return conn


def _fetch_projects_odbc(conn) -> List[Dict[str, Any]]:
    """Fetch project metadata from AxProject via ODBC."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            prjKey,
            prjID,
            prjDescription,
            prjStatus,
            prjProjectType,
            prjProjectManager,
            prjPrincipalInCharge,
            prjLocation,
            prjEstimatedStartDate,
            prjEstimatedCompletionDate,
            prjActualStartDate,
            prjActualCompletionDate,
            prjProject
        FROM dbo.AxProject
    """)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    logger.info(f"[AJERA] ODBC: fetched {len(rows)} projects from AxProject")
    return [dict(zip(columns, row)) for row in rows]


def _fetch_project_types_odbc(conn) -> Dict[int, str]:
    """Fetch project type descriptions from AxProjectType."""
    cursor = conn.cursor()
    cursor.execute("SELECT ptKey, ptDescription FROM dbo.AxProjectType")
    result = {row[0]: row[1] for row in cursor.fetchall()}
    logger.info(f"[AJERA] ODBC: fetched {len(result)} project types")
    return result


def _fetch_time_entries_odbc(conn, lookback_years: int) -> List[Dict[str, Any]]:
    """Fetch time entries from AxTransaction via ODBC.

    Returns list of dicts with employee_key, project_key, date, hours.
    Only includes non-deleted rows where the employee worked hours on a project.
    """
    earliest = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")

    cursor = conn.cursor()
    cursor.execute("""
        SELECT tEmployee, tProject, tDate, tUnits
        FROM dbo.AxTransaction
        WHERE tEmployee IS NOT NULL
          AND tProject IS NOT NULL
          AND tUnits > 0
          AND tIsDeleted = 0
          AND tDate >= ?
        ORDER BY tDate
    """, (earliest,))

    entries = []
    batch_size = 50000
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        for emp, proj, dt, units in rows:
            entries.append({
                "employee_key": str(emp),
                "project_key": str(proj),
                "date": dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10],
                "hours": round(float(units), 2),
            })
        logger.info(f"[AJERA] ODBC: read {len(entries)} time entries so far...")

    logger.info(f"[AJERA] ODBC: total {len(entries)} time entries since {earliest}")
    return entries


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform_to_unified_format(
    employees: List[Dict],
    projects_odbc: List[Dict],
    project_types: Dict[int, str],
    time_entries: List[Dict],
    lookback_years: int,
) -> Dict[str, Any]:
    """Transform fetched data into ajera_unified.json format."""

    # Build employee name lookup from REST API data
    emp_names: Dict[str, str] = {}
    for e in employees:
        ek = str(e["EmployeeKey"])
        first = e.get("FirstName", "")
        last = e.get("LastName", "")
        emp_names[ek] = f"{first} {last}".strip()

    # Build project lookup from ODBC data
    proj_info: Dict[str, Dict[str, Any]] = {}
    for p in projects_odbc:
        pk = str(p["prjKey"])
        pt_key = p.get("prjProjectType")
        proj_info[pk] = {
            "name": p.get("prjDescription") or "",
            "project_id": p.get("prjID") or "",
            "parent_project_key": str(p["prjProject"]) if p.get("prjProject") else None,
            "project_type": pt_key,
            "project_type_description": project_types.get(pt_key, "") if pt_key else "",
            "project_manager": p.get("prjProjectManager"),
            "principal": p.get("prjPrincipalInCharge"),
            "location": p.get("prjLocation") or None,
            "notes": None,
            "estimated_start": _fmt_date(p.get("prjEstimatedStartDate")),
            "estimated_completion": _fmt_date(p.get("prjEstimatedCompletionDate")),
            "actual_start": _fmt_date(p.get("prjActualStartDate")),
            "actual_completion": _fmt_date(p.get("prjActualCompletionDate")),
            "status": p.get("prjStatus"),
        }

    # Group time entries into bidirectional mappings
    emp_proj_timeline: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    proj_emp_timeline: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))

    date_min = None
    date_max = None

    for entry in time_entries:
        ek = entry["employee_key"]
        pk = entry["project_key"]
        record = {"date": entry["date"], "hours": entry["hours"]}
        emp_proj_timeline[ek][pk].append(record)
        proj_emp_timeline[pk][ek].append(record)

        d = entry["date"]
        if date_min is None or d < date_min:
            date_min = d
        if date_max is None or d > date_max:
            date_max = d

        if ek not in emp_names:
            emp_names[ek] = f"Employee {ek}"

    # Build employee_to_projects
    employee_to_projects: Dict[str, Any] = {}
    for ek, proj_timelines in emp_proj_timeline.items():
        employee_to_projects[ek] = {
            "name": emp_names.get(ek, f"Employee {ek}"),
            "projects": sorted(proj_timelines.keys()),
            "timeline": {
                pk: sorted(records, key=lambda r: r["date"])
                for pk, records in proj_timelines.items()
            },
        }

    # Build project_to_employees
    project_to_employees: Dict[str, Any] = {}
    for pk, emp_timelines in proj_emp_timeline.items():
        detail = proj_info.get(pk, {})
        proj_name = detail.get("name", f"Project {pk}")

        project_to_employees[pk] = {
            "name": proj_name,
            "employees": sorted(emp_timelines.keys()),
            "timeline": {
                ek: sorted(records, key=lambda r: r["date"])
                for ek, records in emp_timelines.items()
            },
            "metadata": {
                "name": proj_name,
                "project_id": detail.get("project_id"),
                "parent_project_key": detail.get("parent_project_key"),
                "project_type": detail.get("project_type"),
                "project_manager": detail.get("project_manager"),
                "principal": detail.get("principal"),
                "location": detail.get("location"),
                "marketing_description": None,
                "marketing_scope": None,
                "marketing_notes": None,
                "notes": detail.get("notes"),
                "estimated_start": detail.get("estimated_start"),
                "estimated_completion": detail.get("estimated_completion"),
                "actual_start": detail.get("actual_start"),
                "actual_completion": detail.get("actual_completion"),
                "status": detail.get("status"),
            },
        }

    return {
        "source": "ajera_hybrid_odbc_rest",
        "filter": f"transactions from last {lookback_years} years",
        "date_range": {
            "earliest": date_min or "",
            "latest": date_max or "",
        },
        "employee_to_projects": employee_to_projects,
        "project_to_employees": project_to_employees,
        "metadata": {
            "source": "ajera_hybrid_odbc_rest",
            "synced_at": datetime.now(timezone.utc).isoformat() + "Z",
            "active_employees": len(employee_to_projects),
            "projects": len(project_to_employees),
            "time_entries": len(time_entries),
            "total_projects_in_ajera": len(projects_odbc),
            "projects_with_metadata": len(proj_info),
        },
    }


def _fmt_date(val) -> Optional[str]:
    """Format a datetime or string to ISO date string."""
    if val is None:
        return None
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")
    return str(val)[:10] if val else None


def _regenerate_project_lookup_csv(
    projects_odbc: List[Dict], output_path: Path
) -> int:
    """Regenerate project_lookup.csv from the full AxProject table.

    Writes all projects that have a non-empty prjID.
    CSV columns: ProjectKey, ID, Description, ParentProjectKey
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp")

    count = 0
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(["ProjectKey", "ID", "Description", "ParentProjectKey"])

        for p in projects_odbc:
            prj_id = p.get("prjID") or ""
            if not prj_id:
                continue
            writer.writerow([
                str(p["prjKey"]),
                prj_id,
                p.get("prjDescription") or "",
                str(p["prjProject"]) if p.get("prjProject") else "",
            ])
            count += 1

    tmp_path.rename(output_path)
    return count


# ---------------------------------------------------------------------------
# Main sync entry point
# ---------------------------------------------------------------------------

def run_ajera_sync(lookback_years: int = DEFAULT_LOOKBACK_YEARS) -> Dict[str, Any]:
    """
    Execute a full Ajera data sync.

    Phase 1: REST API v1 → ListEmployees (for names)
    Phase 2: ODBC → AxProject + AxProjectType (metadata)
    Phase 3: ODBC → AxTransaction (time entries)
    Phase 4: Transform → write ajera_unified.json → reload cache
    """
    start_time = time.time()
    result: Dict[str, Any] = {
        "status": "pending",
        "started_at": datetime.now(timezone.utc).isoformat() + "Z",
        "employees": 0,
        "projects": 0,
        "time_entries": 0,
        "duration_seconds": 0,
        "error": None,
    }

    api_client = None
    odbc_conn = None

    try:
        # --- Phase 1: REST API for employee names ---
        if not settings.ajera_api_url:
            logger.warning("[AJERA] REST API URL not configured; employee names will be numeric")
            employees = []
        else:
            api_client = AjeraAPIClient(
                api_url=settings.ajera_api_url,
                username=settings.ajera_api_username,
                password=settings.ajera_api_password,
            )
            api_client.authenticate(api_version=1)
            employees = api_client.list_employees()
            logger.info(f"[AJERA] REST: {len(employees)} employees")
            result["employees"] = len(employees)
            api_client.close()
            api_client = None

        # --- Phase 2: ODBC for projects ---
        odbc_conn = _get_odbc_connection()
        projects_odbc = _fetch_projects_odbc(odbc_conn)
        project_types = _fetch_project_types_odbc(odbc_conn)
        result["projects"] = len(projects_odbc)

        # --- Phase 3: ODBC for time entries ---
        time_entries = _fetch_time_entries_odbc(odbc_conn, lookback_years)
        result["time_entries"] = len(time_entries)
        odbc_conn.close()
        odbc_conn = None

        # --- Phase 4: Transform and write ---
        unified_data = transform_to_unified_format(
            employees, projects_odbc, project_types, time_entries, lookback_years
        )

        output_path = settings.ajera_data_path_resolved
        output_path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = output_path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(unified_data, f)
        tmp_path.rename(output_path)

        logger.info(f"[AJERA] Wrote unified data to {output_path}")

        # Reload in-memory data
        try:
            from .ajera_loader import get_ajera_data
            ajera = get_ajera_data()
            ajera.reload()
            logger.info("[AJERA] Reloaded in-memory Ajera data")
        except Exception as reload_err:
            logger.warning(f"[AJERA] Could not reload in-memory data: {reload_err}")

        # Regenerate project_lookup.csv from full AxProject table
        try:
            csv_path = settings.project_lookup_path_resolved
            csv_count = _regenerate_project_lookup_csv(projects_odbc, csv_path)
            result["csv_projects"] = csv_count
            logger.info(f"[AJERA] Regenerated project_lookup.csv: {csv_count} projects")

            try:
                from .project_mapper import init_project_mapper
                init_project_mapper(str(csv_path))
                logger.info("[AJERA] Reloaded ProjectMapper")
            except Exception as mapper_err:
                logger.warning(f"[AJERA] Could not reload ProjectMapper: {mapper_err}")
        except Exception as csv_err:
            logger.warning(f"[AJERA] Could not regenerate CSV: {csv_err}")

        result["status"] = "success"

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        logger.error(f"[AJERA] Sync failed: {e}", exc_info=True)
    finally:
        if api_client:
            api_client.close()
        if odbc_conn:
            try:
                odbc_conn.close()
            except Exception:
                pass
        result["duration_seconds"] = round(time.time() - start_time, 2)

    return result
