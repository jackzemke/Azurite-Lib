"""
SMA Department code utilities.

The first digit of the file system project ID indicates the department:
    1 - Environmental (ESAs, Asbestos, Wetlands, NEPA)
    2 - Survey (Boundary, platting, construction staking)
    3 - Remediation/UST (Underground storage tanks, gas stations)
    4 - Solid Waste (Landfills, transfer stations)
    5 - Oil & Gas (SPCC plans)
    6 - Water (Water systems, WWTP, distribution)
    7 - Transportation (NMDOT, roads, trails)
    8 - Admin/Solar/Other (Solar, IT services, asset management)
    9 - General Civil (Site development, civil design)
"""

from typing import Dict, List, Optional, Tuple
import re


# Department code mapping
DEPARTMENT_CODES: Dict[str, Dict[str, str]] = {
    "1": {
        "code": "1",
        "name": "Environmental",
        "short": "ENV",
        "description": "Environmental assessments, asbestos surveys, wetlands, NEPA compliance",
        "keywords": ["environmental", "esa", "phase i", "phase ii", "asbestos", "wetland", 
                     "nepa", "hazardous", "contamination", "soil", "groundwater", "remediation survey"]
    },
    "2": {
        "code": "2",
        "name": "Survey",
        "short": "SRV",
        "description": "Boundary surveys, platting, construction staking, topographic surveys",
        "keywords": ["survey", "boundary", "plat", "staking", "topographic", "mapping", 
                     "subdivision", "alta", "easement"]
    },
    "3": {
        "code": "3",
        "name": "Remediation/UST",
        "short": "REM",
        "description": "Underground storage tanks, bulk plants, gas station remediation",
        "keywords": ["ust", "underground storage", "bulk plant", "gas station", "petroleum",
                     "tank removal", "fuel", "release", "corrective action"]
    },
    "4": {
        "code": "4",
        "name": "Solid Waste",
        "short": "SWM",
        "description": "Landfills, transfer stations, solid waste facilities",
        "keywords": ["landfill", "solid waste", "transfer station", "recycling", "disposal",
                     "waste management", "composting", "closure"]
    },
    "5": {
        "code": "5",
        "name": "Oil & Gas",
        "short": "O&G",
        "description": "SPCC plans, oil and gas facilities, pipeline work",
        "keywords": ["oil", "gas", "spcc", "pipeline", "wellhead", "drilling", "ocd",
                     "petroleum", "natural gas", "midstream"]
    },
    "6": {
        "code": "6",
        "name": "Water",
        "short": "WTR",
        "description": "Water systems, wastewater treatment, distribution infrastructure",
        "keywords": ["water", "wastewater", "wwtp", "distribution", "sewer", "treatment",
                     "drinking water", "well", "storage tank", "pump station", "collection"]
    },
    "7": {
        "code": "7",
        "name": "Transportation",
        "short": "TRN",
        "description": "NMDOT projects, roads, trails, bridges",
        "keywords": ["transportation", "road", "highway", "bridge", "trail", "nmdot",
                     "pavement", "intersection", "traffic", "dot"]
    },
    "8": {
        "code": "8",
        "name": "Admin/Solar/Other",
        "short": "ADM",
        "description": "Solar projects, IT services, asset management, administrative",
        "keywords": ["solar", "admin", "administrative", "it services", "asset management",
                     "renewable", "energy", "funding", "grant"]
    },
    "9": {
        "code": "9",
        "name": "General Civil",
        "short": "CIV",
        "description": "Site development, civil design, general engineering",
        "keywords": ["civil", "site development", "grading", "drainage", "stormwater",
                     "design", "engineering", "construction", "development"]
    }
}


def get_department_from_file_id(file_id: str) -> Optional[Dict[str, str]]:
    """
    Get department info from a file system project ID.
    
    Args:
        file_id: Project file ID (e.g., "1430152", "6128405")
    
    Returns:
        Department info dict or None if unknown
    """
    if not file_id or len(file_id) < 1:
        return None
    
    first_digit = file_id[0]
    return DEPARTMENT_CODES.get(first_digit)


def get_department_code(file_id: str) -> Optional[str]:
    """
    Get just the department code from a file ID.
    
    Args:
        file_id: Project file ID
    
    Returns:
        Single digit code (e.g., "1", "6") or None
    """
    if not file_id or len(file_id) < 1:
        return None
    
    first_digit = file_id[0]
    return first_digit if first_digit in DEPARTMENT_CODES else None


def get_department_name(file_id: str) -> Optional[str]:
    """
    Get human-readable department name from a file ID.
    
    Args:
        file_id: Project file ID
    
    Returns:
        Department name (e.g., "Environmental", "Water") or None
    """
    dept = get_department_from_file_id(file_id)
    return dept["name"] if dept else None


def infer_department_from_query(query: str) -> List[str]:
    """
    Infer likely department codes from a user query.
    
    Args:
        query: User's natural language query
    
    Returns:
        List of department codes that match (e.g., ["6", "1"])
    """
    query_lower = query.lower()
    matching_codes = []
    
    for code, dept in DEPARTMENT_CODES.items():
        # Check if any keywords match
        for keyword in dept["keywords"]:
            if keyword in query_lower:
                if code not in matching_codes:
                    matching_codes.append(code)
                break
    
    return matching_codes


def get_all_departments() -> List[Dict[str, str]]:
    """
    Get list of all departments for UI display.
    
    Returns:
        List of department info dicts
    """
    return list(DEPARTMENT_CODES.values())


def filter_projects_by_department(
    project_ids: List[str], 
    department_codes: List[str]
) -> List[str]:
    """
    Filter a list of project IDs to only those in specified departments.
    
    Args:
        project_ids: List of file IDs to filter
        department_codes: List of department codes to include
    
    Returns:
        Filtered list of project IDs
    """
    return [
        pid for pid in project_ids 
        if pid and len(pid) > 0 and pid[0] in department_codes
    ]


def extract_file_id_from_folder(folder_name: str) -> Optional[str]:
    """
    Extract file ID from a folder name (same as ProjectMapper but standalone).
    
    Args:
        folder_name: Folder name like "4-Las Vegas Transfer Station Expansion (4229854)"
    
    Returns:
        File ID like "4229854" or None
    """
    # Pattern 1: ID in parentheses at end
    match = re.search(r'\((\d{6,7})\)$', folder_name.strip())
    if match:
        return match.group(1)
    
    # Pattern 2: Just the ID
    if re.match(r'^\d{6,7}$', folder_name.strip()):
        return folder_name.strip()
    
    return None


def get_folder_department(folder_name: str) -> Optional[Dict[str, str]]:
    """
    Get department info from a folder name.
    
    Args:
        folder_name: Folder name from raw_docs
    
    Returns:
        Department info dict or None
    """
    file_id = extract_file_id_from_folder(folder_name)
    if file_id:
        return get_department_from_file_id(file_id)
    return None
