"""
Indexer using ChromaDB.

Manages vector index for semantic search.
"""

import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional
from pathlib import Path
import logging

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

        # Initialize persistent client
        logger.info(f"Initializing ChromaDB at {chroma_db_path}")
        self.client = chromadb.PersistentClient(path=str(chroma_db_path))

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
                "project_id": chunk["project_id"],
                "file_path": chunk["file_path"],
                "file_basename": chunk["file_basename"],
                "page_number": chunk["page_number"],
                "doc_type": chunk["doc_type"],
                "tokens": chunk["tokens"],
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
    ) -> List[Dict]:
        """
        Query Chroma for similar chunks.

        Args:
            query_embedding: Query vector
            project_ids: Filter by list of project IDs (optional, None = all projects)
            top_k: Number of results to return

        Returns:
            List of dicts with chunk_id, text, metadata, distance
        """
        # Build filter
        where = None
        if project_ids and len(project_ids) > 0:
            # ChromaDB supports $in operator for multiple values
            where = {"project_id": {"$in": project_ids}}

        # Query Chroma
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
        )

        # Parse results
        chunks = []
        if results["ids"] and len(results["ids"]) > 0:
            for i in range(len(results["ids"][0])):
                chunk = {
                    "chunk_id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if "distances" in results else None,
                }
                chunks.append(chunk)

        return chunks

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
