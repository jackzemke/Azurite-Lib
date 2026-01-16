"""
Query expansion to improve semantic search recall.
Rewrites vague queries to include domain-specific terms.
"""

from typing import List, Tuple
import re
import logging

logger = logging.getLogger(__name__)


class QueryExpander:
    """Expand queries with synonyms and domain terms."""
    
    # Domain-specific expansion rules for engineering/construction/environmental
    EXPANSION_RULES = {
        # Project overview queries
        "summary": ["overview", "scope of work", "project description"],
        "purpose": ["objective", "goal", "scope"],
        "about": ["description", "overview", "scope"],
        
        # Location queries
        "where": ["location", "site", "address", "city", "state"],
        "located": ["location", "site address", "project site"],
        "address": ["location", "site", "property"],
        
        # Client/stakeholder queries
        "client": ["owner", "customer", "contracted by", "prepared for"],
        "who hired": ["client", "owner", "customer"],
        
        # Technical terms (environmental consulting)
        "esa": ["environmental site assessment", "phase I", "phase II"],
        "environmental": ["site assessment", "contamination", "remediation"],
        "testing": ["sampling", "analysis", "investigation"],
        "assessment": ["evaluation", "investigation", "study"],
        
        # Project identification
        "project number": ["job number", "project ID", "job no"],
        "job": ["project", "contract", "work order"],
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
                # Add most relevant expansions
                expanded_terms.update(expansions[:2])
        
        if expanded_terms:
            # Combine original query with expanded terms
            expanded = f"{query} {' '.join(expanded_terms)}"
            logger.info(f"Expanded query: '{query}' -> '{expanded}'")
            return expanded
        
        return query
    
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
