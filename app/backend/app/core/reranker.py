"""
Cross-encoder reranker for retrieval quality improvement.

Takes candidate chunks from ChromaDB ANN search and reranks them
using a cross-encoder model that scores query-document pairs directly.
This produces much more accurate relevance ordering than bi-encoder
similarity alone.
"""

import torch
from sentence_transformers import CrossEncoder
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


class Reranker:
    """Rerank retrieval candidates using a cross-encoder model."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """
        Initialize cross-encoder reranker.

        Args:
            model_name: Cross-encoder model from Hugging Face
        """
        self.model_name = model_name

        logger.info(f"Loading reranker model: {model_name}")
        self.model = CrossEncoder(model_name)

        # Move to GPU if available
        if torch.cuda.is_available():
            self.model.model.to(torch.device("cuda"))
            logger.info(f"Reranker loaded on CUDA ({torch.cuda.get_device_name(0)})")
        else:
            logger.info("Reranker loaded on CPU (CUDA not available)")

    def rerank(
        self,
        query: str,
        chunks: List[Dict],
        top_k: int = 10,
    ) -> List[Dict]:
        """
        Rerank chunks by cross-encoder relevance score.

        Args:
            query: User query
            chunks: Candidate chunks from ChromaDB (each has 'text', 'chunk_id', 'metadata', 'distance')
            top_k: Number of top results to return after reranking

        Returns:
            Reranked list of chunks (top_k), with 'rerank_score' added to each
        """
        if not chunks:
            return []

        if len(chunks) <= 1:
            return chunks

        # Build query-document pairs for cross-encoder scoring
        pairs = [(query, chunk["text"]) for chunk in chunks]

        # Score all pairs
        scores = self.model.predict(pairs)

        # Attach scores to chunks
        for i, chunk in enumerate(chunks):
            chunk["rerank_score"] = float(scores[i])

        # Sort by rerank score (higher = more relevant)
        reranked = sorted(chunks, key=lambda c: c["rerank_score"], reverse=True)

        if logger.isEnabledFor(logging.DEBUG):
            for i, chunk in enumerate(reranked[:5]):
                orig_dist = chunk.get("distance", "N/A")
                logger.debug(
                    f"Rerank [{i+1}]: score={chunk['rerank_score']:.3f} "
                    f"orig_dist={orig_dist} "
                    f"file={chunk['metadata'].get('file_basename', '?')}"
                )

        return reranked[:top_k]
