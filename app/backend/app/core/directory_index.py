"""
SQLite-backed directory tree index for project file location and duplicate detection.

Scans configured network drive mount points and indexes all project directories
into a local SQLite database with FTS5 full-text search. Enables fast lookup of
project file locations across drives and detection of duplicate project directories.

Architecture:
- SQLite database with drives, directories, and scan_metadata tables
- FTS5 virtual table for fast text search of project names and IDs
- Full rebuild on each scan (not incremental) — simpler, 5K-20K dirs scans in seconds
- All queries hit local SQLite — no live network access at query time
"""

import re
import sqlite3
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


class DirectoryIndex:
    """
    SQLite-backed directory tree cache for network drive project locations.

    Provides:
    - scan_drives(): Walk configured mount points and index directories
    - search_project_location(): Find where a project is stored
    - find_duplicates(): Detect projects on multiple drives
    """

    def __init__(
        self,
        db_path: str,
        drives: Optional[List[Dict]] = None,
    ):
        """
        Initialize directory index.

        Args:
            db_path: Path to SQLite database file
                     (e.g., "data/index/directory_index.db")
            drives: List of drive config dicts:
                    [{"name": "S Drive", "mount_path": "/mnt/s_drive",
                      "drive_letter": "S", "has_department_level": True}, ...]
        """
        self.db_path = db_path
        self.drives = drives or []
        self._initialized = False
        self._conn: Optional[sqlite3.Connection] = None

    def initialize(self) -> bool:
        """
        Initialize the index: create DB schema and register drives.

        Returns:
            True if initialization succeeded and drives are configured
        """
        try:
            # Ensure parent directory exists
            db_dir = Path(self.db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)

            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")

            self._create_schema()
            self._register_drives()

            self._initialized = True

            if self.drives:
                logger.info(f"DirectoryIndex initialized with {len(self.drives)} drives (db={self.db_path})")
                return True
            else:
                logger.info("DirectoryIndex initialized in stub mode (no drives configured)")
                return False

        except Exception as e:
            logger.error(f"DirectoryIndex initialization failed: {e}")
            self._initialized = False
            return False

    def is_available(self) -> bool:
        """Check if the directory index is available and has scan data."""
        if not self._initialized:
            return False
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM scan_metadata WHERE status = 'completed'"
            ).fetchone()
            return row["cnt"] > 0
        except Exception:
            return False

    def scan_drives(self) -> Dict[str, Any]:
        """
        Full rebuild scan of all configured drives.

        Clears existing directory data and re-scans all mount points.
        Project IDs are extracted from folder names using regex patterns
        consistent with filesystem_scanner.py and project_mapper.py.

        Returns:
            Dict with scan results: status, directories_found,
            drives_scanned, duration_seconds, errors
        """
        if not self._initialized:
            return {"status": "error", "message": "DirectoryIndex not initialized"}

        if not self.drives:
            return {"status": "error", "message": "No drives configured"}

        start_time = time.time()
        errors = []
        total_dirs = 0

        # Create scan metadata entry
        scan_id = self._start_scan()

        try:
            # Clear existing directory data for full rebuild
            self._conn.execute("DELETE FROM directories")
            self._conn.commit()

            # Get drive IDs from database
            drive_rows = self._conn.execute("SELECT * FROM drives").fetchall()
            drive_map = {row["mount_path"]: dict(row) for row in drive_rows}

            for drive_config in self.drives:
                mount_path = drive_config.get("mount_path", "")
                drive_name = drive_config.get("name", mount_path)

                db_drive = drive_map.get(mount_path)
                if not db_drive:
                    errors.append(f"Drive not registered in DB: {mount_path}")
                    continue

                drive_id = db_drive["id"]
                mount = Path(mount_path)

                if not mount.exists():
                    errors.append(f"Mount path does not exist: {mount_path}")
                    logger.warning(f"[SCAN] Skipping {drive_name}: mount path not found at {mount_path}")
                    continue

                has_dept = drive_config.get("has_department_level", False)

                try:
                    count = self._scan_single_drive(drive_id, mount, has_dept)
                    total_dirs += count
                    logger.info(f"[SCAN] {drive_name}: found {count} project directories")
                except Exception as e:
                    err_msg = f"Error scanning {drive_name}: {e}"
                    errors.append(err_msg)
                    logger.error(f"[SCAN] {err_msg}")

            # Rebuild FTS index
            self._rebuild_fts()
            self._conn.commit()

            duration = round(time.time() - start_time, 2)

            # Update scan metadata
            self._complete_scan(scan_id, total_dirs, len(self.drives))

            result = {
                "status": "completed",
                "directories_found": total_dirs,
                "drives_scanned": len(self.drives),
                "duration_seconds": duration,
                "errors": errors,
            }

            logger.info(f"[SCAN] Complete: {total_dirs} directories from {len(self.drives)} drives in {duration}s")
            return result

        except Exception as e:
            self._fail_scan(scan_id, str(e))
            logger.error(f"[SCAN] Failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "directories_found": total_dirs,
                "errors": errors,
            }

    def search_project_location(
        self,
        query: str,
        project_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search for project file locations across network drives.

        Uses a 3-tier search strategy:
        1. Exact project_id match (if query looks like an ID or project_id given)
        2. FTS5 full-text search on folder_name, project_name, department
        3. LIKE fallback for partial matches

        Args:
            query: Search query (project name, ID, or keywords)
            project_id: Optional specific project ID to search for
            limit: Maximum results to return

        Returns:
            List of dicts with location details including Windows paths
        """
        if not self._initialized or not self.is_available():
            return []

        results = []

        # Strategy 1: Exact project_id match
        search_id = project_id
        if not search_id:
            # Check if query itself looks like a project ID
            id_match = re.search(r'\b(\d{5,8})\b', query)
            if id_match:
                search_id = id_match.group(1)
            # Also check for alphanumeric IDs like 1A29514
            alnum_match = re.search(r'\b(\d+[A-Za-z]\d+)\b', query)
            if alnum_match:
                search_id = alnum_match.group(1)

        if search_id:
            results = self._search_by_id(search_id, limit)
            if results:
                return results

        # Strategy 2: FTS5 full-text search
        results = self._search_fts(query, limit)
        if results:
            return results

        # Strategy 3: LIKE fallback for partial matches
        results = self._search_like(query, limit)
        return results

    def find_duplicates(
        self,
        query: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Find duplicate project directories across drives.

        Args:
            query: Optional search query to narrow scope
            project_id: Optional specific project ID to check
            limit: Maximum duplicate groups to return

        Returns:
            List of dicts with duplicate info: project_id, project_name,
            locations list, match_reason
        """
        if not self._initialized or not self.is_available():
            return []

        if project_id:
            return self._find_duplicates_by_id(project_id, limit)

        if query:
            # Search first, then find duplicates among results
            search_id = None
            id_match = re.search(r'\b(\d{5,8})\b', query)
            if id_match:
                search_id = id_match.group(1)

            if search_id:
                return self._find_duplicates_by_id(search_id, limit)

            # FTS search for project, then check those IDs
            search_results = self._search_fts(query, limit * 2)
            if search_results:
                seen_ids = set()
                duplicates = []
                for r in search_results:
                    pid = r.get("project_id")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        dups = self._find_duplicates_by_id(pid, limit)
                        duplicates.extend(dups)
                return duplicates[:limit]

        # No filter: find all project_ids that appear on 2+ drives
        return self._find_all_duplicates(limit)

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        if not self._initialized:
            return {
                "initialized": False,
                "total_directories": 0,
                "total_drives": len(self.drives),
                "drives": [d.get("name", "?") for d in self.drives],
            }

        try:
            dir_count = self._conn.execute("SELECT COUNT(*) as cnt FROM directories").fetchone()["cnt"]
            drive_count = self._conn.execute("SELECT COUNT(*) as cnt FROM drives").fetchone()["cnt"]
            id_count = self._conn.execute(
                "SELECT COUNT(DISTINCT project_id) as cnt FROM directories WHERE project_id IS NOT NULL"
            ).fetchone()["cnt"]

            return {
                "initialized": True,
                "available": self.is_available(),
                "total_directories": dir_count,
                "total_drives": drive_count,
                "unique_project_ids": id_count,
                "drives": [d.get("name", "?") for d in self.drives],
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"initialized": True, "error": str(e)}

    def get_last_scan(self) -> Optional[Dict]:
        """Return metadata about the most recent scan."""
        if not self._initialized:
            return None

        try:
            row = self._conn.execute(
                "SELECT * FROM scan_metadata ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                return dict(row)
            return None
        except Exception:
            return None

    # -----------------------------------------------------------------------
    # Private: Schema & Drive Registration
    # -----------------------------------------------------------------------

    def _create_schema(self):
        """Create database tables if they don't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS drives (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                mount_path TEXT NOT NULL UNIQUE,
                drive_letter TEXT NOT NULL,
                has_department_level BOOLEAN DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS directories (
                id INTEGER PRIMARY KEY,
                drive_id INTEGER NOT NULL REFERENCES drives(id),
                path TEXT NOT NULL,
                folder_name TEXT NOT NULL,
                department TEXT,
                project_id TEXT,
                project_name TEXT,
                depth INTEGER NOT NULL,
                file_count INTEGER DEFAULT 0,
                last_modified TEXT,
                UNIQUE(drive_id, path)
            );

            CREATE TABLE IF NOT EXISTS scan_metadata (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                total_directories INTEGER DEFAULT 0,
                total_drives INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running',
                error_message TEXT
            );
        """)

        # Create FTS5 table (separate to handle "already exists" gracefully)
        try:
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS directories_fts USING fts5(
                    folder_name,
                    project_name,
                    project_id,
                    department,
                    content=directories,
                    content_rowid=id
                )
            """)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                raise

        self._conn.commit()

    def _register_drives(self):
        """Register configured drives in the database."""
        for drive in self.drives:
            try:
                self._conn.execute(
                    """INSERT OR REPLACE INTO drives (name, mount_path, drive_letter, has_department_level)
                       VALUES (?, ?, ?, ?)""",
                    (
                        drive.get("name", ""),
                        drive.get("mount_path", ""),
                        drive.get("drive_letter", ""),
                        drive.get("has_department_level", False),
                    ),
                )
            except Exception as e:
                logger.warning(f"Error registering drive {drive.get('name')}: {e}")

        self._conn.commit()

    # -----------------------------------------------------------------------
    # Private: Scanning
    # -----------------------------------------------------------------------

    def _scan_single_drive(self, drive_id: int, mount: Path, has_department_level: bool) -> int:
        """
        Scan a single drive mount point for project directories.

        For 3-level drives (has_department_level=True):
            mount_path/Department/ProjectFolder

        For 2-level drives (has_department_level=False):
            mount_path/ProjectFolder

        Returns number of project directories found.
        """
        count = 0

        if has_department_level:
            # 3-level: iterate departments, then projects
            for dept_entry in sorted(mount.iterdir()):
                if not dept_entry.is_dir() or dept_entry.name.startswith('.'):
                    continue

                department = dept_entry.name

                for proj_entry in sorted(dept_entry.iterdir()):
                    if not proj_entry.is_dir() or proj_entry.name.startswith('.'):
                        continue

                    self._index_project_dir(
                        drive_id=drive_id,
                        dir_path=proj_entry,
                        department=department,
                        depth=2,
                    )
                    count += 1
        else:
            # 2-level: iterate projects directly
            for proj_entry in sorted(mount.iterdir()):
                if not proj_entry.is_dir() or proj_entry.name.startswith('.'):
                    continue

                self._index_project_dir(
                    drive_id=drive_id,
                    dir_path=proj_entry,
                    department=None,
                    depth=1,
                )
                count += 1

        return count

    def _index_project_dir(
        self,
        drive_id: int,
        dir_path: Path,
        department: Optional[str],
        depth: int,
    ):
        """Index a single project directory."""
        folder_name = dir_path.name
        project_id = self._extract_id(folder_name)
        project_name = self._clean_project_name(folder_name, project_id)

        # Count immediate files (non-recursive for speed)
        file_count = 0
        latest_mtime = 0
        try:
            for item in dir_path.iterdir():
                if item.is_file():
                    file_count += 1
                    mtime = item.stat().st_mtime
                    if mtime > latest_mtime:
                        latest_mtime = mtime
        except PermissionError:
            logger.debug(f"Permission denied reading: {dir_path}")

        last_modified = (
            datetime.fromtimestamp(latest_mtime).isoformat()
            if latest_mtime > 0
            else None
        )

        self._conn.execute(
            """INSERT OR REPLACE INTO directories
               (drive_id, path, folder_name, department, project_id, project_name,
                depth, file_count, last_modified)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                drive_id,
                str(dir_path),
                folder_name,
                department,
                project_id,
                project_name,
                depth,
                file_count,
                last_modified,
            ),
        )

    # -----------------------------------------------------------------------
    # Private: Search
    # -----------------------------------------------------------------------

    def _search_by_id(self, project_id: str, limit: int) -> List[Dict[str, Any]]:
        """Search by exact project_id match."""
        rows = self._conn.execute(
            """SELECT d.*, dr.name as drive_name, dr.drive_letter, dr.mount_path
               FROM directories d
               JOIN drives dr ON d.drive_id = dr.id
               WHERE d.project_id = ?
               LIMIT ?""",
            (project_id, limit),
        ).fetchall()
        return [self._row_to_result(row) for row in rows]

    def _search_fts(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search using FTS5 full-text search."""
        # Clean query for FTS5 (remove special chars that break FTS syntax)
        fts_query = re.sub(r'[^\w\s]', ' ', query).strip()
        if not fts_query:
            return []

        # Convert words to FTS5 prefix search tokens
        tokens = fts_query.split()
        if not tokens:
            return []

        # Use prefix matching: each word gets a * suffix for partial matching
        fts_expr = " ".join(f'"{t}"*' for t in tokens)

        try:
            rows = self._conn.execute(
                """SELECT d.*, dr.name as drive_name, dr.drive_letter, dr.mount_path
                   FROM directories_fts fts
                   JOIN directories d ON fts.rowid = d.id
                   JOIN drives dr ON d.drive_id = dr.id
                   WHERE directories_fts MATCH ?
                   LIMIT ?""",
                (fts_expr, limit),
            ).fetchall()
            return [self._row_to_result(row) for row in rows]
        except sqlite3.OperationalError as e:
            logger.debug(f"FTS query failed (falling back to LIKE): {e}")
            return []

    def _search_like(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Fallback search using LIKE for partial matches."""
        pattern = f"%{query}%"
        rows = self._conn.execute(
            """SELECT d.*, dr.name as drive_name, dr.drive_letter, dr.mount_path
               FROM directories d
               JOIN drives dr ON d.drive_id = dr.id
               WHERE d.folder_name LIKE ? COLLATE NOCASE
                  OR d.project_name LIKE ? COLLATE NOCASE
                  OR d.project_id LIKE ? COLLATE NOCASE
                  OR d.department LIKE ? COLLATE NOCASE
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, limit),
        ).fetchall()
        return [self._row_to_result(row) for row in rows]

    def _row_to_result(self, row) -> Dict[str, Any]:
        """Convert a database row to a result dict."""
        row_dict = dict(row)
        mount_path = row_dict.get("mount_path", "")
        drive_letter = row_dict.get("drive_letter", "")
        dir_path = row_dict.get("path", "")

        return {
            "path": dir_path,
            "windows_path": self._to_windows_path(dir_path, mount_path, drive_letter),
            "drive_letter": drive_letter,
            "drive_name": row_dict.get("drive_name", ""),
            "department": row_dict.get("department"),
            "project_name": row_dict.get("project_name", ""),
            "project_id": row_dict.get("project_id"),
            "folder_name": row_dict.get("folder_name", ""),
            "file_count": row_dict.get("file_count", 0),
            "last_modified": row_dict.get("last_modified"),
        }

    # -----------------------------------------------------------------------
    # Private: Duplicate Detection
    # -----------------------------------------------------------------------

    def _find_duplicates_by_id(self, project_id: str, limit: int) -> List[Dict[str, Any]]:
        """Find all locations of a specific project_id and return as duplicate group."""
        rows = self._conn.execute(
            """SELECT d.*, dr.name as drive_name, dr.drive_letter, dr.mount_path
               FROM directories d
               JOIN drives dr ON d.drive_id = dr.id
               WHERE d.project_id = ?
               ORDER BY dr.drive_letter""",
            (project_id,),
        ).fetchall()

        if len(rows) < 2:
            return []

        # Group into a single duplicate entry
        locations = []
        project_name = ""
        for row in rows:
            row_dict = dict(row)
            mount_path = row_dict["mount_path"]
            drive_letter = row_dict["drive_letter"]
            dir_path = row_dict["path"]

            if not project_name:
                project_name = row_dict.get("project_name", "")

            locations.append({
                "drive_letter": drive_letter,
                "drive_name": row_dict.get("drive_name", ""),
                "path": dir_path,
                "windows_path": self._to_windows_path(dir_path, mount_path, drive_letter),
                "department": row_dict.get("department"),
                "file_count": row_dict.get("file_count", 0),
            })

        return [{
            "project_id": project_id,
            "project_name": project_name,
            "locations": locations,
            "match_reason": "same_project_id",
        }]

    def _find_all_duplicates(self, limit: int) -> List[Dict[str, Any]]:
        """Find all project_ids that appear on 2+ drives."""
        rows = self._conn.execute(
            """SELECT project_id, COUNT(DISTINCT drive_id) as drive_count
               FROM directories
               WHERE project_id IS NOT NULL
               GROUP BY project_id
               HAVING drive_count >= 2
               LIMIT ?""",
            (limit,),
        ).fetchall()

        results = []
        for row in rows:
            pid = row["project_id"]
            dups = self._find_duplicates_by_id(pid, 10)
            results.extend(dups)

        return results[:limit]

    # -----------------------------------------------------------------------
    # Private: Scan Metadata
    # -----------------------------------------------------------------------

    def _start_scan(self) -> int:
        """Create a scan metadata entry and return its ID."""
        cursor = self._conn.execute(
            "INSERT INTO scan_metadata (started_at, status) VALUES (?, 'running')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self._conn.commit()
        return cursor.lastrowid

    def _complete_scan(self, scan_id: int, total_dirs: int, total_drives: int):
        """Mark a scan as completed."""
        self._conn.execute(
            """UPDATE scan_metadata
               SET completed_at = ?, total_directories = ?, total_drives = ?, status = 'completed'
               WHERE id = ?""",
            (datetime.now(timezone.utc).isoformat(), total_dirs, total_drives, scan_id),
        )
        self._conn.commit()

    def _fail_scan(self, scan_id: int, error_message: str):
        """Mark a scan as failed."""
        self._conn.execute(
            """UPDATE scan_metadata
               SET completed_at = ?, status = 'failed', error_message = ?
               WHERE id = ?""",
            (datetime.now(timezone.utc).isoformat(), error_message, scan_id),
        )
        self._conn.commit()

    # -----------------------------------------------------------------------
    # Private: Helpers
    # -----------------------------------------------------------------------

    def _extract_id(self, name: str) -> Optional[str]:
        """
        Extract numeric/alphanumeric ID from a folder name.

        Uses the same patterns as filesystem_scanner.py and project_mapper.py:
            - "Name (1430152)" -> "1430152"
            - "1430152-Name" -> "1430152"
            - "1430152" -> "1430152"
            - "(1A29514)" -> "1A29514"
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

    def _clean_project_name(self, folder_name: str, project_id: Optional[str] = None) -> str:
        """
        Strip ID from folder name to get clean project name.

        Examples:
            'Las Vegas Transfer Station (1430152)' -> 'Las Vegas Transfer Station'
            '1430152-Project Name' -> 'Project Name'
            '1430152' -> '1430152'
        """
        name = folder_name

        if project_id:
            # Remove "(ID)" from end
            name = re.sub(r'\s*\(' + re.escape(project_id) + r'\)\s*$', '', name)
            # Remove "ID-" from start
            name = re.sub(r'^' + re.escape(project_id) + r'[-_\s]+', '', name)

        return name.strip() or folder_name

    def _to_windows_path(self, linux_path: str, mount_path: str, drive_letter: str) -> str:
        """
        Convert Linux mount path to Windows drive letter path.

        Example:
            linux_path:  /mnt/s_drive/Environmental/Project
            mount_path:  /mnt/s_drive
            drive_letter: S
            result:      S:\\Environmental\\Project
        """
        try:
            relative = Path(linux_path).relative_to(Path(mount_path))
            # Convert forward slashes to backslashes
            windows_rel = str(relative).replace("/", "\\")
            if windows_rel == ".":
                return f"{drive_letter}:\\"
            return f"{drive_letter}:\\{windows_rel}"
        except ValueError:
            # Fallback if path isn't relative to mount
            return f"{drive_letter}:\\{Path(linux_path).name}"

    def _rebuild_fts(self):
        """Rebuild FTS5 index from directories table."""
        try:
            # Delete all FTS content
            self._conn.execute("DELETE FROM directories_fts")

            # Re-insert all directory data into FTS
            self._conn.execute("""
                INSERT INTO directories_fts(rowid, folder_name, project_name, project_id, department)
                SELECT id, folder_name, project_name, project_id, department
                FROM directories
            """)

            self._conn.commit()
            logger.debug("Rebuilt FTS5 index")
        except Exception as e:
            logger.warning(f"Error rebuilding FTS index: {e}")
