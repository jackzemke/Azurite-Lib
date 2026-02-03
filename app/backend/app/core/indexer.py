"""
Indexer using ChromaDB.

Manages vector index for semantic search.
"""

import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional
from pathlib import Path
import logging
import os

# Disable ChromaDB telemetry to avoid posthog errors
os.environ["ANONYMIZED_TELEMETRY"] = "False"

logger = logging.getLogger(__name__)


class Indexer:
    """Manage ChromaDB vector index for chunks."""

    def __init__(self, chroma_db_path: Path, collection_name: str = "project_docs"):
        """
        Initialize ChromaDB client.

        Args:
            chroma_db_path: Path to persistent Chroma DB directory
            collection_name: Name of collection to use
        """
        self.chroma_db_path = Path(chroma_db_path)
        self.collection_name = collection_name

        # Ensure DB directory exists
        self.chroma_db_path.mkdir(parents=True, exist_ok=True)

        # Initialize persistent client with telemetry disabled
        logger.info(f"Initializing ChromaDB at {chroma_db_path}")
        self.client = chromadb.PersistentClient(
            path=str(chroma_db_path),
            settings=Settings(anonymized_telemetry=False)
        )

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},  # Use cosine similarity
        )

        logger.info(f"Collection '{collection_name}' ready. Count: {self.collection.count()}")

    def upsert_chunks(self, chunks: List[Dict], embeddings: List[Dict]):
        """
        Upsert chunks and embeddings into Chroma.

        Args:
            chunks: List of chunk dicts with metadata
            embeddings: List of embedding dicts with 'embedding' field
        """
        if not chunks or not embeddings:
            logger.warning("No chunks or embeddings to upsert")
            return

        if len(chunks) != len(embeddings):
            raise ValueError(f"Chunks ({len(chunks)}) and embeddings ({len(embeddings)}) count mismatch")

        # Prepare data for Chroma
        ids = [chunk["chunk_id"] for chunk in chunks]
        documents = [chunk["text"] for chunk in chunks]
        metadatas = [
            {
                # Core identifiers (for filtering)
                "project_id": chunk["project_id"],           # Folder name - main filter key
                "file_id": chunk.get("file_id") or "",       # File system ID (e.g., "1430152")
                "project_key": chunk.get("project_key") or "", # Ajera key (e.g., "125259")
                
                # File information
                "file_path": chunk["file_path"],
                "file_basename": chunk["file_basename"],
                "page_number": chunk["page_number"],
                "doc_type": chunk.get("doc_type", "document"),
                
                # Content metadata
                "tokens": chunk["tokens"],
                "document_title": chunk.get("document_title") or "",
                "section_header": chunk.get("section_header") or "",
                
                # Quality indicators
                "ocr_confidence": chunk.get("ocr_confidence", 0.0),
                
                # Timestamps
                "created_at": chunk["created_at"],
            }
            for chunk in chunks
        ]
        embedding_vectors = [emb["embedding"].tolist() for emb in embeddings]

        # Upsert to Chroma
        logger.info(f"Upserting {len(chunks)} chunks to Chroma")
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embedding_vectors,
        )

        logger.info(f"Upsert complete. Total chunks in collection: {self.collection.count()}")

    def query(
        self,
        query_embedding: List[float],
        project_ids: Optional[List[str]] = None,
        top_k: int = 6,
        diversity: bool = True,
        max_per_document: int = 2,
        doc_type_hints: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        Query Chroma for similar chunks with optional diversity enforcement.

        Args:
            query_embedding: Query vector
            project_ids: Filter by list of project IDs (optional, None = all projects)
            top_k: Number of results to return
            diversity: If True, enforce document diversity (limit chunks per document)
            max_per_document: Max chunks from same document when diversity=True
            doc_type_hints: List of document type keywords to boost (e.g., ["contract", "proposal"])

        Returns:
            List of dicts with chunk_id, text, metadata, distance
        """
        # Build filter
        where = None
        if project_ids and len(project_ids) > 0:
            # ChromaDB supports $in operator for multiple values
            where = {"project_id": {"$in": project_ids}}

        # Fetch more candidates for diversity filtering and re-ranking
        fetch_k = max(top_k * 4, 20) if diversity else top_k

        # Query Chroma
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=fetch_k,
            where=where,
            include=["documents", "metadatas", "distances"]
        )

        # Parse results
        all_chunks = []
        if results["ids"] and len(results["ids"]) > 0:
            for i in range(len(results["ids"][0])):
                chunk = {
                    "chunk_id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if "distances" in results else None,
                }
                all_chunks.append(chunk)
        
        # Log retrieval stats for debugging
        if all_chunks:
            distances = [c["distance"] for c in all_chunks[:5]]
            logger.info(f"Retrieved {len(all_chunks)} candidates, top-5 distances: {[f'{d:.3f}' for d in distances]}")
        
        # Apply doc type hint boosting if provided
        if doc_type_hints and all_chunks:
            all_chunks = self._apply_doc_type_boost(all_chunks, doc_type_hints)
        
        # Apply diversity filtering if enabled
        if diversity and len(all_chunks) > top_k:
            all_chunks = self._apply_diversity(all_chunks, top_k, max_per_document)
        else:
            all_chunks = all_chunks[:top_k]

        return all_chunks
    
    def _apply_doc_type_boost(
        self,
        chunks: List[Dict],
        doc_type_hints: List[str],
        boost_factor: float = 0.05
    ) -> List[Dict]:
        """
        Boost chunks from document types matching the hints.
        
        Lower distance = better match, so we subtract from distance for matches.
        
        Args:
            chunks: List of chunks with distances
            doc_type_hints: Keywords to look for in file names
            boost_factor: How much to reduce distance for matches
            
        Returns:
            Re-sorted chunks with boosted distances
        """
        for chunk in chunks:
            file_name = chunk["metadata"].get("file_basename", "").lower()
            file_path = chunk["metadata"].get("file_path", "").lower()
            
            # Check if any hint matches the filename
            for hint in doc_type_hints:
                if hint.lower() in file_name or hint.lower() in file_path:
                    # Boost this chunk by reducing its distance
                    original_dist = chunk["distance"]
                    chunk["distance"] = max(0, original_dist - boost_factor)
                    logger.debug(f"Boosted '{file_name}' for hint '{hint}': {original_dist:.3f} -> {chunk['distance']:.3f}")
                    break
        
        # Re-sort by adjusted distance
        chunks.sort(key=lambda x: x["distance"])
        return chunks

    def _apply_diversity(
        self,
        chunks: List[Dict],
        top_k: int,
        max_per_document: int
    ) -> List[Dict]:
        """
        Apply MMR-style diversity to chunk results.
        
        Ensures we don't return too many chunks from the same document,
        while still prioritizing relevance (lower distance = better).
        
        Also deduplicates "sibling" documents (e.g., multiple invoices)
        by detecting similar file name patterns.
        
        Args:
            chunks: List of chunks sorted by relevance
            top_k: Target number of results
            max_per_document: Max chunks per document
            
        Returns:
            Diverse subset of chunks
        """
        selected = []
        doc_counts = {}  # file_path -> count
        doc_family_counts = {}  # normalized filename pattern -> count
        
        for chunk in chunks:
            if len(selected) >= top_k:
                break
                
            file_path = chunk["metadata"].get("file_path", "unknown")
            file_basename = chunk["metadata"].get("file_basename", "")
            
            # Check per-file limit
            current_count = doc_counts.get(file_path, 0)
            if current_count >= max_per_document:
                continue
            
            # Check for "sibling" documents (e.g., Invoice #01, Invoice #02)
            # Normalize filename to detect family
            doc_family = self._get_doc_family(file_basename)
            family_count = doc_family_counts.get(doc_family, 0)
            
            # Allow max 2 documents from same family (e.g., 2 invoices total)
            max_per_family = 2
            if family_count >= max_per_family:
                logger.debug(f"Skipping '{file_basename}' - family '{doc_family}' already has {family_count} docs")
                continue
            
            selected.append(chunk)
            doc_counts[file_path] = current_count + 1
            doc_family_counts[doc_family] = family_count + 1
        
        # If we haven't filled top_k yet, add remaining chunks
        # (better to have some results than too few)
        if len(selected) < top_k:
            for chunk in chunks:
                if chunk not in selected:
                    selected.append(chunk)
                    if len(selected) >= top_k:
                        break
        
        logger.debug(f"Diversity filter: {len(chunks)} candidates -> {len(selected)} selected from {len(doc_counts)} documents, {len(doc_family_counts)} families")
        return selected
    
    def _get_doc_family(self, filename: str) -> str:
        """
        Get a normalized "family" name for a document.
        
        This groups similar documents together:
        - "Invoice # 422985401 & cover letter.pdf" -> "invoice_cover_letter"
        - "Invoice # 422985402 & cover letter.pdf" -> "invoice_cover_letter"
        
        Args:
            filename: Original filename
            
        Returns:
            Normalized family string
        """
        import re
        
        # Remove file extension
        name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        
        # Remove numbers (dates, IDs, etc.)
        name = re.sub(r'\d+', '', name)
        
        # Remove special characters, normalize whitespace
        name = re.sub(r'[^a-zA-Z\s]', ' ', name)
        name = ' '.join(name.lower().split())
        
        # If too short after normalization, use first 20 chars of original
        if len(name) < 3:
            name = filename[:20].lower()
        
        return name

    def get_chunk(self, chunk_id: str) -> Optional[Dict]:
        """
        Retrieve a specific chunk by ID.

        Args:
            chunk_id: Chunk ID

        Returns:
            Chunk dict or None if not found
        """
        try:
            result = self.collection.get(ids=[chunk_id], include=["documents", "metadatas"])

            if result["ids"] and len(result["ids"]) > 0:
                return {
                    "chunk_id": result["ids"][0],
                    "text": result["documents"][0],
                    "metadata": result["metadatas"][0],
                }
            return None

        except Exception as e:
            logger.error(f"Failed to get chunk {chunk_id}: {e}")
            return None

    def get_indexed_projects(self) -> List[str]:
        """
        Get list of project IDs that have indexed chunks.

        Returns:
            List of project IDs
        """
        try:
            # Get all unique project_ids from collection
            # Note: Chroma doesn't have a direct way to get unique metadata values,
            # so we sample a large batch and extract unique project_ids
            result = self.collection.get(limit=10000, include=["metadatas"])

            if not result["metadatas"]:
                return []

            project_ids = set()
            for metadata in result["metadatas"]:
                if "project_id" in metadata:
                    project_ids.add(metadata["project_id"])

            return sorted(list(project_ids))

        except Exception as e:
            logger.error(f"Failed to get indexed projects: {e}")
            return []

    def delete_project(self, project_id: str):
        """
        Delete all chunks for a project.

        Args:
            project_id: Project ID to delete
        """
        logger.info(f"Deleting all chunks for project {project_id}")

        # Get all chunk IDs for this project
        result = self.collection.get(
            where={"project_id": project_id},
            include=["metadatas"],
        )

        if result["ids"]:
            self.collection.delete(ids=result["ids"])
            logger.info(f"Deleted {len(result['ids'])} chunks for project {project_id}")
        else:
            logger.info(f"No chunks found for project {project_id}")


# TODO: Add batch upsert for very large datasets (>10k chunks)
# TODO: Implement hybrid search (combine with keyword search)
