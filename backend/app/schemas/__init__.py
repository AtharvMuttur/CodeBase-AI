"""Pydantic schemas (request and response models) for the API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------- Authentication ----------


class AuthRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: int
    email: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ---------- Health ----------


class HealthResponse(BaseModel):
    """Response shape for GET /api/health.

    `status` is `"ok"` when the API and database are reachable,
    `"degraded"` when the API is up but the database is not, and
    `"error"` when something else is wrong.
    """

    status: str = Field(..., description="ok | degraded | error")
    version: str
    database: bool
    timestamp: datetime
    details: dict[str, Any] = Field(default_factory=dict)


# ---------- Ingestion ----------


class IngestRequest(BaseModel):
    """Request body for POST /api/ingest.

    For Phase 1 only ``local_path`` is supported. The path must be
    accessible from the backend process — inside Docker that means
    mounting it into the container (see README).
    """

    name: str = Field(..., min_length=1, max_length=200)
    local_path: str = Field(..., min_length=1, description="Absolute path to a local folder")


class IngestResponse(BaseModel):
    """Response shape for POST /api/ingest."""

    repository_id: int
    name: str
    status: str
    file_count: int
    chunk_count: int
    skipped_files: int
    elapsed_seconds: float
    message: str = "ingestion complete"


class RepositorySummary(BaseModel):
    """Compact representation of a repository, used by list endpoints."""

    id: int
    name: str
    source: str
    source_uri: str | None
    owner: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    file_count: int
    chunk_count: int
    status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class RepositoryDetail(RepositorySummary):
    """Detailed view of a single repository.

    Extends the summary with progress fields used by the Phase 2
    background indexer. The frontend polls this endpoint while a
    GitHub repository is being indexed.
    """

    files_processed: int = 0
    total_files: int = 0


class CreateRepositoryRequest(BaseModel):
    """Request body for POST /api/repositories.

    The only supported source in Phase 2 is a public GitHub URL.
    The endpoint validates the URL, extracts owner/repo, and starts
    a background indexer. It does not block on indexing — the
    response is returned as soon as the row is created.
    """

    url: str = Field(..., min_length=1, description="Public GitHub repository URL")


class CreateRepositoryResponse(BaseModel):
    """Response shape for POST /api/repositories.

    Returned as soon as the repository row is created (or its
    status was determined to be already-up-to-date). The frontend
    should poll ``GET /api/repositories/{id}`` to observe progress.
    """

    repository_id: int
    name: str
    owner: str
    url: str
    status: str
    branch: str | None = None
    commit_sha: str | None = None
    message: str | None = None


# ---------- Query ----------


class QueryRequest(BaseModel):
    """Request body for POST /api/query."""

    question: str = Field(..., min_length=1)
    repository_id: int | None = Field(
        default=None,
        description="Restrict search to a single repository. If omitted, all repos are searched.",
    )
    top_k: int = Field(default=5, ge=1, le=20)


class ChunkCitation(BaseModel):
    """One retrieved chunk, returned as part of a QueryResponse."""

    chunk_id: int
    file_id: int
    file_path: str
    language: str | None
    start_line: int
    end_line: int
    content: str
    score: float


class QueryResponse(BaseModel):
    """Response shape for POST /api/query."""

    answer: str
    chunks: list[ChunkCitation]
    model: str
    repository_id: int | None


__all__ = [
    "HealthResponse",
    "AuthRequest",
    "UserResponse",
    "AuthResponse",
    "IngestRequest",
    "IngestResponse",
    "RepositorySummary",
    "RepositoryDetail",
    "CreateRepositoryRequest",
    "CreateRepositoryResponse",
    "QueryRequest",
    "ChunkCitation",
    "QueryResponse",
]
