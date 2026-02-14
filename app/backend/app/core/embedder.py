"""
Embedder using sentence-transformers.

Generates vector embeddings for text chunks using nomic-embed-text-v1.5.
Supports task-type prefixes (search_document / search_query) required
by the nomic model for optimal quality.
"""

import torch
from sentence_transformers import SentenceTransformer
from typing import List, Dict
import numpy as np
import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Task prefixes required by nomic-embed-text-v1.5.
# Without these, embedding quality degrades significantly.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


class Embedder:
    """Generate embeddings for text chunks and queries."""

    def __init__(self, model_name: str = "nomic-ai/nomic-embed-text-v1.5", batch_size: int = 32):
        """
        Initialize embedder.

        Args:
            model_name: Hugging Face model name
            batch_size: Batch size for embedding generation
        """
        self.model_name = model_name
        self.batch_size = batch_size

        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name, trust_remote_code=True)

        # Move to GPU if available
        if torch.cuda.is_available():
            self.model = self.model.to(torch.device("cuda"))
            logger.info(f"Embedding model loaded on CUDA ({torch.cuda.get_device_name(0)})")
        else:
            logger.info("Embedding model loaded on CPU (CUDA not available)")

        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        logger.info(f"Embedding dimension: {self.embedding_dim}")

    def embed_chunks(self, chunks: List[Dict]) -> List[Dict]:
        """
        Generate embeddings for a list of chunks (documents).

        Prepends 'search_document: ' prefix to each text for optimal
        nomic-embed-text quality.

        Args:
            chunks: List of chunk dicts with 'text' field

        Returns:
            List of dicts with 'chunk_id', 'file_path', 'page', 'embedding'
        """
        if not chunks:
            return []

        # Prepend document prefix for nomic model
        texts = [DOCUMENT_PREFIX + chunk["text"] for chunk in chunks]

        logger.info(f"Embedding {len(texts)} chunks in batches of {self.batch_size}")
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
        )

        results = []
        for i, chunk in enumerate(chunks):
            results.append({
                "chunk_id": chunk["chunk_id"],
                "file_path": chunk["file_path"],
                "page": chunk["page_number"],
                "project_id": chunk["project_id"],
                "embedding": embeddings[i],
            })

        return results

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a single query string for retrieval.

        Prepends 'search_query: ' prefix for optimal nomic-embed-text quality.

        Args:
            query: Query text

        Returns:
            Embedding as list of floats (ready for ChromaDB)
        """
        prefixed = QUERY_PREFIX + query
        embedding = self.model.encode([prefixed], convert_to_numpy=True)[0]
        return embedding.tolist()

    def save_embeddings(self, embeddings: List[Dict], output_path: Path):
        """
        Save embeddings to parquet file.

        Args:
            embeddings: List of embedding dicts
            output_path: Path to save parquet file
        """
        if not embeddings:
            logger.warning("No embeddings to save")
            return

        # Convert to DataFrame
        df = pd.DataFrame({
            "chunk_id": [e["chunk_id"] for e in embeddings],
            "file_path": [e["file_path"] for e in embeddings],
            "page": [e["page"] for e in embeddings],
            "project_id": [e["project_id"] for e in embeddings],
            "embedding_vector": [e["embedding"].tolist() for e in embeddings],
        })

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save to parquet
        df.to_parquet(output_path, index=False)
        logger.info(f"Saved {len(embeddings)} embeddings to {output_path}")

    def load_embeddings(self, input_path: Path) -> List[Dict]:
        """
        Load embeddings from parquet file.

        Args:
            input_path: Path to parquet file

        Returns:
            List of embedding dicts
        """
        df = pd.read_parquet(input_path)

        embeddings = []
        for _, row in df.iterrows():
            embeddings.append({
                "chunk_id": row["chunk_id"],
                "file_path": row["file_path"],
                "page": row["page"],
                "project_id": row["project_id"],
                "embedding": np.array(row["embedding_vector"]),
            })

        logger.info(f"Loaded {len(embeddings)} embeddings from {input_path}")
        return embeddings
