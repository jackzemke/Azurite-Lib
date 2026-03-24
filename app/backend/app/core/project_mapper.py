"""
Project ID mapper for bridging Ajera and file system identifiers.

The CSV mapping file contains:
- ProjectKey: Internal Ajera ID (used in time tracking)
- ID: File system project number (used in folder names)
- Description: Project name/title

This module provides bidirectional lookups and integrates with AjeraData.
"""

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import logging

logger = logging.getLogger(__name__)


class ProjectMapper:
    """
    Maps between Ajera ProjectKeys and file system IDs.
    
    CSV Structure:
        ProjectKey,ID,Description
        125259,1133234,La Plata County On Call Services/Contract Approved 4.24.24
    
    File system folders may contain the ID in various formats:
        - "1-NMED Acomita Day School (1430152)"  -> ID = 1430152
        - "1133234"                              -> ID = 1133234
        - "La Plata County Project"             -> Need name-based lookup
    """
    
    def __init__(self, csv_path: str):
        """
        Initialize with path to project_lookup.csv.
        
        Args:
            csv_path: Absolute path to project_lookup.csv
        """
        self.csv_path = Path(csv_path)
        
        # Bidirectional lookup maps
        self.key_to_id: Dict[str, str] = {}      # Ajera ProjectKey -> File System ID
        self.id_to_key: Dict[str, str] = {}      # File System ID -> Ajera ProjectKey
        
        # Additional lookups
        self.key_to_info: Dict[str, Dict[str, str]] = {}  # ProjectKey -> {id, description}
        self.id_to_info: Dict[str, Dict[str, str]] = {}   # ID -> {key, description}
        
        # Name-based search index (lowercase name -> list of project keys)
        self.name_index: Dict[str, List[str]] = {}

        # Parent-child relationship maps
        self.child_to_parent: Dict[str, str] = {}       # child prjKey -> parent prjKey
        self.parent_to_children: Dict[str, List[str]] = {}  # parent prjKey -> [child prjKeys]

        self._load_mapping()
    
    def _load_mapping(self) -> None:
        """Load project mapping from CSV file."""
        try:
            if not self.csv_path.exists():
                logger.warning(f"Project mapping file not found: {self.csv_path}")
                return
            
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    project_key = row.get("ProjectKey", "").strip()
                    file_id = row.get("ID", "").strip()
                    description = row.get("Description", "").strip()
                    
                    if not project_key or not file_id:
                        continue
                    
                    # Build bidirectional maps
                    self.key_to_id[project_key] = file_id
                    self.id_to_key[file_id] = project_key
                    
                    # Build info lookups
                    self.key_to_info[project_key] = {
                        "id": file_id,
                        "description": description
                    }
                    self.id_to_info[file_id] = {
                        "key": project_key,
                        "description": description
                    }
                    
                    # Build name index for search
                    name_lower = description.lower()
                    if name_lower not in self.name_index:
                        self.name_index[name_lower] = []
                    self.name_index[name_lower].append(project_key)

                    # Build parent-child maps (column added by ajera_sync)
                    parent_key = row.get("ParentProjectKey", "").strip()
                    if parent_key and parent_key != project_key:
                        self.child_to_parent[project_key] = parent_key
                        if parent_key not in self.parent_to_children:
                            self.parent_to_children[parent_key] = []
                        self.parent_to_children[parent_key].append(project_key)

            logger.info(
                f"Loaded project mapping: {len(self.key_to_id)} projects, "
                f"{len(self.child_to_parent)} child-parent links"
            )
            
        except Exception as e:
            logger.error(f"Failed to load project mapping: {e}")
    
    def get_file_id(self, project_key: str) -> Optional[str]:
        """
        Get file system ID from Ajera ProjectKey.
        
        Args:
            project_key: Ajera ProjectKey (e.g., "125259")
        
        Returns:
            File system ID (e.g., "1133234") or None if not found
        """
        return self.key_to_id.get(str(project_key))
    
    def get_project_key(self, file_id: str) -> Optional[str]:
        """
        Get Ajera ProjectKey from file system ID.
        
        Args:
            file_id: File system ID (e.g., "1133234")
        
        Returns:
            Ajera ProjectKey (e.g., "125259") or None if not found
        """
        return self.id_to_key.get(str(file_id))
    
    def get_project_info(self, identifier: str) -> Optional[Dict[str, str]]:
        """
        Get project info by either ProjectKey or file ID.
        
        Args:
            identifier: Either ProjectKey or file ID
        
        Returns:
            Dict with 'project_key', 'file_id', 'description' or None
        """
        # Try as ProjectKey first
        if identifier in self.key_to_info:
            info = self.key_to_info[identifier]
            return {
                "project_key": identifier,
                "file_id": info["id"],
                "description": info["description"]
            }
        
        # Try as file ID
        if identifier in self.id_to_info:
            info = self.id_to_info[identifier]
            return {
                "project_key": info["key"],
                "file_id": identifier,
                "description": info["description"]
            }
        
        return None
    
    def extract_id_from_folder(self, folder_name: str) -> Optional[str]:
        """
        Extract file system ID from a folder name.
        
        Common patterns:
            - "1-NMED Acomita Day School (1430152)" -> "1430152"
            - "1430152" -> "1430152"
            - "Project Name (ID)" -> "ID"
        
        Args:
            folder_name: Folder name to parse
        
        Returns:
            Extracted ID or None if not found
        """
        # Pattern 1: ID in parentheses at end, e.g., "Name (1430152)"
        match = re.search(r'\((\d{6,7})\)$', folder_name.strip())
        if match:
            return match.group(1)
        
        # Pattern 2: ID at start with dash, e.g., "1430152-Project Name"
        match = re.match(r'^(\d{6,7})-', folder_name)
        if match:
            return match.group(1)
        
        # Pattern 3: Just the ID (pure number)
        if re.match(r'^\d{6,7}$', folder_name.strip()):
            return folder_name.strip()
        
        # Pattern 4: Alphanumeric IDs like "1A29514"
        match = re.search(r'\((\d+[A-Za-z]\d+)\)$', folder_name.strip())
        if match:
            return match.group(1)
        
        match = re.match(r'^(\d+[A-Za-z]\d+)$', folder_name.strip())
        if match:
            return match.group(1)
        
        return None
    
    def resolve_folder_to_key(self, folder_name: str) -> Optional[str]:
        """
        Resolve a folder name to its Ajera ProjectKey.
        
        Tries multiple strategies:
            1. Extract ID from folder and lookup
            2. Direct name match
            3. Partial name match
        
        Args:
            folder_name: Project folder name
        
        Returns:
            Ajera ProjectKey or None if not resolved
        """
        # Strategy 1: Extract ID from folder name
        extracted_id = self.extract_id_from_folder(folder_name)
        if extracted_id:
            key = self.get_project_key(extracted_id)
            if key:
                return key
        
        # Strategy 2: Try folder name as-is (might be an ID)
        key = self.get_project_key(folder_name)
        if key:
            return key
        
        # Strategy 3: Name-based matching (exact match on description)
        folder_lower = folder_name.lower()
        for desc_lower, keys in self.name_index.items():
            if folder_lower == desc_lower:
                return keys[0]  # Return first match
        
        # Strategy 4: Partial name match (folder contained in description)
        for desc_lower, keys in self.name_index.items():
            if folder_lower in desc_lower or desc_lower in folder_lower:
                return keys[0]
        
        return None
    
    def search_projects(self, query: str, limit: int = 20) -> List[Dict[str, str]]:
        """
        Search projects by name/description.
        
        Args:
            query: Search query (partial match, case-insensitive)
            limit: Maximum results to return
        
        Returns:
            List of project info dicts
        """
        results = []
        query_lower = query.lower()
        
        for project_key, info in self.key_to_info.items():
            description = info.get("description", "")
            if query_lower in description.lower():
                results.append({
                    "project_key": project_key,
                    "file_id": info["id"],
                    "description": description
                })
                
                if len(results) >= limit:
                    break
        
        return results
    
    def get_all_mappings(self) -> List[Dict[str, str]]:
        """
        Get all project mappings.
        
        Returns:
            List of all project info dicts
        """
        return [
            {
                "project_key": key,
                "file_id": info["id"],
                "description": info["description"]
            }
            for key, info in self.key_to_info.items()
        ]
    
    def get_stats(self) -> Dict[str, int]:
        """Get mapping statistics."""
        return {
            "total_projects": len(self.key_to_id),
            "unique_descriptions": len(self.name_index),
            "child_parent_links": len(self.child_to_parent),
        }

    def resolve_child_to_file_id(self, child_key: str) -> Optional[str]:
        """
        Resolve a child/phase prjKey to a file system ID (prjID).

        Walks up the parent chain if the child itself doesn't have
        a meaningful file system ID.

        Args:
            child_key: Child/phase Ajera ProjectKey

        Returns:
            File system ID (prjID) or None
        """
        current = str(child_key)
        # Try direct lookup first, then walk up (max 5 levels)
        for _ in range(6):
            file_id = self.key_to_id.get(current)
            if file_id:
                return file_id
            parent = self.child_to_parent.get(current)
            if not parent:
                break
            current = parent
        return None

    def get_parent_key(self, child_key: str) -> Optional[str]:
        """Get the parent/master project key for a child project."""
        return self.child_to_parent.get(str(child_key))

    def get_children_keys(self, parent_key: str) -> List[str]:
        """Get all child/phase project keys for a parent project."""
        return self.parent_to_children.get(str(parent_key), [])


# Global instance
_project_mapper: Optional[ProjectMapper] = None


def init_project_mapper(csv_path: str) -> None:
    """
    Initialize global ProjectMapper instance.
    Call this on app startup.
    
    Args:
        csv_path: Path to project_lookup.csv
    """
    global _project_mapper
    _project_mapper = ProjectMapper(csv_path)


def get_project_mapper() -> ProjectMapper:
    """
    Get the global ProjectMapper instance.
    
    Returns:
        ProjectMapper instance
    
    Raises:
        RuntimeError: If ProjectMapper not initialized
    """
    if _project_mapper is None:
        raise RuntimeError("ProjectMapper not initialized. Call init_project_mapper() first.")
    
    return _project_mapper
