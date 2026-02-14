"""
Centralized configuration module.

Loads config.yaml once at import time. All paths are resolved relative
to a base directory (AAA_BASE_DIR env var, defaults to project root).
Environment variables with AAA_ prefix override any config.yaml value.

Usage:
    from app.config import settings
    print(settings.model_path)
    print(settings.raw_docs_dir)
"""

from pathlib import Path
from typing import Optional
from functools import lru_cache
import os
import yaml
import logging

from pydantic_settings import BaseSettings
from pydantic import Field, model_validator

logger = logging.getLogger(__name__)

# Project root: four levels up from this file (app/backend/app/config.py -> project root)
_DEFAULT_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


def _load_yaml_config(base_dir: Path) -> dict:
    """Load config.yaml and return as flat dict.

    Search order:
    1. CONFIG_PATH env var (set by docker-compose)
    2. <base_dir>/app/backend/config.yaml (standard repo layout)
    3. <base_dir>/config.yaml (flat layout, e.g. inside Docker container)
    """
    # Check explicit CONFIG_PATH env var first (Docker support)
    env_config = os.environ.get("CONFIG_PATH")
    if env_config:
        config_path = Path(env_config)
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f) or {}

    # Standard repo layout
    config_path = base_dir / "app" / "backend" / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}

    # Flat layout fallback (e.g. Docker WORKDIR)
    alt_path = Path(__file__).resolve().parent.parent / "config.yaml"
    if alt_path.exists():
        with open(alt_path) as f:
            return yaml.safe_load(f) or {}

    logger.warning(f"config.yaml not found at {config_path}, using defaults")
    return {}


class Settings(BaseSettings):
    """Application settings with env var overrides.

    Environment variables use AAA_ prefix:
        AAA_BASE_DIR=/opt/aaa
        AAA_MODEL_PATH=data/models/my-model.gguf
        AAA_DB_USERNAME=user
        AAA_DB_PASSWORD=secret
    """

    # Base directory (all relative paths resolved from here)
    base_dir: Path = Field(default=_DEFAULT_BASE_DIR)

    # --- Model ---
    model_path: str = "data/models/Meta-Llama-3.1-8B-Instruct-Q6_K.gguf"
    model_n_gpu_layers: int = 40
    model_n_threads: int = 8
    model_max_tokens: int = 1024
    model_temperature: float = 0.0
    model_n_ctx: int = 8192

    # --- Embedding ---
    embedding_model_name: str = "nomic-ai/nomic-embed-text-v1.5"
    embedding_batch_size: int = 32

    # --- Paths (relative to base_dir) ---
    raw_docs_dir: str = "data/raw_docs"
    ocr_dir: str = "data/ocr"
    text_dir: str = "data/text"
    chunks_dir: str = "data/chunks"
    embeddings_dir: str = "data/embeddings"
    chroma_db_dir: str = "data/index/chroma"

    # --- Logging ---
    queries_log: str = "data/logs/queries.log"
    ingest_report: str = "data/logs/ingest_report.json"
    errors_log: str = "data/logs/errors.log"
    debug_mode: bool = False

    # --- OCR ---
    ocr_use_tesseract: bool = True
    ocr_tesseract_lang: str = "eng"
    ocr_min_text_length: int = 100

    # --- Chunking ---
    chunking_semantic: bool = False
    chunking_chunk_size_tokens: int = 500
    chunking_chunk_overlap_tokens: int = 100

    # --- Index ---
    index_top_k: int = 6
    index_similarity_threshold: float = 0.5

    # --- Database (from env vars only, not config.yaml) ---
    db_dsn: str = ""
    db_username: str = ""
    db_password: str = ""

    # --- Data files ---
    ajera_data_path: str = "data/ajera_unified.json"
    project_lookup_path: str = "data/mappings/project_lookup.csv"

    # --- Security ---
    api_key: str = ""  # Empty = no auth (dev mode)
    frontend_url: str = "http://localhost:5173"

    model_config = {
        "env_prefix": "AAA_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="before")
    @classmethod
    def load_from_yaml(cls, data: dict) -> dict:
        """Load values from config.yaml as defaults, env vars override."""
        base_dir = Path(data.get("base_dir", data.get("AAA_BASE_DIR", _DEFAULT_BASE_DIR)))
        yaml_config = _load_yaml_config(base_dir)

        if not yaml_config:
            return data

        # Map yaml nested keys to flat settings keys (only set if not already in data)
        yaml_mapping = {
            # model
            "model_path": ("model", "path"),
            "model_n_gpu_layers": ("model", "n_gpu_layers"),
            "model_n_threads": ("model", "n_threads"),
            "model_max_tokens": ("model", "max_tokens"),
            "model_temperature": ("model", "temperature"),
            "model_n_ctx": ("model", "n_ctx"),
            # embedding
            "embedding_model_name": ("embedding", "model_name"),
            "embedding_batch_size": ("embedding", "batch_size"),
            # paths
            "raw_docs_dir": ("paths", "raw_docs"),
            "ocr_dir": ("paths", "ocr"),
            "text_dir": ("paths", "text"),
            "chunks_dir": ("paths", "chunks"),
            "embeddings_dir": ("paths", "embeddings"),
            "chroma_db_dir": ("paths", "chroma_db"),
            # logging
            "queries_log": ("logging", "queries_log"),
            "ingest_report": ("logging", "ingest_report"),
            "errors_log": ("logging", "errors_log"),
            "debug_mode": ("logging", "debug_mode"),
            # ocr
            "ocr_use_tesseract": ("ocr", "use_tesseract"),
            "ocr_tesseract_lang": ("ocr", "tesseract_lang"),
            "ocr_min_text_length": ("ocr", "min_text_length"),
            # chunking
            "chunking_semantic": ("chunking", "semantic"),
            "chunking_chunk_size_tokens": ("chunking", "chunk_size_tokens"),
            "chunking_chunk_overlap_tokens": ("chunking", "chunk_overlap_tokens"),
            # index
            "index_top_k": ("index", "top_k"),
            "index_similarity_threshold": ("index", "similarity_threshold"),
            # database
            "db_dsn": ("database", "dsn"),
            "db_username": ("database", "username"),
            "db_password": ("database", "password"),
        }

        for settings_key, yaml_path in yaml_mapping.items():
            if settings_key in data:
                continue  # env var already set, takes precedence
            # Traverse yaml nested dict
            val = yaml_config
            for key in yaml_path:
                if isinstance(val, dict):
                    val = val.get(key)
                else:
                    val = None
                    break
            if val is not None:
                data[settings_key] = val

        return data

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a path relative to base_dir.

        If the path is already absolute, return it as-is.
        Otherwise, resolve relative to base_dir.
        """
        p = Path(relative_path)
        if p.is_absolute():
            return p
        return self.base_dir / p

    # --- Convenience properties for resolved absolute paths ---

    @property
    def model_path_resolved(self) -> Path:
        return self.resolve_path(self.model_path)

    @property
    def raw_docs_path(self) -> Path:
        return self.resolve_path(self.raw_docs_dir)

    @property
    def ocr_path(self) -> Path:
        return self.resolve_path(self.ocr_dir)

    @property
    def text_path(self) -> Path:
        return self.resolve_path(self.text_dir)

    @property
    def chunks_path(self) -> Path:
        return self.resolve_path(self.chunks_dir)

    @property
    def embeddings_path(self) -> Path:
        return self.resolve_path(self.embeddings_dir)

    @property
    def chroma_db_path(self) -> Path:
        return self.resolve_path(self.chroma_db_dir)

    @property
    def queries_log_path(self) -> Path:
        return self.resolve_path(self.queries_log)

    @property
    def ingest_report_path(self) -> Path:
        return self.resolve_path(self.ingest_report)

    @property
    def errors_log_path(self) -> Path:
        return self.resolve_path(self.errors_log)

    @property
    def ajera_data_path_resolved(self) -> Path:
        return self.resolve_path(self.ajera_data_path)

    @property
    def project_lookup_path_resolved(self) -> Path:
        return self.resolve_path(self.project_lookup_path)

    @property
    def prompts_dir(self) -> Path:
        # Resolve relative to this module — works in both repo layout and Docker
        return Path(__file__).resolve().parent / "prompts"

    def get_legacy_config_dict(self) -> dict:
        """Return a dict matching the old config.yaml structure.

        Use this for gradual migration — modules that still expect
        the old config dict can call this.
        """
        return {
            "model": {
                "path": str(self.model_path_resolved),
                "n_gpu_layers": self.model_n_gpu_layers,
                "n_threads": self.model_n_threads,
                "max_tokens": self.model_max_tokens,
                "temperature": self.model_temperature,
                "n_ctx": self.model_n_ctx,
            },
            "embedding": {
                "model_name": self.embedding_model_name,
                "batch_size": self.embedding_batch_size,
            },
            "paths": {
                "raw_docs": str(self.raw_docs_path),
                "ocr": str(self.ocr_path),
                "text": str(self.text_path),
                "chunks": str(self.chunks_path),
                "embeddings": str(self.embeddings_path),
                "chroma_db": str(self.chroma_db_path),
            },
            "logging": {
                "queries_log": str(self.queries_log_path),
                "ingest_report": str(self.ingest_report_path),
                "errors_log": str(self.errors_log_path),
                "debug_mode": self.debug_mode,
            },
            "ocr": {
                "use_tesseract": self.ocr_use_tesseract,
                "tesseract_lang": self.ocr_tesseract_lang,
                "min_text_length": self.ocr_min_text_length,
            },
            "chunking": {
                "semantic": self.chunking_semantic,
                "chunk_size_tokens": self.chunking_chunk_size_tokens,
                "chunk_overlap_tokens": self.chunking_chunk_overlap_tokens,
            },
            "index": {
                "top_k": self.index_top_k,
                "similarity_threshold": self.index_similarity_threshold,
            },
            "database": {
                "dsn": self.db_dsn,
                "username": self.db_username,
                "password": self.db_password,
            },
        }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings singleton."""
    return Settings()


# Module-level singleton for convenience imports
settings = get_settings()
