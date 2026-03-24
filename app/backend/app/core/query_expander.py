"""
Query expansion to improve semantic search recall.
Rewrites vague queries to include domain-specific terms.

Key strategy: Map user intent to document types likely to contain the answer.
"""

from typing import List, Tuple, Set
import re
import logging

logger = logging.getLogger(__name__)


class QueryExpander:
    """Expand queries with synonyms and domain terms."""
    
    # Domain-specific expansion rules for engineering/construction/environmental
    EXPANSION_RULES = {
        # Project overview queries - need cover pages, proposals, scope docs
        "summary": ["scope of work", "project description", "executive summary"],
        "purpose": ["objective", "scope of work", "project purpose"],
        "about": ["project description", "scope", "overview"],
        "overview": ["executive summary", "project description", "scope of work"],
        "outcome": ["findings", "results", "conclusions", "recommendations"],
        "outcomes": ["findings", "results", "conclusions", "recommendations"],
        "result": ["findings", "outcomes", "conclusions"],
        "results": ["findings", "outcomes", "conclusions"],
        
        # Location queries
        "where": ["location", "site address", "city", "property"],
        "located": ["site address", "property location", "city state"],
        "address": ["site location", "property address", "street"],
        "location": ["site address", "city", "property"],
        
        # Client/stakeholder queries - contracts, proposals, cover letters
        "client": ["owner", "contracted by", "agreement between", "prepared for"],
        "who hired": ["client", "owner", "contracted by", "agreement"],
        "owner": ["client", "property owner", "contracted by"],
        "contractor": ["subcontractor", "contracted to", "performed by"],
        
        # Technical terms (environmental consulting)
        "esa": ["environmental site assessment", "phase I", "phase II", "ESA"],
        "environmental": ["site assessment", "contamination", "remediation", "hazardous"],
        "testing": ["sampling", "analysis", "laboratory", "investigation"],
        "assessment": ["evaluation", "investigation", "study", "report"],
        "contamination": ["hazardous", "contaminated", "remediation", "cleanup"],
        "asbestos": ["ACM", "asbestos-containing", "abatement", "survey"],
        
        # Project identification
        "project number": ["job number", "project ID", "contract number"],
        "job": ["project", "contract", "work order"],
        
        # Date/time queries
        "when": ["date", "dated", "year", "timeline"],
        "date": ["dated", "year", "completed"],
        
        # Cost/budget queries
        "cost": ["budget", "fee", "amount", "price", "invoice"],
        "budget": ["cost", "fee", "estimate", "amount"],
        "fee": ["cost", "amount", "invoice", "payment"],

        # Project metadata expansions (for metadata-first search)
        "nmed": ["New Mexico Environment Department", "environmental"],
        "bia": ["Bureau of Indian Affairs"],
        "epa": ["Environmental Protection Agency"],
        "water system": ["water", "sewer", "infrastructure", "pipeline"],
        "transfer station": ["solid waste", "landfill", "waste management"],
        "day school": ["school", "education", "BIA"],
    }
    
    # Map query intents to document types most likely to have answers
    INTENT_DOC_HINTS = {
        "client": ["contract", "agreement", "proposal", "cover letter"],
        "owner": ["contract", "agreement", "proposal"],
        "location": ["report", "proposal", "assessment", "cover"],
        "summary": ["proposal", "report", "scope", "executive summary"],
        "overview": ["proposal", "report", "scope"],
        "outcome": ["report", "assessment", "summary", "findings"],
        "outcomes": ["report", "assessment", "summary", "findings"],
        "result": ["report", "assessment", "summary"],
        "results": ["report", "assessment", "summary"],
        "cost": ["invoice", "proposal", "contract", "budget"],
        "fee": ["invoice", "proposal", "contract"],
        "date": ["contract", "report", "proposal", "letter"],
        "team": ["proposal", "qualifications", "organization"],
    }
    
    # Patterns that indicate a vague/contextual query
    VAGUE_PATTERNS = [
        r"^this project",
        r"^the project",
        r"^that project",
        r"what (was|is|were) (the|this|that)",
        r"where (was|is|were) (the|this|that)",
        r"who (was|is|were) (the|this|that)",
        r"tell me about",
        r"can you (tell|find|show)",
    ]
    
    def expand_query(self, query: str) -> str:
        """
        Expand query with domain-specific synonyms.

        Limits total expansion terms to 5 to prevent precision degradation
        from embedding too many loosely related terms.

        Args:
            query: Original user query

        Returns:
            Expanded query with additional terms
        """
        query_lower = query.lower()
        expanded_terms = set()  # Use set to avoid duplicates

        # Check each word/phrase in query against expansion rules
        for keyword, expansions in self.EXPANSION_RULES.items():
            if keyword in query_lower:
                # Add most relevant expansions (up to 2 per keyword match)
                expanded_terms.update(expansions[:2])

        if expanded_terms:
            # Cap total expansion terms at 5 to preserve precision
            limited_terms = list(expanded_terms)[:5]
            expanded = f"{query} {' '.join(limited_terms)}"
            logger.info(f"Expanded query: '{query}' -> '{expanded}' ({len(limited_terms)} terms added)")
            return expanded

        return query
    
    def get_doc_type_hints(self, query: str) -> List[str]:
        """
        Get document types likely to contain the answer.
        
        Args:
            query: User query
            
        Returns:
            List of document type keywords to boost in retrieval
        """
        query_lower = query.lower()
        hints = set()
        
        for keyword, doc_types in self.INTENT_DOC_HINTS.items():
            if keyword in query_lower:
                hints.update(doc_types)
        
        return list(hints)
    
    def is_vague_query(self, query: str) -> bool:
        """
        Check if query is vague/needs context.
        
        Args:
            query: User query
            
        Returns:
            True if query is vague
        """
        query_lower = query.lower().strip()
        
        for pattern in self.VAGUE_PATTERNS:
            if re.search(pattern, query_lower):
                return True
        
        # Also vague if very short
        if len(query.split()) <= 3:
            return True
            
        return False
    
    def extract_query_intent(self, query: str) -> Tuple[str, List[str]]:
        """
        Extract the intent and key entities from a query.
        
        Args:
            query: User query
            
        Returns:
            Tuple of (intent_type, extracted_entities)
        """
        query_lower = query.lower()
        
        # Detect intent type
        if any(word in query_lower for word in ["where", "location", "located", "address", "site"]):
            intent = "location"
        elif any(word in query_lower for word in ["who", "client", "owner", "contractor"]):
            intent = "stakeholder"
        elif any(word in query_lower for word in ["when", "date", "year", "timeline"]):
            intent = "temporal"
        elif any(word in query_lower for word in ["what", "summary", "about", "describe", "overview"]):
            intent = "overview"
        elif any(word in query_lower for word in ["project number", "job number", "project id"]):
            intent = "identifier"
        else:
            intent = "general"
        
        # Extract potential entities (proper nouns, numbers)
        entities = []
        # Look for capitalized words that might be names
        words = query.split()
        for word in words:
            if word[0].isupper() and word.lower() not in ["what", "where", "who", "when", "how", "the", "this", "that"]:
                entities.append(word)
        
        return intent, entities
    
    def rewrite_query(self, query: str) -> List[str]:
        """
        Generate alternative query formulations.
        
        Args:
            query: Original query
            
        Returns:
            List of query variations
        """
        variations = [query]  # Always include original
        
        query_lower = query.lower()
        
        # Extract intent to generate better variations
        intent, entities = self.extract_query_intent(query)
        
        if intent == "location":
            variations.extend([
                "project location site address",
                "where is the site located city state",
            ])
        elif intent == "stakeholder":
            variations.extend([
                "client owner customer contracted by",
                "prepared for submitted to",
            ])
        elif intent == "overview":
            variations.extend([
                "scope of work project description",
                "work performed activities completed",
            ])
            if "outcome" in query_lower or "result" in query_lower:
                variations.extend([
                    "key findings outcomes recommendations",
                    "results conclusions summary",
                ])
        elif intent == "identifier":
            variations.extend([
                "project number job number contract",
                "project ID reference number",
            ])
        
        # Generic fallbacks
        if "what was" in query_lower or "what is" in query_lower:
            cleaned = query_lower.replace("what was", "").replace("what is", "").strip()
            if cleaned:
                variations.append(cleaned)
        
        return variations[:4]  # Limit to 4 variations

    def expand_for_metadata(self, query: str) -> str:
        """Expand query for project metadata search.

        Lighter expansion than document search since metadata chunks are
        short and precise -- heavy expansion hurts precision.

        Args:
            query: Original user query

        Returns:
            Expanded query (max 3 additional terms)
        """
        query_lower = query.lower()
        expanded_terms: Set[str] = set()

        for keyword, expansions in self.EXPANSION_RULES.items():
            if keyword in query_lower:
                expanded_terms.update(expansions[:1])

        if expanded_terms:
            limited = list(expanded_terms)[:3]
            expanded = f"{query} {' '.join(limited)}"
            logger.info(f"Metadata expansion: '{query}' -> '{expanded}'")
            return expanded

        return query
