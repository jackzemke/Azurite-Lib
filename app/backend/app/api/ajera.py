"""
Ajera data API endpoints.
Provides access to employee and project information with department filtering.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel

from ..core.ajera_loader import get_ajera_data
from ..core.department_codes import (
    get_department_from_file_id,
    get_all_departments,
    infer_department_from_query,
    filter_projects_by_department,
    DEPARTMENT_CODES
)
from ..core.project_mapper import get_project_mapper
from ..core.project_resolver import get_project_resolver

router = APIRouter()


class EmployeeInfo(BaseModel):
    """Employee information."""
    employee_id: str
    name: str
    project_count: int


class ProjectInfo(BaseModel):
    """Project information."""
    project_id: str
    name: str
    employee_count: int
    employees: List[str]


class EmployeeDetail(BaseModel):
    """Detailed employee information with projects."""
    employee_id: str
    name: str
    projects: List[str]
    total_hours: Optional[float] = None


@router.get("/employees", response_model=List[EmployeeInfo])
async def list_employees(
    search: Optional[str] = Query(None, description="Search employees by name"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results to return")
):
    """
    List or search employees.
    
    - **search**: Optional name search query (partial match, case-insensitive)
    - **limit**: Maximum number of results (default 50, max 500)
    
    Returns list of employees with basic info.
    """
    ajera = get_ajera_data()
    
    if search:
        # Search by name
        results = ajera.search_employees_by_name(search, limit=limit)
        employees = []
        for result in results:
            emp_id = result["employee_id"]
            projects = ajera.get_employee_projects(emp_id)
            employees.append(EmployeeInfo(
                employee_id=emp_id,
                name=result["name"],
                project_count=len(projects)
            ))
    else:
        # Return all employees
        if not ajera.data:
            return []
        
        employees = []
        for emp_id, emp_data in list(ajera.data.get("employee_to_projects", {}).items())[:limit]:
            employees.append(EmployeeInfo(
                employee_id=emp_id,
                name=emp_data.get("name", ""),
                project_count=len(emp_data.get("projects", []))
            ))
    
    return employees


@router.get("/employees/{employee_id}", response_model=EmployeeDetail)
async def get_employee(employee_id: str):
    """
    Get detailed information for a specific employee.
    
    - **employee_id**: Employee ID or name (partial match)
    
    Returns employee details including project list.
    """
    ajera = get_ajera_data()
    
    # Try to resolve if name provided
    resolved_id = employee_id
    if not employee_id.isdigit():
        resolved_id = ajera.get_employee_id_by_name(employee_id)
        if not resolved_id:
            raise HTTPException(
                status_code=404,
                detail=f"Employee '{employee_id}' not found"
            )
    
    # Get employee data
    name = ajera.get_employee_name(resolved_id)
    if not name:
        raise HTTPException(
            status_code=404,
            detail=f"Employee ID {resolved_id} not found"
        )
    
    projects = ajera.get_employee_projects(resolved_id)
    
    # Calculate total hours if available
    total_hours = None
    if ajera.data:
        emp_data = ajera.data.get("employee_to_projects", {}).get(resolved_id, {})
        timeline = emp_data.get("timeline", {})
        if timeline:
            total_hours = sum(
                sum(entry["hours"] for entry in entries)
                for entries in timeline.values()
            )
    
    return EmployeeDetail(
        employee_id=resolved_id,
        name=name,
        projects=projects,
        total_hours=total_hours
    )


@router.get("/ajera/projects", response_model=List[ProjectInfo])
async def list_ajera_projects(
    search: Optional[str] = Query(None, description="Search projects by name"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results to return")
):
    """
    List or search Ajera projects.
    
    - **search**: Optional name search query (partial match, case-insensitive)
    - **limit**: Maximum number of results (default 50, max 500)
    
    Returns list of projects with basic info from Ajera.
    """
    ajera = get_ajera_data()
    
    if search:
        # Search by name
        results = ajera.search_projects_by_name(search, limit=limit)
        projects = []
        for result in results:
            proj_id = result["project_id"]
            employees = ajera.get_project_employees(proj_id)
            projects.append(ProjectInfo(
                project_id=proj_id,
                name=result["name"],
                employee_count=len(employees),
                employees=employees[:5]  # First 5 employees
            ))
    else:
        # Return all projects
        if not ajera.data:
            return []
        
        projects = []
        for proj_id, proj_data in list(ajera.data.get("project_to_employees", {}).items())[:limit]:
            employees = proj_data.get("employees", [])
            projects.append(ProjectInfo(
                project_id=proj_id,
                name=proj_data.get("name", ""),
                employee_count=len(employees),
                employees=employees[:5]
            ))
    
    return projects


@router.get("/ajera/projects/{project_id}", response_model=ProjectInfo)
async def get_ajera_project(project_id: str):
    """
    Get detailed information for a specific Ajera project.
    
    - **project_id**: Project ID
    
    Returns project details from Ajera including employee list.
    """
    ajera = get_ajera_data()
    
    proj_info = ajera.get_project_info(project_id)
    if not proj_info:
        raise HTTPException(
            status_code=404,
            detail=f"Project {project_id} not found"
        )
    
    return ProjectInfo(
        project_id=project_id,
        name=proj_info["name"],
        employee_count=len(proj_info["employees"]),
        employees=proj_info["employees"]
    )


@router.get("/ajera/metadata")
async def get_ajera_metadata():
    """
    Get Ajera data metadata (counts, date ranges, etc.).
    
    Returns metadata about the loaded Ajera dataset.
    """
    ajera = get_ajera_data()
    return ajera.get_metadata()


# =============================================================================
# Department Code Endpoints
# =============================================================================

class DepartmentInfo(BaseModel):
    """Department information."""
    code: str
    name: str
    short: str
    description: str


class ProjectSearchResult(BaseModel):
    """Project search result with department info."""
    project_key: str
    file_id: Optional[str]
    name: str
    department: Optional[DepartmentInfo]
    employee_count: int
    has_documents: bool = False


class EmployeeProjectHistory(BaseModel):
    """Employee's project history by department."""
    employee_id: str
    employee_name: str
    total_projects: int
    by_department: dict  # code -> list of project names
    recent_projects: List[dict]


@router.get("/departments", response_model=List[DepartmentInfo])
async def list_departments():
    """
    List all SMA department codes.
    
    Returns the mapping of first-digit codes to department names.
    Useful for filtering projects by discipline.
    """
    return [
        DepartmentInfo(
            code=dept["code"],
            name=dept["name"],
            short=dept["short"],
            description=dept["description"]
        )
        for dept in get_all_departments()
    ]


@router.get("/projects/search", response_model=List[ProjectSearchResult])
async def search_projects(
    q: Optional[str] = Query(None, description="Search query (searches name, description, metadata)"),
    department: Optional[str] = Query(None, description="Filter by department code (1-9)"),
    employee_id: Optional[str] = Query(None, description="Filter to projects this employee worked on"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results")
):
    """
    Search projects across Ajera with department filtering.
    
    This is the primary endpoint for marketing/business development queries like:
    - "Find water projects" (department=6)
    - "Projects John Smith worked on" (employee_id=...)
    - "Landfill projects with employee X" (q=landfill, employee_id=...)
    
    Auto-infers department from search terms if not specified.
    """
    ajera = get_ajera_data()
    mapper = get_project_mapper()
    resolver = get_project_resolver()
    
    # Start with all projects or employee's projects
    if employee_id:
        # Resolve employee name if needed
        resolved_id = employee_id
        if not employee_id.isdigit():
            resolved_id = ajera.get_employee_id_by_name(employee_id)
            if not resolved_id:
                raise HTTPException(404, f"Employee '{employee_id}' not found")
        
        project_keys = ajera.get_employee_projects(resolved_id)
    else:
        # All projects
        if not ajera.data:
            return []
        project_keys = list(ajera.data.get("project_to_employees", {}).keys())

    # If query provided, try metadata search first (if available)
    meta_keys = set()
    if q:
        meta_results = ajera.search_projects_by_metadata(q, limit=limit * 5)
        if meta_results:
            meta_keys = {r["project_id"] for r in meta_results}
            project_keys = [k for k in project_keys if k in meta_keys]

    # Get file IDs for department filtering and build project list
    projects_with_ids = []
    for key in project_keys:
        file_id = mapper.get_file_id(key)
        proj_info = ajera.get_project_info(key)
        proj_name = proj_info.get("name", "") if proj_info else ""

        projects_with_ids.append({
            "project_key": key,
            "file_id": file_id,
            "name": proj_name,
            "employees": proj_info.get("employees", []) if proj_info else []
        })

    # Filter by department
    dept_codes: List[str] = []
    if department:
        dept_codes = [department]
    elif q:
        # Auto-infer department from query
        dept_codes = infer_department_from_query(q)

    if dept_codes:
        filtered_ids = filter_projects_by_department(
            [p["file_id"] for p in projects_with_ids if p["file_id"]],
            dept_codes
        )
        projects_with_ids = [
            p for p in projects_with_ids
            if p["file_id"] in filtered_ids
        ]

    # Text search on name (fallback if metadata isn't available)
    if q and not meta_keys:
        q_lower = q.lower()
        projects_with_ids = [
            p for p in projects_with_ids
            if q_lower in p["name"].lower()
        ]
    
    # Build results
    results = []
    for proj in projects_with_ids[:limit]:
        dept_info = None
        if proj["file_id"]:
            dept = get_department_from_file_id(proj["file_id"])
            if dept:
                dept_info = DepartmentInfo(
                    code=dept["code"],
                    name=dept["name"],
                    short=dept["short"],
                    description=dept["description"]
                )
        
        has_docs = False
        if proj["file_id"]:
            has_docs = resolver.resolve_to_folder_name(proj["file_id"]) is not None
        elif proj["project_key"]:
            has_docs = resolver.resolve_to_folder_name(proj["project_key"]) is not None

        results.append(ProjectSearchResult(
            project_key=proj["project_key"],
            file_id=proj["file_id"],
            name=proj["name"],
            department=dept_info,
            employee_count=len(proj["employees"]),
            has_documents=has_docs
        ))
    
    return results


@router.get("/employees/{employee_id}/history", response_model=EmployeeProjectHistory)
async def get_employee_project_history(
    employee_id: str,
    department: Optional[str] = Query(None, description="Filter by department code")
):
    """
    Get an employee's project history grouped by department.
    
    Useful for marketing queries like:
    - "What water projects has Jane worked on?"
    - "Show me John's environmental experience"
    """
    ajera = get_ajera_data()
    mapper = get_project_mapper()
    
    # Resolve employee
    resolved_id = employee_id
    if not employee_id.isdigit():
        resolved_id = ajera.get_employee_id_by_name(employee_id)
        if not resolved_id:
            raise HTTPException(404, f"Employee '{employee_id}' not found")
    
    name = ajera.get_employee_name(resolved_id)
    if not name:
        raise HTTPException(404, f"Employee ID {resolved_id} not found")
    
    project_keys = ajera.get_employee_projects(resolved_id)
    
    # Group by department
    by_department = {code: [] for code in DEPARTMENT_CODES.keys()}
    by_department["unknown"] = []

    # Build project list with last activity
    all_projects = []
    timeline = {}
    if ajera.data:
        emp_data = ajera.data.get("employee_to_projects", {}).get(resolved_id, {})
        timeline = emp_data.get("timeline", {})

    for key in project_keys:
        file_id = mapper.get_file_id(key)
        proj_info = ajera.get_project_info(key)
        proj_name = proj_info.get("name", f"Project {key}") if proj_info else f"Project {key}"

        dept_code = file_id[0] if file_id and file_id[0] in DEPARTMENT_CODES else "unknown"

        # Apply department filter if specified
        if department and dept_code != department:
            continue

        # Last activity date for this project
        last_activity = None
        if timeline and key in timeline:
            dates = [entry.get("date") for entry in timeline[key] if entry.get("date")]
            last_activity = max(dates) if dates else None

        by_department[dept_code].append(proj_name)
        all_projects.append({
            "project_key": key,
            "file_id": file_id,
            "name": proj_name,
            "department": DEPARTMENT_CODES.get(dept_code, {}).get("name", "Unknown"),
            "last_activity": last_activity
        })
    
    # Remove empty departments
    by_department = {k: v for k, v in by_department.items() if v}
    
    # Convert to {dept_name: [projects]} for readability
    by_department_named = {}
    for code, projects in by_department.items():
        dept_name = DEPARTMENT_CODES.get(code, {}).get("name", "Unknown")
        by_department_named[dept_name] = projects
    
    # Sort by last activity (most recent first)
    all_projects_sorted = sorted(
        all_projects,
        key=lambda p: p.get("last_activity") or "",
        reverse=True
    )

    return EmployeeProjectHistory(
        employee_id=resolved_id,
        employee_name=name,
        total_projects=len(all_projects_sorted),
        by_department=by_department_named,
        recent_projects=all_projects_sorted[:20]  # Most recent 20
    )
