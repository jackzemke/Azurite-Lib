"""
Lightweight metadata scraper for projects.

Walks a parent directory structure, identifies projects by pattern (NAME (ID)),
and extracts key metadata from files without analyzing file contents:
- Project start/end dates
- Client name
- Project scope/type
- Team/department

Stores results in a single JSON index file for fast lookup by LLM/Ajera integration.

Strategy:
- File-based index (JSON) - no database overhead
- Priority file search: Proposals first, then Project Mgmt docs
- Hybrid approach: Look for known file patterns, fall back to content search if needed
- Incremental updates: Track directory modification times to avoid re-scanning
"""

import json
import re
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)

# Department mapping based on leading digit in folder name
DEPARTMENT_MAP = {
    "1": "Environmental",
    "2": "Survey",
    "3": "Other",
    "4": "Other",
    "5": "Oil and Gas",
    "6": "Water",
    "7": "Transportation",
    "8": "Other",
    "9": "General Civil",
}


@dataclass
class ProjectMetadata:
    """Metadata for a single project."""
    project_id: Optional[str] = None
    project_name: str = ""
    full_path: str = ""
    department: Optional[str] = None  # Extracted from leading number (e.g., "Environmental", "Survey")

    # Critical metadata (required if available)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    client: Optional[str] = None
    scope_type: Optional[str] = None  # e.g., "Drainage Projects", "HVAC Design"

    # Support metadata
    team: Optional[str] = None
    location: Optional[str] = None

    # Metadata about metadata
    extraction_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: float = 1.0  # 0.0-1.0, lower if extracted from limited sources
    sources_used: List[str] = field(default_factory=list)  # Which files provided data

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values to keep JSON lean."""
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None or k in ["project_id", "start_date", "end_date", "client", "scope_type", "department"]}


class ProjectMetadataScraper:
    """Scrapes project metadata from directory tree and builds JSON index."""

    def __init__(self, parent_dir: str, index_output_path: str):
        """
        Initialize scraper.

        Args:
            parent_dir: Parent directory containing projects (e.g., "data/raw_docs")
            index_output_path: Where to save the JSON index file
        """
        self.parent_dir = Path(parent_dir)
        self.index_output_path = Path(index_output_path)
        self.projects: Dict[str, ProjectMetadata] = {}
        self.errors: List[str] = []

    def scrape(self) -> Dict[str, Any]:
        """
        Scrape parent directory for projects and extract metadata.

        Returns:
            Dict with results: status, projects_found, metadata_entries,
                              extraction_duration, errors
        """
        if not self.parent_dir.exists():
            return {"status": "error", "message": f"Parent dir not found: {self.parent_dir}"}

        start_time = datetime.now(timezone.utc)

        try:
            # Walk directory tree looking for projects
            self._walk_directory(self.parent_dir)

            # Save index
            self._save_index()

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()

            return {
                "status": "completed",
                "projects_found": len(self.projects),
                "metadata_entries": len([p for p in self.projects.values() if p.client or p.start_date]),
                "extraction_duration_seconds": round(duration, 2),
                "index_saved_to": str(self.index_output_path),
                "errors": self.errors,
            }

        except Exception as e:
            logger.error(f"Scrape failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "projects_found": len(self.projects),
                "errors": self.errors,
            }

    # -----------------------------------------------------------------------
    # Private: Directory Walking
    # -----------------------------------------------------------------------

    def _walk_directory(self, current_dir: Path, depth: int = 0):
        """
        Recursively walk directory tree looking for projects.

        A project is identified by:
        1. Folder name matching pattern "NAME (ID)" where ID is numeric
        2. If folder doesn't have ID, recurse into it
        """
        try:
            for entry in sorted(current_dir.iterdir()):
                if not entry.is_dir() or entry.name.startswith('.'):
                    continue

                project_id = self._extract_id(entry.name)

                if project_id:
                    # This is a project folder
                    self._index_project(entry, project_id)
                else:
                    # Not a project folder - recurse
                    if depth < 3:  # Prevent infinite recursion
                        self._walk_directory(entry, depth + 1)

        except PermissionError:
            msg = f"Permission denied reading: {current_dir}"
            logger.warning(msg)
            self.errors.append(msg)
        except Exception as e:
            msg = f"Error walking {current_dir}: {e}"
            logger.error(msg)
            self.errors.append(msg)

    def _index_project(self, project_dir: Path, project_id: str):
        """Index a single project folder and extract metadata."""
        project_name = self._clean_project_name(project_dir.name, project_id)
        department = self._extract_department(project_dir.name)

        metadata = ProjectMetadata(
            project_id=project_id,
            project_name=project_name,
            full_path=str(project_dir),
            department=department,
        )

        # Extract metadata from files in this project
        self._extract_metadata(project_dir, metadata)

        # Store in index
        self.projects[project_id] = metadata
        logger.debug(f"Indexed: {project_name} ({project_id}) - {department}")

    # -----------------------------------------------------------------------
    # Private: Metadata Extraction
    # -----------------------------------------------------------------------

    def _extract_metadata(self, project_dir: Path, metadata: ProjectMetadata):
        """
        Extract metadata from project directory.

        Priority:
        1. Look for known filename patterns in specific folders
        2. Fall back to searching file contents if needed
        """
        # Priority 1: Proposal documents (General/Proposals)
        proposals_dir = project_dir / "General" / "Proposals"
        if proposals_dir.exists():
            self._extract_from_proposals(proposals_dir, metadata)

        # Priority 2: Project Management docs (Project Mgmt/Contract)
        contract_dir = project_dir / "Project Mgmt" / "Contract"
        if contract_dir.exists():
            self._extract_from_contracts(contract_dir, metadata)

        # Priority 3: Financials (for dates)
        financials_dir = project_dir / "Project Mgmt" / "Financials"
        if financials_dir.exists():
            self._extract_from_financials(financials_dir, metadata)

        # Clean up extracted metadata
        self._cleanup_metadata(metadata)

    def _extract_from_proposals(self, proposals_dir: Path, metadata: ProjectMetadata):
        """Extract metadata from proposal files."""
        try:
            # Look for common proposal files and extract text
            for file_pattern in ["proposal*.pdf", "proposal*.docx", "scope*.pdf", "scope*.docx"]:
                for doc_file in proposals_dir.glob(file_pattern):
                    # For now, use filename patterns to infer metadata
                    # This is the lightweight approach - we'll add content parsing if needed
                    logger.debug(f"Found proposal: {doc_file.name}")

                    # Try to extract text and look for keywords
                    if doc_file.suffix.lower() in ['.pdf', '.docx']:
                        try:
                            # Attempt lightweight text extraction
                            extracted = self._extract_text_from_file(doc_file)
                            self._parse_metadata_from_text(extracted, metadata)
                            metadata.sources_used.append(f"proposal:{doc_file.name}")
                        except Exception as e:
                            logger.debug(f"Could not extract from {doc_file.name}: {e}")

        except Exception as e:
            logger.debug(f"Error extracting from proposals: {e}")

    def _extract_from_contracts(self, contract_dir: Path, metadata: ProjectMetadata):
        """Extract metadata from contract files."""
        try:
            for contract_file in contract_dir.glob("*"):
                if contract_file.is_file() and contract_file.suffix.lower() in ['.pdf', '.docx', '.doc']:
                    logger.debug(f"Found contract: {contract_file.name}")

                    try:
                        extracted = self._extract_text_from_file(contract_file)
                        self._parse_metadata_from_text(extracted, metadata)
                        metadata.sources_used.append(f"contract:{contract_file.name}")
                    except Exception as e:
                        logger.debug(f"Could not extract from {contract_file.name}: {e}")

        except Exception as e:
            logger.debug(f"Error extracting from contracts: {e}")

    def _extract_from_financials(self, financials_dir: Path, metadata: ProjectMetadata):
        """Extract metadata from financial files (especially dates)."""
        try:
            for fin_file in financials_dir.glob("*"):
                if fin_file.is_file():
                    logger.debug(f"Found financial doc: {fin_file.name}")

                    try:
                        # For Excel/CSV, we'd normally parse dates
                        # For now, look at file modification times as proxy for project dates
                        stat_info = fin_file.stat()
                        if not metadata.start_date or not metadata.end_date:
                            # Use file dates as rough proxies
                            # (This is lightweight - actual dates should come from document content)
                            mtime = datetime.fromtimestamp(stat_info.st_mtime).isoformat()
                            if not metadata.end_date:
                                metadata.end_date = mtime
                            metadata.sources_used.append(f"financial:{fin_file.name}")
                    except Exception as e:
                        logger.debug(f"Could not extract from {fin_file.name}: {e}")

        except Exception as e:
            logger.debug(f"Error extracting from financials: {e}")

    # -----------------------------------------------------------------------
    # Private: Metadata Cleanup
    # -----------------------------------------------------------------------

    def _cleanup_metadata(self, metadata: ProjectMetadata):
        """Clean up extracted metadata for consistency and readability."""
        # Clean up client name: remove line breaks and extra whitespace
        if metadata.client:
            metadata.client = ' '.join(metadata.client.split())
            # Remove "the" from the start if it's an institutional name
            if metadata.client.startswith('the '):
                metadata.client = metadata.client[4:]

        # Dates are already clean from parsing, but could add validation here

        # Clean up scope type: ensure consistent casing
        if metadata.scope_type:
            metadata.scope_type = metadata.scope_type.strip()

    # -----------------------------------------------------------------------
    # Private: Text Extraction & Parsing
    # -----------------------------------------------------------------------

    def _extract_text_from_file(self, file_path: Path) -> str:
        """
        Extract text from file (PDF, DOCX).

        Returns concatenated text from all pages/sections.
        Returns empty string if extraction fails or dependencies missing.

        Text extraction requires pdfplumber (for PDF) and python-docx packages.
        Gracefully falls back to empty string if not available.
        """
        try:
            if file_path.suffix.lower() == '.pdf':
                try:
                    from .extractors.pdf_extractor import PDFExtractor
                    extractor = PDFExtractor(min_text_length=50)
                    result = extractor.extract(file_path)
                    if result and result.get('pages'):
                        # Concatenate all page text (limit to first 5 pages to keep it fast)
                        text = '\n'.join(page.get('text', '') for page in result['pages'][:5])
                        return text
                except ImportError:
                    logger.debug("pdfplumber not installed - skipping PDF text extraction")
                    return ""
            elif file_path.suffix.lower() in ['.docx']:
                try:
                    from .extractors.docx_extractor import DOCXExtractor
                    extractor = DOCXExtractor()
                    result = extractor.extract(file_path)
                    if result and result.get('text'):
                        return result['text'][:5000]  # Limit text to keep it manageable
                except ImportError:
                    logger.debug("python-docx not installed - skipping DOCX text extraction")
                    return ""
        except Exception as e:
            logger.debug(f"Text extraction failed for {file_path}: {e}")

        return ""

    def _parse_metadata_from_text(self, text: str, metadata: ProjectMetadata):
        """Parse metadata from extracted document text."""
        if not text or len(text) < 10:
            return

        text_lower = text.lower()

        # Scope/type keyword matching (comprehensive)
        scope_keywords = {
            "drainage": "Drainage Projects",
            "stormwater": "Stormwater",
            "hvac": "HVAC Design",
            "environmental": "Environmental",
            "phase i esa": "Phase I ESA",
            "environmental site": "Environmental Site Assessment",
            "bridge": "Bridge Design",
            "highway": "Highway",
            "survey": "Survey",
            "master plan": "Master Planning",
            "water system": "Water System",
            "wastewater": "Wastewater",
            "treatment plant": "Treatment Plant Design",
            "site investigation": "Site Investigation",
            "remedial": "Remedial Design",
            "engineering": "Engineering Services",
            "feasibility": "Feasibility Study",
        }

        for keyword, scope_type in scope_keywords.items():
            if keyword in text_lower and not metadata.scope_type:
                metadata.scope_type = scope_type
                break

        # Date pattern matching (improved - look for dates near key terms)
        # Patterns: YYYY-MM-DD, MM/DD/YYYY, DateWord DD, YYYY
        date_patterns = [
            # Most reliable: Month DD, YYYY
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}',
            # ISO format: YYYY-MM-DD
            r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b',
            # US format: MM/DD/YYYY or M/D/YYYY
            r'\b\d{1,2}/\d{1,2}/\d{4}\b',
        ]

        all_dates = []
        for pattern in date_patterns:
            dates = re.findall(pattern, text, re.IGNORECASE)
            all_dates.extend(dates)

        if all_dates:
            # Deduplicate and clean
            unique_dates = list(dict.fromkeys(all_dates))  # Remove duplicates, preserve order
            if unique_dates:
                if not metadata.start_date:
                    metadata.start_date = unique_dates[0]
                if not metadata.end_date and len(unique_dates) > 1:
                    metadata.end_date = unique_dates[-1]

        # Client extraction (improved)
        # Look for common client indicators - now smarter about org names
        client_patterns = [
            # Organization name at start of line with common org type
            r'^([A-Z][A-Za-z\s]+(?:Department|Agency|Authority|Inc|LLC|Corp|Company|District|Bureau))\b',
            # "client:" or "for:" patterns
            r'(?:client|for):?\s+([A-Z][a-z][A-Za-z\s]+?)(?:\n|$)',
            # Prepared for / owner patterns
            r'(?:prepared for|project owner|owner):\s+([A-Za-z][A-Za-z\s]+?)(?:\n|\(|$)',
        ]

        for pattern in client_patterns:
            matches = re.findall(pattern, text, re.MULTILINE | re.IGNORECASE)
            if matches:
                for match in matches:
                    potential_client = match.strip()[:80]
                    # Reasonable length and not garbage text
                    if (len(potential_client) > 3 and
                        len(potential_client) < 80 and
                        not re.match(r'^(page|section|see|the|standard|form)', potential_client, re.IGNORECASE)):
                        metadata.client = potential_client
                        break
            if metadata.client:
                break

        # Fallback: look for capitalized multi-word phrases that might be entity names
        if not metadata.client:
            # More specific: look for "Word Word Inc/LLC/etc" patterns
            capitals = re.findall(
                r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\s+(?:Inc|LLC|Ltd|Corp|Company|Agency|Department|District|Authority|Commission|Bureau|Board)\b',
                text
            )
            if capitals:
                # Pick the longest one (most likely to have full name)
                metadata.client = sorted(capitals, key=len, reverse=True)[0][:80]

    # -----------------------------------------------------------------------
    # Private: ID & Name Handling
    # -----------------------------------------------------------------------

    def _extract_id(self, name: str) -> Optional[str]:
        """
        Extract numeric ID from folder name.

        Patterns:
            - "Name (1430152)" -> "1430152"
            - "1-Name (1430152)" -> "1430152"
            - "4-Las Vegas Transfer Station (4229854)" -> "4229854"
        """
        # Pattern: Numeric ID in parentheses
        match = re.search(r'\((\d{5,8})\)', name)
        if match:
            return match.group(1)

        # Pattern: Alphanumeric ID in parentheses
        match = re.search(r'\((\d+[A-Za-z]\d+)\)', name)
        if match:
            return match.group(1)

        return None

    def _extract_department(self, folder_name: str) -> Optional[str]:
        """
        Extract department from leading digit in folder name.

        Examples:
            '1-NMED Acomita...' -> 'Environmental'
            '2-AECOM Las Vegas...' -> 'Survey'
            '6-Rio Embudo...' -> 'Water'
            'Acomita Day School' -> None (no leading digit)

        Returns:
            Department name or None if not found.
        """
        # Look for leading digit(s) followed by dash or space
        match = re.match(r'^(\d+)[-\s]', folder_name)
        if match:
            dept_num = match.group(1)[0]  # Take first digit only
            return DEPARTMENT_MAP.get(dept_num, "Other")
        return None

    def _clean_project_name(self, folder_name: str, project_id: Optional[str] = None) -> str:
        """
        Strip ID and priority number from folder name.

        Examples:
            '1-Las Vegas Transfer (1430152)' -> 'Las Vegas Transfer'
            '4-El Rancho Shell (3424143)' -> 'El Rancho Shell'
        """
        name = folder_name

        # Remove priority prefix (e.g., "1-", "4-")
        name = re.sub(r'^\d+-', '', name)

        # Remove "(ID)" from end
        if project_id:
            name = re.sub(r'\s*\(' + re.escape(project_id) + r'\)\s*$', '', name)

        return name.strip() or folder_name

    # -----------------------------------------------------------------------
    # Private: Persistence
    # -----------------------------------------------------------------------

    def _save_index(self):
        """Save metadata index to JSON file."""
        try:
            # Ensure output directory exists
            self.index_output_path.parent.mkdir(parents=True, exist_ok=True)

            # Convert to dict format for JSON serialization
            index_data = {
                "metadata": {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "parent_directory": str(self.parent_dir),
                    "total_projects": len(self.projects),
                    "projects_with_metadata": len([p for p in self.projects.values() if p.client or p.start_date]),
                },
                "projects": {
                    pid: project.to_dict()
                    for pid, project in self.projects.items()
                }
            }

            # Write JSON
            with open(self.index_output_path, 'w') as f:
                json.dump(index_data, f, indent=2)

            logger.info(f"Index saved: {self.index_output_path} ({len(self.projects)} projects)")

        except Exception as e:
            msg = f"Failed to save index: {e}"
            logger.error(msg)
            self.errors.append(msg)
            raise


def create_project_index(parent_dir: str, output_path: str = None) -> Dict[str, Any]:
    """
    Convenience function to create a project metadata index.

    Args:
        parent_dir: Parent directory containing projects
        output_path: Optional output path (defaults to data/metadata_index.json)

    Returns:
        Scrape result dict with status and statistics
    """
    if output_path is None:
        output_path = "data/metadata_index.json"

    scraper = ProjectMetadataScraper(parent_dir, output_path)
    return scraper.scrape()
