"""
Project mapping API endpoints.
Provides access to project ID mappings between Ajera and file system.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from ..core.project_mapper import get_project_mapper
from ..core.ajera_loader import get_ajera_data
from ..core.project_resolver import get_project_resolver

router = APIRouter()


class ProjectMapping(BaseModel):
    """Project ID mapping between Ajera and file system."""
    project_key: str        # Ajera internal key (for time tracking)
    file_id: str            # File system ID (in folder names)
    description: str        # Project name/title


class ProjectDetail(BaseModel):
    """Detailed project information combining mapping and Ajera data."""
    project_key: str
    file_id: str
    description: str
    employee_count: Optional[int] = None
    employees: Optional[List[str]] = None
    has_time_tracking: bool = False


class MappingStats(BaseModel):
    """Statistics about project mappings."""
    total_projects: int
    projects_with_time_tracking: int
    unique_descriptions: int


@router.get("/projects/mappings", response_model=List[ProjectMapping])
async def list_project_mappings(
    search: Optional[str] = Query(None, description="Search projects by name"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results to return")
):
    """
    List all project mappings or search by name.
    
    This endpoint returns the mapping between:
    - **project_key**: Ajera internal ID (used for time tracking)
    - **file_id**: File system ID (used in folder names like "Project Name (1430152)")
    - **description**: Project name/title
    
    Use this to resolve project IDs when querying employee work history.
    """
    mapper = get_project_mapper()
    
    if search:
        results = mapper.search_projects(search, limit=limit)
    else:
        results = mapper.get_all_mappings()[:limit]
    
    return [
        ProjectMapping(
            project_key=r["project_key"],
            file_id=r["file_id"],
            description=r["description"]
        )
        for r in results
    ]


@router.get("/projects/mappings/stats", response_model=MappingStats)
async def get_mapping_stats():
    """
    Get statistics about project mappings.
    
    Returns counts of:
    - Total projects in mapping file
    - Projects that also have time tracking data in Ajera
    - Unique project descriptions
    """
    mapper = get_project_mapper()
    ajera = get_ajera_data()
    
    stats = mapper.get_stats()
    
    # Count how many mapped projects have Ajera time tracking
    projects_with_tracking = 0
    for project_key in mapper.key_to_id.keys():
        if ajera.get_project_info(project_key):
            projects_with_tracking += 1
    
    return MappingStats(
        total_projects=stats["total_projects"],
        projects_with_time_tracking=projects_with_tracking,
        unique_descriptions=stats["unique_descriptions"]
    )


@router.get("/projects/resolve/{identifier}", response_model=ProjectDetail)
async def resolve_project(identifier: str):
    """
    Resolve a project identifier to full details.
    
    The identifier can be:
    - An Ajera ProjectKey (e.g., "125259")
    - A file system ID (e.g., "1133234")
    - A folder name (e.g., "1-NMED Acomita Day School (1430152)")
    
    Returns combined information from both the mapping file and Ajera time tracking.
    """
    mapper = get_project_mapper()
    ajera = get_ajera_data()
    
    # Try direct lookup first
    info = mapper.get_project_info(identifier)
    
    # If not found, try to parse as folder name
    if not info:
        project_key = mapper.resolve_folder_to_key(identifier)
        if project_key:
            info = mapper.get_project_info(project_key)
    
    if not info:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{identifier}' not found in mappings"
        )
    
    # Get Ajera time tracking data if available
    ajera_info = ajera.get_project_info(info["project_key"])
    
    return ProjectDetail(
        project_key=info["project_key"],
        file_id=info["file_id"],
        description=info["description"],
        employee_count=len(ajera_info.get("employees", [])) if ajera_info else None,
        employees=ajera_info.get("employees", [])[:10] if ajera_info else None,  # First 10
        has_time_tracking=ajera_info is not None
    )


@router.get("/projects/folder/{folder_name:path}", response_model=ProjectDetail)
async def resolve_folder(folder_name: str):
    """
    Resolve a folder name to project details.
    
    Handles common folder naming patterns:
    - "1-NMED Acomita Day School (1430152)" -> extracts ID 1430152
    - "1430152" -> direct ID lookup
    - "Project Name" -> name-based matching
    
    This is useful when processing the file system to find matching Ajera data.
    """
    mapper = get_project_mapper()
    ajera = get_ajera_data()
    
    # Try to resolve folder to project key
    project_key = mapper.resolve_folder_to_key(folder_name)
    
    if not project_key:
        # Try extracted ID directly
        extracted_id = mapper.extract_id_from_folder(folder_name)
        if extracted_id:
            raise HTTPException(
                status_code=404,
                detail=f"Found ID '{extracted_id}' in folder name but no mapping exists. "
                       f"This project may not be in the lookup file yet."
            )
        raise HTTPException(
            status_code=404,
            detail=f"Could not resolve folder '{folder_name}' to a project"
        )
    
    info = mapper.get_project_info(project_key)
    ajera_info = ajera.get_project_info(project_key)
    
    return ProjectDetail(
        project_key=info["project_key"],
        file_id=info["file_id"],
        description=info["description"],
        employee_count=len(ajera_info.get("employees", [])) if ajera_info else None,
        employees=ajera_info.get("employees", [])[:10] if ajera_info else None,
        has_time_tracking=ajera_info is not None
    )


@router.get("/employees/{employee_id}/projects/detailed", response_model=List[ProjectDetail])
async def get_employee_projects_detailed(
    employee_id: str,
    limit: int = Query(50, ge=1, le=200, description="Maximum projects to return")
):
    """
    Get detailed project information for an employee's work history.
    
    Unlike the basic employee projects endpoint, this returns full project details
    including file system IDs and descriptions from the mapping file.
    
    This is useful for:
    - Showing an employee's complete work history with project names
    - Building project selection dropdowns filtered to employee's projects
    - Resolving Ajera ProjectKeys to file system locations
    """
    ajera = get_ajera_data()
    mapper = get_project_mapper()
    
    # Resolve employee ID if name provided
    resolved_id = employee_id
    if not employee_id.isdigit():
        resolved_id = ajera.get_employee_id_by_name(employee_id)
        if not resolved_id:
            raise HTTPException(
                status_code=404,
                detail=f"Employee '{employee_id}' not found"
            )
    
    # Get employee's projects from Ajera (these are ProjectKeys)
    project_keys = ajera.get_employee_projects(resolved_id)
    
    if not project_keys:
        return []
    
    # Enrich with mapping data
    results = []
    for key in project_keys[:limit]:
        # Try to get mapping info
        mapping_info = mapper.get_project_info(key)
        ajera_info = ajera.get_project_info(key)
        
        if mapping_info:
            results.append(ProjectDetail(
                project_key=key,
                file_id=mapping_info["file_id"],
                description=mapping_info["description"],
                employee_count=len(ajera_info.get("employees", [])) if ajera_info else None,
                employees=None,  # Don't include full list for performance
                has_time_tracking=True
            ))
        else:
            # Project exists in Ajera but not in mapping file
            results.append(ProjectDetail(
                project_key=key,
                file_id="",  # Unknown
                description=ajera_info.get("name", "") if ajera_info else f"Project {key}",
                employee_count=len(ajera_info.get("employees", [])) if ajera_info else None,
                employees=None,
                has_time_tracking=True
            ))
    
    return results


# =============================================================================
# Unified Project Resolver Endpoints
# =============================================================================

class UnifiedProjectInfo(BaseModel):
    """Complete project information from all sources."""
    identifier: str
    folder_name: Optional[str] = None
    file_id: Optional[str] = None
    project_key: Optional[str] = None
    description: Optional[str] = None
    in_filesystem: bool = False
    in_mapping: bool = False
    in_ajera: bool = False
    employee_count: int = 0
    document_count: int = 0


class EmployeeFolders(BaseModel):
    """Employee's projects resolved to file system folders."""
    employee_id: str
    employee_name: Optional[str] = None
    total_ajera_projects: int
    resolved_folders: List[str]
    unresolved_project_keys: List[str]


@router.get("/projects/unified/{identifier}", response_model=UnifiedProjectInfo)
async def get_unified_project_info(identifier: str):
    """
    Get complete project information by resolving across all data sources.
    
    The identifier can be:
    - An Ajera ProjectKey (e.g., "125259")
    - A file system ID (e.g., "1133234")
    - A folder name (e.g., "Acomita Day School")
    
    Returns combined information showing what's available in:
    - File system (raw_docs)
    - Project mapping CSV
    - Ajera time tracking
    """
    resolver = get_project_resolver()
    
    info = resolver.get_project_full_info(identifier)
    
    if not info:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{identifier}' not found in any data source"
        )
    
    return UnifiedProjectInfo(**info)


@router.get("/employees/{employee_id}/folders", response_model=EmployeeFolders)
async def get_employee_project_folders(employee_id: str):
    """
    Get file system folder names for an employee's projects.
    
    This is the key endpoint for filtering document searches by employee.
    It resolves Ajera ProjectKeys to actual folder names in raw_docs.
    
    Returns:
    - resolved_folders: Folder names that can be used to filter ChromaDB
    - unresolved_project_keys: Ajera projects with no matching folder
    """
    resolver = get_project_resolver()
    ajera = get_ajera_data()
    
    # Resolve employee ID if name
    resolved_id = employee_id
    if not employee_id.isdigit():
        resolved_id = ajera.get_employee_id_by_name(employee_id)
        if not resolved_id:
            raise HTTPException(
                status_code=404,
                detail=f"Employee '{employee_id}' not found"
            )
    
    employee_name = ajera.get_employee_name(resolved_id)
    project_keys = ajera.get_employee_projects(resolved_id)
    
    # Resolve each project to folder name
    resolved_folders = []
    unresolved = []
    
    for key in project_keys:
        folder = resolver.resolve_to_folder_name(key)
        if folder:
            if folder not in resolved_folders:
                resolved_folders.append(folder)
        else:
            unresolved.append(key)
    
    return EmployeeFolders(
        employee_id=resolved_id,
        employee_name=employee_name,
        total_ajera_projects=len(project_keys),
        resolved_folders=resolved_folders,
        unresolved_project_keys=unresolved
    )


@router.get("/projects/diagnostics")
async def get_project_diagnostics():
    """
    Get diagnostic information about project data quality.
    
    Shows:
    - Projects in file system but not in mapping/Ajera
    - Projects in Ajera but not in file system
    - Overall match statistics
    
    Use this to identify data gaps that need attention.
    """
    resolver = get_project_resolver()
    
    return resolver.find_unmatched_projects()