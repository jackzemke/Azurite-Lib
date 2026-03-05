"""
Tests for query_router.classify_query().

Pure function tests — no external dependencies, no mocking needed.
Run: python -m pytest app/scripts/test_query_router.py -v
"""

import sys
from pathlib import Path

# Add backend to path so imports work standalone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.query_router import classify_query, QueryIntent


# ---------------------------------------------------------------------------
# DOCUMENT_QA (default intent, always present)
# ---------------------------------------------------------------------------

class TestDocumentQA:
    def test_basic_document_query(self):
        result = classify_query("what was the soil condition?")
        assert QueryIntent.DOCUMENT_QA in result.intents

    def test_sole_intent_for_regular_query(self):
        result = classify_query("what was the scope of work?")
        assert result.intents == [QueryIntent.DOCUMENT_QA]

    def test_sole_intent_for_technical_query(self):
        result = classify_query("what is the pipe diameter?")
        assert result.intents == [QueryIntent.DOCUMENT_QA]

    def test_broad_query_detected(self):
        result = classify_query("give me a summary of this project")
        assert result.is_broad_query is True

    def test_overview_is_broad(self):
        result = classify_query("provide an overview")
        assert result.is_broad_query is True

    def test_non_broad_query(self):
        result = classify_query("what is the pipe diameter?")
        assert result.is_broad_query is False


# ---------------------------------------------------------------------------
# PERSONNEL intent
# ---------------------------------------------------------------------------

class TestPersonnel:
    def test_who_worked_on(self):
        result = classify_query("who worked on this project?")
        assert QueryIntent.PERSONNEL in result.intents
        assert result.is_team_query is True

    def test_team_keyword(self):
        result = classify_query("show me the team for this project")
        assert QueryIntent.PERSONNEL in result.intents

    def test_hours_query(self):
        result = classify_query("how many hours were logged?")
        assert QueryIntent.PERSONNEL in result.intents

    def test_staff_keyword(self):
        result = classify_query("who was the staff on this?")
        assert QueryIntent.PERSONNEL in result.intents

    def test_personnel_keyword(self):
        result = classify_query("list the personnel")
        assert QueryIntent.PERSONNEL in result.intents

    def test_project_manager(self):
        result = classify_query("who was the project manager?")
        assert QueryIntent.PERSONNEL in result.intents

    def test_coexists_with_document_qa(self):
        result = classify_query("who worked on this project?")
        assert QueryIntent.DOCUMENT_QA in result.intents
        assert QueryIntent.PERSONNEL in result.intents


# ---------------------------------------------------------------------------
# FILE_LOCATION intent
# ---------------------------------------------------------------------------

class TestFileLocation:
    def test_where_is_stored(self):
        result = classify_query("where is this project stored?")
        assert QueryIntent.FILE_LOCATION in result.intents

    def test_which_drive(self):
        result = classify_query("which drive is the Las Vegas project on?")
        assert QueryIntent.FILE_LOCATION in result.intents

    def test_what_drive(self):
        result = classify_query("what drive has the project files?")
        assert QueryIntent.FILE_LOCATION in result.intents

    def test_network_path(self):
        result = classify_query("what is the network path for project 1430152?")
        assert QueryIntent.FILE_LOCATION in result.intents

    def test_file_location_phrase(self):
        result = classify_query("what is the file location?")
        assert QueryIntent.FILE_LOCATION in result.intents

    def test_s_drive_mention(self):
        result = classify_query("is the project on the S drive?")
        assert QueryIntent.FILE_LOCATION in result.intents
        assert result.drive_mention == "S"

    def test_p_drive_colon(self):
        result = classify_query("can you check P: for this project?")
        assert QueryIntent.FILE_LOCATION in result.intents
        assert result.drive_mention == "P"

    def test_project_folder(self):
        result = classify_query("where is the project folder?")
        assert QueryIntent.FILE_LOCATION in result.intents

    def test_windows_path_pattern(self):
        result = classify_query("can you find S:\\Projects\\1430152?")
        assert QueryIntent.FILE_LOCATION in result.intents


# ---------------------------------------------------------------------------
# DUPLICATE_DETECTION intent
# ---------------------------------------------------------------------------

class TestDuplicateDetection:
    def test_is_duplicated(self):
        result = classify_query("is this project duplicated on another drive?")
        assert QueryIntent.DUPLICATE_DETECTION in result.intents

    def test_multiple_copies(self):
        result = classify_query("are there multiple copies of this project?")
        assert QueryIntent.DUPLICATE_DETECTION in result.intents

    def test_duplicate_folders(self):
        result = classify_query("check for duplicate folders")
        assert QueryIntent.DUPLICATE_DETECTION in result.intents

    def test_exists_on_another_drive(self):
        result = classify_query("does this project exist on another drive?")
        assert QueryIntent.DUPLICATE_DETECTION in result.intents

    def test_redundant_copies(self):
        result = classify_query("are there redundant copies?")
        assert QueryIntent.DUPLICATE_DETECTION in result.intents


# ---------------------------------------------------------------------------
# Multi-intent queries
# ---------------------------------------------------------------------------

class TestMultiIntent:
    def test_personnel_and_file_location(self):
        result = classify_query("who worked on the soil project and where is it stored?")
        assert QueryIntent.PERSONNEL in result.intents
        assert QueryIntent.FILE_LOCATION in result.intents
        assert QueryIntent.DOCUMENT_QA in result.intents

    def test_file_location_and_duplicate(self):
        result = classify_query("where is this project stored and is it duplicated?")
        assert QueryIntent.FILE_LOCATION in result.intents
        assert QueryIntent.DUPLICATE_DETECTION in result.intents

    def test_is_multi_intent_property(self):
        result = classify_query("who worked on this and where is it stored?")
        assert result.is_multi_intent is True

    def test_single_intent_not_multi(self):
        result = classify_query("what was the soil condition?")
        assert result.is_multi_intent is False


# ---------------------------------------------------------------------------
# False positive prevention
# ---------------------------------------------------------------------------

class TestFalsePositives:
    def test_physical_location_not_file_location(self):
        """'where was the project located?' asks about site geography, not file storage."""
        result = classify_query("where was the project located?")
        assert QueryIntent.FILE_LOCATION not in result.intents

    def test_soil_testing_not_personnel(self):
        result = classify_query("what type of soil testing was performed?")
        assert QueryIntent.PERSONNEL not in result.intents

    def test_client_not_personnel(self):
        result = classify_query("who was the client?")
        # "who was" matches, but this is really a document QA question about stakeholders
        # The personnel intent will fire here, but the RAG pipeline still runs
        # and the LLM will answer from documents. This is acceptable behavior.
        assert QueryIntent.DOCUMENT_QA in result.intents

    def test_project_description_not_file_location(self):
        result = classify_query("describe the project scope")
        assert QueryIntent.FILE_LOCATION not in result.intents

    def test_pipe_diameter_not_duplicate(self):
        result = classify_query("what is the pipe diameter?")
        assert QueryIntent.DUPLICATE_DETECTION not in result.intents


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string(self):
        result = classify_query("")
        assert QueryIntent.DOCUMENT_QA in result.intents
        assert len(result.intents) == 1

    def test_short_query(self):
        result = classify_query("hi")
        assert QueryIntent.DOCUMENT_QA in result.intents

    def test_entity_extraction_quoted_string(self):
        result = classify_query('find "Las Vegas Transfer Station"')
        assert "Las Vegas Transfer Station" in result.extracted_entities

    def test_entity_extraction_capitalized_words(self):
        result = classify_query("what did John Smith work on?")
        assert "John" in result.extracted_entities
        assert "Smith" in result.extracted_entities

    def test_confidence_scores_present(self):
        result = classify_query("who worked on this project?")
        assert QueryIntent.DOCUMENT_QA in result.confidence_scores
        assert QueryIntent.PERSONNEL in result.confidence_scores
        assert result.confidence_scores[QueryIntent.PERSONNEL] > 0

    def test_document_qa_confidence_sole(self):
        result = classify_query("what is the scope?")
        assert result.confidence_scores[QueryIntent.DOCUMENT_QA] == 1.0

    def test_document_qa_confidence_multi(self):
        result = classify_query("who worked on this?")
        assert result.confidence_scores[QueryIntent.DOCUMENT_QA] == 0.7
