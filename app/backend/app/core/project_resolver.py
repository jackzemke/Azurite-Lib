"""
Unified project resolver.
Combines data from file system, Ajera time tracking, and project mapping CSV.
"""

from typing import Dict, List, Optional, Any, Set
from pathlib import Path
import logging

from .project_mapper import get_project_mapper, ProjectMapper
from .ajera_loader import get_ajera_data, AjeraData
from .filesystem_scanner import FileSystemProjectScanner
from ..config import settings

logger = logging.getLogger(__name__)


class UnifiedProjectResolver:
    """
    Resolves project identifiers across multiple data sources:

    1. File System (raw_docs folders)
       - folder_name: "Acomita Day School"
       - file_id: Extracted from folder names (e.g., "1430152")

    2. Ajera Time Tracking (ajera_unified.json)
       - project_key: Ajera internal ID for time tracking
       - Has employee-project mappings and hours

    3. Project Mapping CSV (project_lookup.csv)
       - Maps project_key <-> file_id
       - Has project descriptions/names

    Use Cases:
    - Given an employee ID, find all their projects in the file system
    - Given a folder name, find who worked on it
    - Given a project name, resolve to file system location
    """

    def __init__(
        self,
        mapper: Optional[ProjectMapper] = None,
        ajera: Optional[AjeraData] = None,
        raw_docs_path: Optional[str] = None
    ):
        """
        Initialize with data sources.

        If not provided, will use global instances.

        Args:
            mapper: ProjectMapper instance
            ajera: AjeraData instance
            raw_docs_path: Path to raw_docs for file system scanning
        """
        self._mapper = mapper
        self._ajera = ajera
        self._raw_docs_path = raw_docs_path or str(settings.raw_docs_path)
        self._fs_scanner: Optional[FileSystemProjectScanner] = None
        self._fs_scanned = False
    
    @property
    def mapper(self) -> ProjectMapper:
        """Get ProjectMapper (lazy load from global)."""
        if self._mapper is None:
            self._mapper = get_project_mapper()
        return self._mapper
    
    @property
    def ajera(self) -> AjeraData:
        """Get AjeraData (lazy load from global)."""
        if self._ajera is None:
            self._ajera = get_ajera_data()
        return self._ajera
    
    def _ensure_fs_scan(self) -> None:
        """Ensure file system has been scanned."""
        if not self._fs_scanned:
            self._fs_scanner = FileSystemProjectScanner(self._raw_docs_path)
            self._fs_scanner.scan()
            self._fs_scanned = True
    
    def resolve_to_folder_name(self, identifier: str) -> Optional[str]:
        """
        Resolve any identifier to a file system folder name.
        
        This is what ChromaDB needs for filtering.
        
        Args:
            identifier: Can be:
                - Ajera project_key (e.g., "125259")
                - File system ID (e.g., "1133234")
                - Folder name (e.g., "Acomita Day School")
        
        Returns:
            Folder name that matches raw_docs structure, or None
        """
        self._ensure_fs_scan()
        
        # Try direct folder name match first
        if identifier in self._fs_scanner.projects:
            return identifier
        
        # Try as file ID
        project = self._fs_scanner.get_project_by_id(identifier)
        if project:
            return project["folder_name"]
        
        # Try to resolve via mapper (project_key -> file_id -> folder)
        # Uses parent-chain resolution: child prjKey -> parent prjKey -> prjID
        file_id = self.mapper.resolve_child_to_file_id(identifier)
        if file_id:
            project = self._fs_scanner.get_project_by_id(file_id)
            if project:
                return project["folder_name"]
        
        # Try reverse: identifier might be file_id, get project_key, then search
        project_key = self.mapper.get_project_key(identifier)
        if project_key:
            # Check if project_key is in fs by name matching
            project_info = self.mapper.get_project_info(project_key)
            if project_info:
                project = self._fs_scanner.get_project_by_name(project_info["description"])
                if project:
                    return project["folder_name"]
        
        # Last resort: name-based search
        project = self._fs_scanner.get_project_by_name(identifier)
        if project:
            return project["folder_name"]
        
        return None
    
    def get_employee_folder_names(self, employee_id: str) -> List[str]:
        """
        Get all folder names for projects an employee worked on.
        
        This is the key function for filtering ChromaDB queries by employee.
        
        Args:
            employee_id: Ajera employee ID
        
        Returns:
            List of folder names that exist in raw_docs
        """
        # Get project keys from Ajera
        project_keys = self.ajera.get_employee_projects(employee_id)
        
        if not project_keys:
            return []
        
        folder_names = []
        for key in project_keys:
            folder_name = self.resolve_to_folder_name(key)
            if folder_name:
                folder_names.append(folder_name)
        
        return folder_names
    
    def get_project_full_info(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Get complete project information from all sources.
        
        Args:
            identifier: Any project identifier
        
        Returns:
            Dict with combined info from all sources
        """
        self._ensure_fs_scan()
        
        info = {
            "identifier": identifier,
            "folder_name": None,
            "file_id": None,
            "project_key": None,
            "description": None,
            "in_filesystem": False,
            "in_mapping": False,
            "in_ajera": False,
            "employee_count": 0,
            "document_count": 0,
        }
        
        # Try to get folder name
        folder_name = self.resolve_to_folder_name(identifier)
        if folder_name:
            info["folder_name"] = folder_name
            info["in_filesystem"] = True
            
            fs_project = self._fs_scanner.projects.get(folder_name)
            if fs_project:
                info["document_count"] = fs_project.get("document_count", 0)
                # Get file_id from fs
                if fs_project.get("file_ids"):
                    info["file_id"] = fs_project["file_ids"][0]
        
        # Try mapping lookup
        map_info = self.mapper.get_project_info(identifier)
        if map_info:
            info["project_key"] = map_info["project_key"]
            info["file_id"] = info["file_id"] or map_info["file_id"]
            info["description"] = map_info["description"]
            info["in_mapping"] = True
        
        # Try Ajera lookup
        if info["project_key"]:
            ajera_info = self.ajera.get_project_info(info["project_key"])
            if ajera_info:
                info["in_ajera"] = True
                info["employee_count"] = len(ajera_info.get("employees", []))
                info["description"] = info["description"] or ajera_info.get("name")
        
        # If we found nothing, return None
        if not any([info["in_filesystem"], info["in_mapping"], info["in_ajera"]]):
            return None
        
        return info
    
    def find_unmatched_projects(self) -> Dict[str, List[str]]:
        """
        Find projects that exist in one system but not others.
        
        Useful for data quality reporting.
        
        Returns:
            Dict with:
                - fs_only: Folders with no Ajera/mapping match
                - ajera_only: Ajera projects with no folder match
                - mapping_only: Mapping entries with no folder match
        """
        self._ensure_fs_scan()
        
        fs_folders = set(self._fs_scanner.projects.keys())
        mapping_ids = set(self.mapper.id_to_key.keys())
        
        # Get all Ajera project keys
        ajera_keys = set()
        if self.ajera.data:
            ajera_keys = set(self.ajera.data.get("project_to_employees", {}).keys())
        
        # Find matches
        fs_matched = set()
        ajera_matched = set()
        mapping_matched = set()
        
        for folder in fs_folders:
            # Check if this folder has a matching Ajera project
            folder_key = self.resolve_to_folder_name(folder)
            if folder_key:
                # Try to find the project_key
                fs_info = self._fs_scanner.projects.get(folder)
                for file_id in fs_info.get("file_ids", []):
                    project_key = self.mapper.get_project_key(file_id)
                    if project_key:
                        fs_matched.add(folder)
                        mapping_matched.add(file_id)
                        if project_key in ajera_keys:
                            ajera_matched.add(project_key)
        
        return {
            "fs_only": list(fs_folders - fs_matched),
            "ajera_only": list(ajera_keys - ajera_matched),
            "mapping_only": list(mapping_ids - mapping_matched),
            "summary": {
                "total_fs": len(fs_folders),
                "total_mapping": len(mapping_ids),
                "total_ajera": len(ajera_keys),
                "matched_fs": len(fs_matched),
            }
        }
    
    def resolve_folder_to_ajera_key(self, folder_name: str) -> Optional[str]:
        """
        Resolve a folder name to an Ajera project key.
        
        This is needed to look up team/hours data in Ajera from ChromaDB project_id.
        
        Args:
            folder_name: Folder name from raw_docs (e.g., "4-Las Vegas Transfer Station Expansion (4229854)")
        
        Returns:
            Ajera project_key (e.g., "4229854") or None
        """
        self._ensure_fs_scan()
        
        # Get file system info for this folder
        fs_project = self._fs_scanner.projects.get(folder_name)
        if not fs_project:
            return None
        
        # Try each file_id extracted from the folder name
        p2e = self.ajera.data.get("project_to_employees", {}) if self.ajera.data else {}
        for file_id in fs_project.get("file_ids", []):
            # Use mapper: file_id -> project_key (this is a parent key)
            project_key = self.mapper.get_project_key(file_id)
            if project_key:
                # Check if parent key itself is in Ajera
                if project_key in p2e:
                    return project_key
                # Parent not in Ajera (time entries are on children) —
                # find a child that has time entries
                for child_key in self.mapper.get_children_keys(project_key):
                    if child_key in p2e:
                        return child_key

        # Fallback: Check if any file_id IS the project_key directly
        for file_id in fs_project.get("file_ids", []):
            if file_id in p2e:
                return file_id
        
        return None
    
    def get_project_team_from_folder(self, folder_name: str) -> List[Dict[str, Any]]:
        """
        Get team info for a project from its folder name.
        
        Convenience method that resolves folder -> Ajera key -> team data.
        
        Args:
            folder_name: Folder name from raw_docs
        
        Returns:
            List of team members with hours (same as AjeraData.get_project_team_with_hours)
        """
        project_key = self.resolve_folder_to_ajera_key(folder_name)
        if not project_key:
            logger.debug(f"Could not resolve folder '{folder_name}' to Ajera project key")
            return []
        
        return self.ajera.get_project_team_with_hours(project_key)


# Global instance
_resolver: Optional[UnifiedProjectResolver] = None


def init_project_resolver() -> None:
    """Initialize global resolver instance."""
    global _resolver
    _resolver = UnifiedProjectResolver()


def get_project_resolver() -> UnifiedProjectResolver:
    """Get global resolver instance."""
    if _resolver is None:
        # Lazy init
        init_project_resolver()
    return _resolver
