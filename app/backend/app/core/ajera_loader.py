"""
Ajera data loader and utilities.
Loads employee-project mappings from Ajera time series JSON.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class AjeraData:
    """
    Manages employee-project mappings from Ajera.
    Loaded once on startup and cached in memory.
    """
    
    def __init__(self, data_path: str):
        """
        Initialize with path to ajera_time_series.json.
        
        Args:
            data_path: Absolute path to ajera_time_series.json
        """
        self.data_path = Path(data_path)
        self.data: Optional[Dict[str, Any]] = None
        self._load_data()
    
    def _load_data(self) -> None:
        """Load Ajera data from JSON file."""
        try:
            if not self.data_path.exists():
                logger.warning(f"Ajera data file not found: {self.data_path}")
                self.data = {
                    "employee_to_projects": {},
                    "project_to_employees": {},
                    "metadata": {}
                }
                return
            
            with open(self.data_path, 'r') as f:
                self.data = json.load(f)
            
            logger.info(f"✓ Loaded Ajera data: {self.data.get('metadata', {})}")
            
        except Exception as e:
            logger.error(f"Failed to load Ajera data: {e}")
            self.data = {
                "employee_to_projects": {},
                "project_to_employees": {},
                "metadata": {}
            }
    
    def get_employee_projects(self, employee_id: str) -> List[str]:
        """
        Get list of project IDs for an employee.
        
        Args:
            employee_id: Employee ID (as string)
        
        Returns:
            List of project IDs (as strings)
        """
        if not self.data:
            return []
        
        emp_data = self.data.get("employee_to_projects", {}).get(str(employee_id))
        if not emp_data:
            return []
        
        return emp_data.get("projects", [])
    
    def get_employee_name(self, employee_id: str) -> Optional[str]:
        """
        Get employee name.
        
        Args:
            employee_id: Employee ID (as string)
        
        Returns:
            Employee name or None if not found
        """
        if not self.data:
            return None
        
        emp_data = self.data.get("employee_to_projects", {}).get(str(employee_id))
        if not emp_data:
            return None
        
        return emp_data.get("name")
    
    def get_employee_id_by_name(self, name: str) -> Optional[str]:
        """
        Get employee ID by name (case-insensitive partial match).
        
        Args:
            name: Employee name or partial name
        
        Returns:
            Employee ID or None if not found
        """
        if not self.data:
            return None
        
        name_lower = name.lower().strip()
        
        # First try exact match
        for emp_id, emp_data in self.data.get("employee_to_projects", {}).items():
            emp_name = emp_data.get("name", "")
            if emp_name.lower() == name_lower:
                return emp_id
        
        # Then try partial match (contains)
        for emp_id, emp_data in self.data.get("employee_to_projects", {}).items():
            emp_name = emp_data.get("name", "")
            if name_lower in emp_name.lower():
                return emp_id
        
        return None
    
    def search_employees_by_name(self, query: str, limit: int = 10) -> List[Dict[str, str]]:
        """
        Search employees by name (partial match).
        
        Args:
            query: Search query string
            limit: Maximum number of results
        
        Returns:
            List of dicts with 'employee_id' and 'name' keys
        """
        if not self.data:
            return []
        
        query_lower = query.lower().strip()
        results = []
        
        for emp_id, emp_data in self.data.get("employee_to_projects", {}).items():
            emp_name = emp_data.get("name", "")
            if query_lower in emp_name.lower():
                results.append({
                    "employee_id": emp_id,
                    "name": emp_name
                })
                
                if len(results) >= limit:
                    break
        
        return results
    
    def get_project_info(self, project_id: str) -> Optional[Dict[str, Any]]:
        """
        Get project information including enriched metadata.
        
        Args:
            project_id: Project ID (as string)
        
        Returns:
            Dict with 'name', 'employees', and 'metadata' keys, or None if not found
        """
        if not self.data:
            return None
        
        proj_data = self.data.get("project_to_employees", {}).get(str(project_id))
        if not proj_data:
            return None
        
        return {
            "name": proj_data.get("name", ""),
            "employees": proj_data.get("employees", []),
            "metadata": proj_data.get("metadata", {})
        }
    
    def get_project_employees(self, project_id: str) -> List[str]:
        """
        Get list of employee IDs for a project.
        
        Args:
            project_id: Project ID (as string)
        
        Returns:
            List of employee IDs (as strings)
        """
        proj_info = self.get_project_info(project_id)
        if not proj_info:
            return []
        
        return proj_info.get("employees", [])
    
    def search_projects_by_name(self, query: str, limit: int = 10) -> List[Dict[str, str]]:
        """
        Search projects by name (simple substring match).
        
        Args:
            query: Search query string
            limit: Maximum number of results
        
        Returns:
            List of dicts with 'project_id' and 'name' keys
        """
        if not self.data:
            return []
        
        query_lower = query.lower()
        results = []
        
        for proj_id, proj_data in self.data.get("project_to_employees", {}).items():
            proj_name = proj_data.get("name", "")
            if query_lower in proj_name.lower():
                results.append({
                    "project_id": proj_id,
                    "name": proj_name
                })
                
                if len(results) >= limit:
                    break
        
        return results
    
    def search_projects_by_metadata(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Search projects by metadata (name, location, marketing fields, etc.).
        
        Args:
            query: Search query string
            limit: Maximum number of results
        
        Returns:
            List of dicts with project_id, name, and match details
        """
        if not self.data:
            return []
        
        query_lower = query.lower()
        results = []
        
        for proj_id, proj_data in self.data.get("project_to_employees", {}).items():
            metadata = proj_data.get("metadata", {})
            proj_name = metadata.get("name", "")
            
            # Search in multiple fields
            searchable_fields = [
                ("name", proj_name),
                ("location", metadata.get("location", "")),
                ("project_type", metadata.get("project_type", "")),
                ("marketing_description", metadata.get("marketing_description", "")),
                ("marketing_scope", metadata.get("marketing_scope", "")),
                ("notes", metadata.get("notes", ""))
            ]
            
            match_found = False
            match_fields = []
            
            for field_name, field_value in searchable_fields:
                if field_value and query_lower in str(field_value).lower():
                    match_found = True
                    match_fields.append(field_name)
            
            if match_found:
                results.append({
                    "project_id": proj_id,
                    "name": proj_name,
                    "location": metadata.get("location"),
                    "project_type": metadata.get("project_type"),
                    "match_fields": match_fields,
                    "employee_count": len(proj_data.get("employees", []))
                })
                
                if len(results) >= limit:
                    break
        
        return results
    
    def get_project_team_with_hours(self, project_id: str) -> List[Dict[str, Any]]:
        """
        Get all employees who worked on a project with their hours.
        
        Args:
            project_id: Project ID
        
        Returns:
            List of dicts with employee_id, name, total_hours sorted by hours desc
        """
        if not self.data:
            return []
        
        project_data = self.data.get("project_to_employees", {}).get(project_id)
        if not project_data:
            return []
        
        team = []
        employee_ids = project_data.get("employees", [])
        
        for emp_id in employee_ids:
            emp_data = self.data.get("employee_to_projects", {}).get(emp_id, {})
            emp_name = emp_data.get("name", f"Employee {emp_id}")
            
            # Calculate hours for this specific project
            timeline = emp_data.get("timeline", {}).get(project_id, [])
            total_hours = sum(entry.get("hours", 0) for entry in timeline)
            
            team.append({
                "employee_id": emp_id,
                "name": emp_name,
                "total_hours": round(total_hours, 2)
            })
        
        # Sort by hours descending
        team.sort(key=lambda x: x["total_hours"], reverse=True)
        return team
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get Ajera data metadata (counts, date ranges, etc.)."""
        if not self.data:
            return {}
        
        return self.data.get("metadata", {})
    
    def reload(self) -> None:
        """Reload data from file (for periodic refresh)."""
        logger.info("Reloading Ajera data...")
        self._load_data()


# Global instance (initialized in main.py)
_ajera_data: Optional[AjeraData] = None


def init_ajera_data(data_path: str) -> None:
    """
    Initialize global Ajera data instance.
    Call this on app startup.
    
    Args:
        data_path: Path to ajera_unified.json (or ajera_time_series.json)
    """
    global _ajera_data
    _ajera_data = AjeraData(data_path)


def get_ajera_data() -> AjeraData:
    """
    Get the global Ajera data instance.
    
    Returns:
        AjeraData instance
    
    Raises:
        RuntimeError: If Ajera data not initialized
    """
    if _ajera_data is None:
        raise RuntimeError("Ajera data not initialized. Call init_ajera_data() first.")
    
    return _ajera_data
