"""Application configuration module.

This module centralises environment configuration using pydantic's
``BaseSettings``.  The settings object is imported by both the FastAPI
application and background workers so that configuration is consistent
across processes.
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

try:
    from pydantic_settings import BaseSettings
except ImportError:  # pragma: no cover - fallback for Pydantic v1 environments
    from pydantic import BaseSettings  # type: ignore

from pydantic import Field, HttpUrl


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    os_url: HttpUrl = Field(
        default="http://opensearch:9200",
        description="Base URL of the OpenSearch cluster.",
    )
    redis_url: str = Field(
        default="redis://redis:6379/0",
        description="Redis connection string used by Celery.",
    )
    ollama_url: HttpUrl = Field(
        default="http://ollama:11434",
        description="Base URL of the Ollama instance providing embeddings.",
    )
    ollama_embed_model: str = Field(
        default="nomic-embed-text",
        description="Default embedding model served by Ollama.",
    )
    index_name: str = Field(
        default="docs_chunks_v1",
        description="Primary OpenSearch index for chunk documents.",
    )
    max_crawl_depth: int = Field(default=3, ge=0)
    max_crawl_pages: int = Field(default=800, ge=1)
    rate_limit_per_sec: float = Field(default=1.0, ge=0.1)
    allow_subdomains: bool = Field(default=True)
    same_domain_only: bool = Field(default=True)
    default_embedding_dims: int = Field(
        default=768,
        description="Fallback embedding dimensionality when Ollama detection fails.",
    )
    bm25_top_n: int = Field(default=200, ge=1)
    vector_top_n: int = Field(default=200, ge=1)
    rrf_k: int = Field(default=60, ge=1)
    query_top_k: int = Field(default=8, ge=1)
    enable_reranker: bool = Field(default=False)
    allowed_origins: List[str] = Field(default_factory=list)
    api_key: Optional[str] = Field(
        default=None,
        description="Optional static API key for simple authn.",
    )
    gemini_api_key: Optional[str] = Field(
        default=None,
        description="Optional Gemini API key used when integrating a generation model.",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="LLM model identifier used for answer generation.",
    )
    upload_dir: Path = Field(
        default=Path("/data/uploads"),
        description="Directory where uploaded files are stored for ingestion.",
    )
    http_timeout: float = Field(
        default=10.0,
        description="Default HTTP timeout in seconds for downstream calls.",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance.

    Using ``lru_cache`` keeps configuration loading inexpensive while still
    allowing tests to override environment variables by clearing the cache.
    """

    return Settings()


settings = get_settings()
