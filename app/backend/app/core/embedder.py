"""
Embedder using sentence-transformers.

Generates vector embeddings for text chunks.
"""

from sentence_transformers import SentenceTransformer
from typing import List, Dict
import numpy as np
import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class Embedder:
    """Generate embeddings for text chunks."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", batch_size: int = 32):
        """
        Initialize embedder.

        Args:
            model_name: Hugging Face model name
            batch_size: Batch size for embedding generation
        """
        self.model_name = model_name
        self.batch_size = batch_size

        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        logger.info(f"Model loaded. Embedding dimension: {self.embedding_dim}")

    def embed_chunks(self, chunks: List[Dict]) -> List[Dict]:
        """
        Generate embeddings for a list of chunks.

        Args:
            chunks: List of chunk dicts with 'text' field

        Returns:
            List of dicts with 'chunk_id', 'file_path', 'page', 'embedding'
        """
        if not chunks:
            return []

        texts = [chunk["text"] for chunk in chunks]

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


# TODO: Add GPU acceleration for embedding generation (if available)
# TODO: Consider caching embeddings to avoid re-encoding unchanged chunks
