"""
Centralized service singletons.

All heavyweight services (LLM, Embedder, Indexer, Reranker, QueryExpander)
are initialized once here and shared across the entire application.  This
prevents duplicate GPU model loads (health.py vs query.py VRAM conflict)
and redundant ChromaDB connections.

Usage:
    from ..services import get_llm_client, get_indexer, get_embedder
"""

import logging

from .config import settings
from .core.embedder import Embedder
from .core.indexer import Indexer
from .core.llm_client import LLMClient
from .core.reranker import Reranker
from .core.query_expander import QueryExpander
from .core.directory_index import DirectoryIndex

logger = logging.getLogger(__name__)

_llm_client = None
_indexer = None
_embedder = None
_reranker = None
_query_expander = None
_directory_index = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(settings.get_legacy_config_dict())
        logger.info("Initialized shared LLMClient singleton")
    return _llm_client


def get_indexer() -> Indexer:
    global _indexer
    if _indexer is None:
        _indexer = Indexer(chroma_db_path=settings.chroma_db_path)
        logger.info("Initialized shared Indexer singleton")
    return _indexer


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder(
            model_name=settings.embedding_model_name,
            batch_size=settings.embedding_batch_size,
        )
        logger.info("Initialized shared Embedder singleton")
    return _embedder


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
        logger.info("Initialized shared Reranker singleton")
    return _reranker


def get_query_expander() -> QueryExpander:
    global _query_expander
    if _query_expander is None:
        _query_expander = QueryExpander()
        logger.info("Initialized shared QueryExpander singleton")
    return _query_expander


from typing import Optional


def get_directory_index() -> Optional[DirectoryIndex]:
    """Get directory index singleton. Returns None if no drives configured."""
    global _directory_index
    if _directory_index is None:
        if not settings.network_drives_config:
            return None
        _directory_index = DirectoryIndex(
            db_path=str(settings.directory_index_db_path),
            drives=settings.network_drives_config,
        )
        _directory_index.initialize()
        logger.info("Initialized DirectoryIndex singleton")
    return _directory_index

