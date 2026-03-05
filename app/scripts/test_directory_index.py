"""
Tests for DirectoryIndex — SQLite-backed directory tree cache.

Tests use the real mock drive data created by create_mock_drives.py,
plus some tests using temporary directories for isolation.

Run: python -m pytest app/scripts/test_directory_index.py -v
"""

import sys
import os
import tempfile
import shutil
from pathlib import Path

import pytest

# Add backend to path so imports work standalone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.directory_index import DirectoryIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_directory_index.db")


@pytest.fixture
def mock_drives(tmp_path):
    """Create minimal mock drive structures for testing."""
    s_drive = tmp_path / "s_drive"
    p_drive = tmp_path / "p_drive"

    # S Drive: 3-level (Drive > Department > Project)
    (s_drive / "Environmental" / "Las Vegas Transfer Station (1430152)").mkdir(parents=True)
    (s_drive / "Environmental" / "NMED Acomita Day School (1A29514)").mkdir(parents=True)
    (s_drive / "Geotechnical" / "I-25 Bridge Replacement (1133234)").mkdir(parents=True)
    (s_drive / "Geotechnical" / "Rio Rancho Soil Study (1150001)").mkdir(parents=True)

    # Add some files to projects
    (s_drive / "Environmental" / "Las Vegas Transfer Station (1430152)" / "report.pdf").touch()
    (s_drive / "Environmental" / "Las Vegas Transfer Station (1430152)" / "site_photos.zip").touch()
    (s_drive / "Environmental" / "Las Vegas Transfer Station (1430152)" / "field_notes.docx").touch()
    (s_drive / "Geotechnical" / "I-25 Bridge Replacement (1133234)" / "specs.pdf").touch()

    # P Drive: 2-level (Drive > Project)
    (p_drive / "Las Vegas Transfer Station (1430152)").mkdir(parents=True)  # Duplicate
    (p_drive / "Albuquerque Airport Terminal B (1290045)").mkdir(parents=True)
    (p_drive / "Santa Fe Rail Trail Extension (1340067)").mkdir(parents=True)

    # Add files to P drive
    (p_drive / "Las Vegas Transfer Station (1430152)" / "report.pdf").touch()
    (p_drive / "Albuquerque Airport Terminal B (1290045)" / "report.pdf").touch()

    return {
        "s_drive": str(s_drive),
        "p_drive": str(p_drive),
    }


@pytest.fixture
def drives_config(mock_drives):
    """Return drive config list for mock drives."""
    return [
        {
            "name": "S Drive (Test)",
            "mount_path": mock_drives["s_drive"],
            "drive_letter": "S",
            "has_department_level": True,
        },
        {
            "name": "P Drive (Test)",
            "mount_path": mock_drives["p_drive"],
            "drive_letter": "P",
            "has_department_level": False,
        },
    ]


@pytest.fixture
def index(tmp_db, drives_config):
    """Create an initialized DirectoryIndex with mock data."""
    idx = DirectoryIndex(db_path=tmp_db, drives=drives_config)
    idx.initialize()
    return idx


@pytest.fixture
def scanned_index(index):
    """Create an initialized and scanned DirectoryIndex."""
    index.scan_drives()
    return index


# ---------------------------------------------------------------------------
# Initialization Tests
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_initialize_creates_db(self, tmp_db, drives_config):
        idx = DirectoryIndex(db_path=tmp_db, drives=drives_config)
        result = idx.initialize()
        assert result is True
        assert Path(tmp_db).exists()

    def test_initialize_no_drives(self, tmp_db):
        idx = DirectoryIndex(db_path=tmp_db, drives=[])
        result = idx.initialize()
        assert result is False

    def test_not_available_before_scan(self, index):
        assert index.is_available() is False

    def test_available_after_scan(self, scanned_index):
        assert scanned_index.is_available() is True


# ---------------------------------------------------------------------------
# Scanning Tests
# ---------------------------------------------------------------------------

class TestScanning:
    def test_scan_returns_completed(self, index):
        result = index.scan_drives()
        assert result["status"] == "completed"

    def test_scan_finds_all_directories(self, index):
        result = index.scan_drives()
        # S drive: 4 projects, P drive: 3 projects = 7 total
        assert result["directories_found"] == 7

    def test_scan_counts_drives(self, index):
        result = index.scan_drives()
        assert result["drives_scanned"] == 2

    def test_scan_reports_duration(self, index):
        result = index.scan_drives()
        assert "duration_seconds" in result
        assert result["duration_seconds"] >= 0

    def test_scan_missing_mount_path(self, tmp_db):
        drives = [{
            "name": "Missing Drive",
            "mount_path": "/nonexistent/path",
            "drive_letter": "X",
            "has_department_level": False,
        }]
        idx = DirectoryIndex(db_path=tmp_db, drives=drives)
        idx.initialize()
        result = idx.scan_drives()
        assert result["status"] == "completed"
        assert len(result["errors"]) > 0

    def test_rescan_rebuilds(self, index):
        """Second scan should replace, not append."""
        result1 = index.scan_drives()
        result2 = index.scan_drives()
        assert result1["directories_found"] == result2["directories_found"]


# ---------------------------------------------------------------------------
# ID Extraction Tests
# ---------------------------------------------------------------------------

class TestIDExtraction:
    def test_id_in_parentheses(self, index):
        assert index._extract_id("Las Vegas Transfer Station (1430152)") == "1430152"

    def test_alphanumeric_id(self, index):
        assert index._extract_id("NMED Acomita Day School (1A29514)") == "1A29514"

    def test_id_at_start_with_dash(self, index):
        assert index._extract_id("1430152-Las Vegas") == "1430152"

    def test_pure_numeric(self, index):
        assert index._extract_id("1430152") == "1430152"

    def test_no_id(self, index):
        assert index._extract_id("Some Random Folder") is None

    def test_short_number_ignored(self, index):
        """Numbers shorter than 5 digits should not be extracted."""
        assert index._extract_id("1234") is None


# ---------------------------------------------------------------------------
# Project Name Cleaning Tests
# ---------------------------------------------------------------------------

class TestCleanProjectName:
    def test_strip_id_parentheses(self, index):
        name = index._clean_project_name("Las Vegas Transfer Station (1430152)", "1430152")
        assert name == "Las Vegas Transfer Station"

    def test_strip_id_prefix(self, index):
        name = index._clean_project_name("1430152-Las Vegas Project", "1430152")
        assert name == "Las Vegas Project"

    def test_no_id_returns_original(self, index):
        name = index._clean_project_name("Some Folder", None)
        assert name == "Some Folder"


# ---------------------------------------------------------------------------
# Windows Path Conversion Tests
# ---------------------------------------------------------------------------

class TestWindowsPath:
    def test_basic_conversion(self, index):
        result = index._to_windows_path(
            "/mnt/s_drive/Environmental/Project",
            "/mnt/s_drive",
            "S",
        )
        assert result == "S:\\Environmental\\Project"

    def test_root_path(self, index):
        result = index._to_windows_path("/mnt/s_drive", "/mnt/s_drive", "S")
        assert result == "S:\\"

    def test_deep_path(self, index):
        result = index._to_windows_path(
            "/mnt/p_drive/Las Vegas Transfer Station (1430152)",
            "/mnt/p_drive",
            "P",
        )
        assert result == "P:\\Las Vegas Transfer Station (1430152)"


# ---------------------------------------------------------------------------
# Search Tests
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_by_project_id(self, scanned_index):
        results = scanned_index.search_project_location("1430152")
        assert len(results) >= 1
        assert any(r["project_id"] == "1430152" for r in results)

    def test_search_by_name_fts(self, scanned_index):
        results = scanned_index.search_project_location("Las Vegas")
        assert len(results) >= 1
        assert any("Las Vegas" in r.get("project_name", "") for r in results)

    def test_search_by_name_like_fallback(self, scanned_index):
        results = scanned_index.search_project_location("vegas")
        assert len(results) >= 1

    def test_search_returns_windows_path(self, scanned_index):
        results = scanned_index.search_project_location("1430152")
        assert len(results) >= 1
        for r in results:
            assert "\\" in r["windows_path"]
            assert r["drive_letter"] in ("S", "P")

    def test_search_returns_department(self, scanned_index):
        results = scanned_index.search_project_location("1430152")
        s_drive_results = [r for r in results if r["drive_letter"] == "S"]
        if s_drive_results:
            assert s_drive_results[0]["department"] == "Environmental"

    def test_search_returns_file_count(self, scanned_index):
        results = scanned_index.search_project_location("1430152")
        s_drive_results = [r for r in results if r["drive_letter"] == "S"]
        if s_drive_results:
            assert s_drive_results[0]["file_count"] == 3  # report.pdf, site_photos.zip, field_notes.docx

    def test_search_no_results(self, scanned_index):
        results = scanned_index.search_project_location("nonexistent project xyz")
        assert len(results) == 0

    def test_search_alphanumeric_id(self, scanned_index):
        results = scanned_index.search_project_location("1A29514")
        assert len(results) >= 1
        assert any(r["project_id"] == "1A29514" for r in results)

    def test_search_by_department(self, scanned_index):
        results = scanned_index.search_project_location("Geotechnical")
        assert len(results) >= 1
        assert all(r.get("department") == "Geotechnical" or "Geotechnical" in r.get("folder_name", "") for r in results)

    def test_search_with_explicit_project_id(self, scanned_index):
        results = scanned_index.search_project_location(
            query="anything",
            project_id="1430152",
        )
        assert len(results) >= 1
        assert all(r["project_id"] == "1430152" for r in results)

    def test_search_limit(self, scanned_index):
        results = scanned_index.search_project_location("", limit=2)
        assert len(results) <= 2


# ---------------------------------------------------------------------------
# Duplicate Detection Tests
# ---------------------------------------------------------------------------

class TestDuplicateDetection:
    def test_find_duplicate_by_id(self, scanned_index):
        """Las Vegas Transfer Station (1430152) is on both S and P drives."""
        results = scanned_index.find_duplicates(project_id="1430152")
        assert len(results) == 1
        assert results[0]["project_id"] == "1430152"
        assert len(results[0]["locations"]) == 2
        drive_letters = {loc["drive_letter"] for loc in results[0]["locations"]}
        assert drive_letters == {"S", "P"}

    def test_find_all_duplicates(self, scanned_index):
        """Should find Las Vegas (1430152) as a duplicate across drives."""
        results = scanned_index.find_duplicates()
        assert len(results) >= 1
        project_ids = {r["project_id"] for r in results}
        assert "1430152" in project_ids

    def test_no_duplicate_for_unique_project(self, scanned_index):
        """Project only on one drive should not be a duplicate."""
        results = scanned_index.find_duplicates(project_id="1290045")
        assert len(results) == 0

    def test_duplicate_match_reason(self, scanned_index):
        results = scanned_index.find_duplicates(project_id="1430152")
        assert results[0]["match_reason"] == "same_project_id"

    def test_duplicate_has_windows_paths(self, scanned_index):
        results = scanned_index.find_duplicates(project_id="1430152")
        for loc in results[0]["locations"]:
            assert "windows_path" in loc
            assert "\\" in loc["windows_path"]

    def test_find_duplicates_by_query(self, scanned_index):
        results = scanned_index.find_duplicates(query="Las Vegas")
        assert len(results) >= 1
        assert any(r["project_id"] == "1430152" for r in results)


# ---------------------------------------------------------------------------
# Stats and Metadata Tests
# ---------------------------------------------------------------------------

class TestStatsAndMetadata:
    def test_stats_before_scan(self, index):
        stats = index.get_stats()
        assert stats["initialized"] is True
        assert stats["total_directories"] == 0

    def test_stats_after_scan(self, scanned_index):
        stats = scanned_index.get_stats()
        assert stats["total_directories"] == 7
        assert stats["total_drives"] == 2
        assert stats["unique_project_ids"] > 0

    def test_last_scan_before_scan(self, index):
        assert index.get_last_scan() is None

    def test_last_scan_after_scan(self, scanned_index):
        scan = scanned_index.get_last_scan()
        assert scan is not None
        assert scan["status"] == "completed"
        assert scan["total_directories"] == 7

    def test_stats_drives_list(self, scanned_index):
        stats = scanned_index.get_stats()
        assert "S Drive (Test)" in stats["drives"]
        assert "P Drive (Test)" in stats["drives"]


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_drive(self, tmp_path, tmp_db):
        """A drive with no project directories."""
        empty_drive = tmp_path / "empty_drive"
        empty_drive.mkdir()

        drives = [{
            "name": "Empty",
            "mount_path": str(empty_drive),
            "drive_letter": "E",
            "has_department_level": False,
        }]

        idx = DirectoryIndex(db_path=tmp_db, drives=drives)
        idx.initialize()
        result = idx.scan_drives()
        assert result["status"] == "completed"
        assert result["directories_found"] == 0

    def test_hidden_directories_skipped(self, tmp_path, tmp_db):
        """Directories starting with . should be skipped."""
        drive = tmp_path / "drive"
        (drive / ".hidden_project").mkdir(parents=True)
        (drive / "Visible Project (1234567)").mkdir(parents=True)

        drives = [{
            "name": "Test",
            "mount_path": str(drive),
            "drive_letter": "T",
            "has_department_level": False,
        }]

        idx = DirectoryIndex(db_path=tmp_db, drives=drives)
        idx.initialize()
        result = idx.scan_drives()
        assert result["directories_found"] == 1

    def test_uninitialized_returns_empty(self):
        idx = DirectoryIndex(db_path="/tmp/nonexistent.db", drives=[])
        assert idx.is_available() is False
        assert idx.search_project_location("test") == []
        assert idx.find_duplicates() == []
        assert idx.get_last_scan() is None

    def test_scan_not_initialized(self):
        idx = DirectoryIndex(db_path="/tmp/nonexistent.db", drives=[])
        result = idx.scan_drives()
        assert result["status"] == "error"
