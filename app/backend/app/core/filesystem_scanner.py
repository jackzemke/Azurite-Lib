"""
File system project scanner.
Scans raw_docs directory to catalog all projects and extract IDs.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging
import json

logger = logging.getLogger(__name__)


class FileSystemProjectScanner:
    """
    Scans the raw_docs directory to catalog projects and extract IDs.
    
    This provides a ground-truth view of what projects exist in the file system,
    which can be cross-referenced with Ajera data and the project mapping CSV.
    """
    
    def __init__(self, raw_docs_path: str):
        """
        Initialize scanner.
        
        Args:
            raw_docs_path: Path to raw_docs directory
        """
        self.raw_docs_path = Path(raw_docs_path)
        self.projects: Dict[str, Dict[str, Any]] = {}
        
    def scan(self) -> Dict[str, Dict[str, Any]]:
        """
        Scan raw_docs directory for projects.
        
        Returns:
            Dict mapping folder name to project info
        """
        self.projects = {}
        
        if not self.raw_docs_path.exists():
            logger.warning(f"raw_docs path does not exist: {self.raw_docs_path}")
            return self.projects
        
        # Scan top-level directories (project folders)
        for entry in self.raw_docs_path.iterdir():
            if entry.is_dir() and not entry.name.startswith('.'):
                project_info = self._analyze_project_folder(entry)
                self.projects[entry.name] = project_info
        
        logger.info(f"Scanned {len(self.projects)} projects from file system")
        return self.projects
    
    def _analyze_project_folder(self, folder: Path) -> Dict[str, Any]:
        """
        Analyze a project folder to extract metadata.
        
        Args:
            folder: Path to project folder
        
        Returns:
            Dict with project metadata
        """
        info = {
            "folder_name": folder.name,
            "path": str(folder),
            "file_ids": [],
            "subfolders": [],
            "document_count": 0,
        }
        
        # Try to extract ID from folder name
        extracted_id = self._extract_id(folder.name)
        if extracted_id:
            info["file_ids"].append(extracted_id)
        
        # Scan subfolders for IDs and count documents
        for item in folder.rglob("*"):
            if item.is_file():
                info["document_count"] += 1
            elif item.is_dir():
                # Check subfolder name for IDs
                subfolder_id = self._extract_id(item.name)
                if subfolder_id and subfolder_id not in info["file_ids"]:
                    info["file_ids"].append(subfolder_id)
                    
                # Record immediate subfolders only
                if item.parent == folder:
                    info["subfolders"].append(item.name)
        
        return info
    
    def _extract_id(self, name: str) -> Optional[str]:
        """
        Extract numeric/alphanumeric ID from a folder name.
        
        Patterns:
            - "Name (1430152)" -> "1430152"
            - "1430152-Name" -> "1430152"
            - "(1A29514)" -> "1A29514"
        
        Args:
            name: Folder name
        
        Returns:
            Extracted ID or None
        """
        # Pattern 1: Numeric ID in parentheses
        match = re.search(r'\((\d{5,8})\)', name)
        if match:
            return match.group(1)
        
        # Pattern 2: Alphanumeric ID in parentheses (e.g., 1A29514)
        match = re.search(r'\((\d+[A-Za-z]\d+)\)', name)
        if match:
            return match.group(1)
        
        # Pattern 3: ID at start followed by separator
        match = re.match(r'^(\d{5,8})[-_\s]', name)
        if match:
            return match.group(1)
        
        # Pattern 4: Pure numeric folder name
        if re.match(r'^\d{5,8}$', name.strip()):
            return name.strip()
        
        return None
    
    def get_project_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """
        Find project that contains a specific file ID.
        
        Args:
            file_id: File system ID to search for
        
        Returns:
            Project info dict or None
        """
        for folder_name, info in self.projects.items():
            if file_id in info.get("file_ids", []):
                return info
        return None
    
    def get_project_by_name(self, name_query: str) -> Optional[Dict[str, Any]]:
        """
        Find project by name (case-insensitive partial match).
        
        Args:
            name_query: Name to search for
        
        Returns:
            Project info dict or None
        """
        query_lower = name_query.lower()
        for folder_name, info in self.projects.items():
            if query_lower in folder_name.lower():
                return info
        return None
    
    def export_catalog(self, output_path: str) -> None:
        """
        Export project catalog to JSON file.
        
        Args:
            output_path: Path for output JSON file
        """
        catalog = {
            "scan_path": str(self.raw_docs_path),
            "total_projects": len(self.projects),
            "total_documents": sum(p.get("document_count", 0) for p in self.projects.values()),
            "projects": self.projects
        }
        
        with open(output_path, 'w') as f:
            json.dump(catalog, f, indent=2)
        
        logger.info(f"Exported project catalog to {output_path}")
