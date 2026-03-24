"""
Metadata indexer for project-level metadata search.

Reads metadata_index.json, creates one rich-text chunk per project,
embeds using nomic-embed-text-v1.5, and upserts into ChromaDB
collection 'project_metadata'.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

import chromadb
from chromadb.config import Settings as ChromaSettings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "project_metadata"


class MetadataIndexer:
    """Index project metadata for semantic search."""

    def __init__(self, chroma_db_path: Path, metadata_index_path: Path):
        self.chroma_db_path = Path(chroma_db_path)
        self.metadata_index_path = Path(metadata_index_path)

        self.chroma_db_path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(self.chroma_db_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": "nomic-ai/nomic-embed-text-v1.5",
            },
        )
        logger.info(
            f"Collection '{COLLECTION_NAME}' ready. Count: {self.collection.count()}"
        )

    # ---- Chunk Construction ----

    def build_chunk_text(self, project: Dict[str, Any]) -> str:
        """Render a single project's metadata as rich text for embedding.

        Format preserves inter-field relationships for semantic matching.
        """
        lines = []
        lines.append(f"Project: {project.get('project_name', 'Unknown')}")
        lines.append(f"ID: {project.get('project_id', 'Unknown')}")

        if project.get("department"):
            lines.append(f"Department: {project['department']}")
        if project.get("client"):
            lines.append(f"Client: {project['client']}")

        start = project.get("start_date")
        end = project.get("end_date")
        if start or end:
            lines.append(f"Dates: {start or '?'} to {end or '?'}")

        if project.get("scope_type"):
            lines.append(f"Scope: {project['scope_type']}")
        if project.get("full_path"):
            lines.append(f"Path: {project['full_path']}")

        return "\n".join(lines)

    # ---- Indexing ----

    def index_metadata(self, embedder) -> Dict[str, Any]:
        """Read metadata_index.json, embed each project, upsert into ChromaDB.

        Args:
            embedder: Embedder instance (shared singleton)

        Returns:
            Summary dict with counts and any errors
        """
        summary: Dict[str, Any] = {"indexed": 0, "skipped": 0, "errors": []}

        if not self.metadata_index_path.exists():
            summary["errors"].append(
                f"Metadata index not found: {self.metadata_index_path}"
            )
            return summary

        with open(self.metadata_index_path) as f:
            data = json.load(f)

        projects = data.get("projects", {})
        if not projects:
            summary["errors"].append("No projects in metadata index")
            return summary

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        texts_for_embedding: List[str] = []

        for project_id, project in projects.items():
            chunk_text = self.build_chunk_text(project)
            doc_id = f"meta_{project_id}"

            ids.append(doc_id)
            documents.append(chunk_text)
            texts_for_embedding.append(chunk_text)
            metadatas.append({
                "project_id": str(project_id),
                "project_name": project.get("project_name", ""),
                "department": project.get("department", ""),
                "client": project.get("client") or "",
                "start_date": project.get("start_date") or "",
                "end_date": project.get("end_date") or "",
                "scope_type": project.get("scope_type") or "",
                "full_path": project.get("full_path") or "",
                "confidence": float(project.get("confidence", 0.0)),
                "extraction_timestamp": project.get("extraction_timestamp", ""),
            })

        # Embed using shared embedder (search_document: prefix)
        from .embedder import DOCUMENT_PREFIX

        prefixed_texts = [DOCUMENT_PREFIX + t for t in texts_for_embedding]
        embedding_vectors = embedder.model.encode(
            prefixed_texts,
            batch_size=len(prefixed_texts),
            convert_to_numpy=True,
        )

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=[v.tolist() for v in embedding_vectors],
        )

        summary["indexed"] = len(ids)
        logger.info(
            f"Metadata index complete: {len(ids)} projects indexed "
            f"into '{COLLECTION_NAME}'"
        )
        return summary

    def needs_reindex(self) -> bool:
        """Check if the metadata index needs refreshing.

        Returns True if the collection is empty or metadata_index.json
        has been modified since the last index.
        """
        if self.collection.count() == 0:
            return True

        if not self.metadata_index_path.exists():
            return False

        file_mtime = self.metadata_index_path.stat().st_mtime

        sample = self.collection.peek(limit=1)
        if sample and sample.get("metadatas") and sample["metadatas"]:
            stored_ts = sample["metadatas"][0].get("extraction_timestamp", "")
            if stored_ts:
                try:
                    stored_dt = datetime.fromisoformat(stored_ts)
                    file_dt = datetime.fromtimestamp(
                        file_mtime, tz=stored_dt.tzinfo
                    )
                    return file_dt > stored_dt
                except (ValueError, TypeError):
                    pass

        return True

    # ---- Querying ----

    def query(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        department: Optional[str] = None,
    ) -> List[Dict]:
        """Query the project_metadata collection.

        Args:
            query_embedding: Query vector from Embedder.embed_query()
            top_k: Number of results
            department: Optional department filter

        Returns:
            List of dicts with project metadata and distance
        """
        where = None
        if department:
            where = {"department": department}

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        parsed = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                parsed.append({
                    "id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                })

        return parsed

    def get_project_by_id(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single project metadata record by exact project_id."""
        results = self.collection.get(
            where={"project_id": str(project_id)},
            limit=1,
            include=["documents", "metadatas"],
        )

        if not results or not results.get("ids"):
            return None

        if not results["ids"]:
            return None

        return {
            "id": results["ids"][0],
            "text": results["documents"][0],
            "metadata": results["metadatas"][0],
            "distance": 0.0,
        }

    def get_all_projects(self) -> List[Dict]:
        """Return all indexed project metadata entries."""
        result = self.collection.get(limit=1000, include=["metadatas"])
        return result.get("metadatas", [])
