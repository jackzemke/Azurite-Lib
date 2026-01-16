"""
Ajera data API endpoints.
Provides access to employee and project information.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel

from ..core.ajera_loader import get_ajera_data

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
