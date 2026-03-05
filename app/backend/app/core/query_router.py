"""
Rule-based query router for intent classification.

Classifies user queries into one or more intent types using keyword
and regex pattern matching. Designed for ~0ms overhead (no ML inference).

Intent types:
  - DOCUMENT_QA: Questions about document content (default, always present)
  - PERSONNEL: Questions about employees, teams, hours (Ajera data)
  - FILE_LOCATION: Questions about where projects/files live on network drives
  - DUPLICATE_DETECTION: Questions about duplicate directories/files across drives
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import re
import logging

logger = logging.getLogger(__name__)


class QueryIntent(str, Enum):
    """Intent types for query routing."""
    DOCUMENT_QA = "document_qa"
    PERSONNEL = "personnel"
    FILE_LOCATION = "file_location"
    DUPLICATE_DETECTION = "duplicate_detection"


@dataclass
class RouterResult:
    """Result of query classification."""
    intents: List[QueryIntent] = field(default_factory=lambda: [QueryIntent.DOCUMENT_QA])
    confidence_scores: Dict[QueryIntent, float] = field(default_factory=dict)
    extracted_entities: List[str] = field(default_factory=list)

    # Legacy compatibility flags (replace is_team_query, is_broad_query in query.py)
    is_broad_query: bool = False
    is_team_query: bool = False

    # Intent-specific extraction
    drive_mention: Optional[str] = None

    @property
    def has_personnel(self) -> bool:
        return QueryIntent.PERSONNEL in self.intents

    @property
    def has_file_location(self) -> bool:
        return QueryIntent.FILE_LOCATION in self.intents

    @property
    def has_duplicate_detection(self) -> bool:
        return QueryIntent.DUPLICATE_DETECTION in self.intents

    @property
    def is_multi_intent(self) -> bool:
        return len(self.intents) > 1


# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

# Absorbs team_keywords from query.py:107-110
PERSONNEL_KEYWORDS: List[str] = [
    # Phrase-level (checked first, stronger signal)
    "who worked", "who's working", "who is working", "working on",
    "worked on", "who was", "who did", "who is on",
    "how many hours", "hours logged", "hours spent", "time spent",
    "billable hours", "total hours",
    "project manager", "project team",
    # Word-level
    "team", "staff", "people", "employees", "personnel",
    "engineer", "engineers", "manager", "pm",
    "architect", "designer", "technician",
]

FILE_LOCATION_KEYWORDS: List[str] = [
    # Phrase-level
    "where is the project", "where are the files", "where is this stored",
    "where can i find", "what drive", "which drive", "what folder",
    "which folder", "file location", "file path", "folder path",
    "where is it stored", "where is it saved", "where is it located",
    "network drive", "network path", "server path",
    "project folder", "project directory",
    # Drive letter references
    "s drive", "p drive", "n drive", "z drive",
    "s:", "p:", "n:", "z:",
]

FILE_LOCATION_PATTERNS: List[re.Pattern] = [
    re.compile(r"where\s+(is|are|can\s+i\s+find)\s+.*(project|file|folder|document)\s.*(stored|saved|located|kept)", re.IGNORECASE),
    re.compile(r"(which|what)\s+drive", re.IGNORECASE),
    re.compile(r"(path|location)\s+(to|of|for)\s+.*(file|folder|project|document)", re.IGNORECASE),
    re.compile(r"stored\s+(on|in|at)\s+.*(drive|server|network)", re.IGNORECASE),
    re.compile(r"[A-Z]:\\", re.IGNORECASE),
]

DUPLICATE_DETECTION_KEYWORDS: List[str] = [
    # Phrase-level
    "is this duplicated", "is this project duplicated",
    "does this exist on another", "duplicate directories",
    "duplicate folders", "duplicate files", "duplicate copies",
    "exists on another drive", "copied to another",
    "multiple copies", "redundant copies",
    "same project on", "also stored on",
    # Word-level (only match in combination with context)
    "duplicated", "duplicate", "redundant",
]

DUPLICATE_DETECTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"(duplicat|redundant|copied)\w*\s+.*(project|folder|file|director)", re.IGNORECASE),
    re.compile(r"(exist|stored|saved|copied)\s+.*(another|other|multiple)\s+(drive|folder|location)", re.IGNORECASE),
    re.compile(r"(same|identical)\s+(project|folder|file)\s+on", re.IGNORECASE),
]

# Absorbs is_broad_query keywords from query.py:114
BROAD_QUERY_KEYWORDS: List[str] = [
    "summary", "overview", "purpose", "about",
    "describe", "explain", "what was",
]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_query(query: str) -> RouterResult:
    """
    Classify a query into one or more intent types.

    Uses keyword matching and regex patterns for ~0ms classification.
    DOCUMENT_QA is always included as the default/base intent.
    Other intents are additive (non-exclusive).

    Args:
        query: The user's natural language query

    Returns:
        RouterResult with detected intents and metadata
    """
    query_lower = query.lower().strip()
    result = RouterResult()

    # --- PERSONNEL detection ---
    personnel_score = _score_keywords(query_lower, PERSONNEL_KEYWORDS)
    if personnel_score > 0:
        result.intents.append(QueryIntent.PERSONNEL)
        result.confidence_scores[QueryIntent.PERSONNEL] = min(personnel_score, 1.0)
        result.is_team_query = True

    # --- FILE_LOCATION detection ---
    location_score = _score_keywords(query_lower, FILE_LOCATION_KEYWORDS)
    location_pattern_match = any(p.search(query) for p in FILE_LOCATION_PATTERNS)
    if location_score > 0 or location_pattern_match:
        result.intents.append(QueryIntent.FILE_LOCATION)
        combined_score = location_score + (0.5 if location_pattern_match else 0)
        result.confidence_scores[QueryIntent.FILE_LOCATION] = min(combined_score, 1.0)
        # Extract drive letter mention
        drive_match = re.search(r'([A-Za-z])\s*(?:drive|:)', query, re.IGNORECASE)
        if drive_match:
            result.drive_mention = drive_match.group(1).upper()

    # --- DUPLICATE_DETECTION detection ---
    dup_score = _score_keywords(query_lower, DUPLICATE_DETECTION_KEYWORDS)
    dup_pattern_match = any(p.search(query) for p in DUPLICATE_DETECTION_PATTERNS)
    if dup_score > 0 or dup_pattern_match:
        result.intents.append(QueryIntent.DUPLICATE_DETECTION)
        combined_score = dup_score + (0.5 if dup_pattern_match else 0)
        result.confidence_scores[QueryIntent.DUPLICATE_DETECTION] = min(combined_score, 1.0)

    # --- BROAD query detection ---
    if any(term in query_lower for term in BROAD_QUERY_KEYWORDS):
        result.is_broad_query = True

    # --- DOCUMENT_QA confidence ---
    if len(result.intents) == 1:
        result.confidence_scores[QueryIntent.DOCUMENT_QA] = 1.0
    else:
        result.confidence_scores[QueryIntent.DOCUMENT_QA] = 0.7

    # --- Entity extraction ---
    result.extracted_entities = _extract_entities(query)

    logger.info(
        f"[ROUTER] Query: '{query[:80]}' -> intents={[i.value for i in result.intents]}, "
        f"broad={result.is_broad_query}, team={result.is_team_query}"
    )

    return result


def _score_keywords(query_lower: str, keywords: List[str]) -> float:
    """
    Score how strongly a query matches a keyword list.

    Phrase matches (multi-word) score higher than single-word matches.

    Returns:
        Confidence score (0.0 = no match, higher = stronger match)
    """
    score = 0.0
    for keyword in keywords:
        if keyword in query_lower:
            if " " in keyword:
                score += 0.6
            else:
                score += 0.3
    return score


def _extract_entities(query: str) -> List[str]:
    """
    Extract potential entity names from the query.

    Looks for quoted strings and capitalized words that aren't
    common question words.
    """
    entities = []

    # Extract quoted strings
    quoted = re.findall(r'"([^"]+)"', query)
    entities.extend(quoted)

    # Extract capitalized words (potential project/person names)
    skip_words = {
        "what", "where", "who", "when", "how", "the", "this", "that",
        "is", "are", "was", "were", "can", "could", "would", "should",
        "do", "does", "did", "has", "have", "had", "i", "my", "me",
        "and", "or", "but", "not", "on", "in", "at", "to", "for",
        "of", "with", "from", "by", "about", "which", "project",
    }
    words = query.split()
    for word in words:
        cleaned = word.strip("?.,!;:'\"")
        if cleaned and cleaned[0].isupper() and cleaned.lower() not in skip_words:
            entities.append(cleaned)

    return entities
