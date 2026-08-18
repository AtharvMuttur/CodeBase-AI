"""Application configuration loaded from environment variables.

We use pydantic-settings so every value is type-checked, defaulted
sensibly, and documented in one place. Provider-agnostic env vars
let Phase 3+ swap LLM / embedding / reranker backends without
code changes — only the .env file changes.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Top-level settings object.

    Environment variables are read from the process environment and,
    when running the backend directly on the host, from a `.env` file
    located next to the backend package.
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- Database ----------
    database_url: str = Field(
        default="postgresql+psycopg://codebase:codebase_dev_password@db:5432/codebase_ai",
        description="SQLAlchemy database URL. Use postgresql+psycopg for sync, +psycopg_asyncpg for async.",
    )

    # ---------- CORS ----------
    frontend_url: str = Field(default="http://localhost:5173")

    # ---------- LLM ----------
    llm_provider: str = Field(default="openai")
    llm_api_key: Optional[str] = Field(default=None)
    llm_model: str = Field(default="gpt-4o-mini")
    llm_base_url: Optional[str] = Field(default=None)

    # ---------- Embeddings ----------
    embedding_provider: str = Field(default="openai")
    embedding_api_key: Optional[str] = Field(default=None)
    embedding_model: str = Field(default="text-embedding-3-small")
    embedding_base_url: Optional[str] = Field(default=None)
    embedding_dimensions: int = Field(default=1536, ge=64, le=4096)

    # ---------- Reranker ----------
    reranker_provider: str = Field(default="cohere")
    reranker_api_key: Optional[str] = Field(default=None)
    reranker_model: Optional[str] = Field(default=None)

    # ---------- GitHub ----------
    github_token: Optional[str] = Field(default=None)

    # ---------- Ingestion limits ----------
    max_repo_size_mb: int = Field(default=200, ge=1)
    max_file_size_kb: int = Field(default=512, ge=1)
    max_files_per_repo: int = Field(default=20_000, ge=1)

    # ---------- Logging ----------
    log_level: str = Field(default="INFO")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance.

    Cached because loading .env and validating every field on every
    request would be wasteful. Tests that need different settings
    should clear the cache with `get_settings.cache_clear()`.
    """
    return Settings()
