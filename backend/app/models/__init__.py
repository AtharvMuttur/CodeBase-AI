"""SQLAlchemy ORM models for Phase 1 + Phase 2.

Three tables are enough for an MVP RAG pipeline:

* ``Repository``  — one row per indexed project.
* ``File``        — one row per source file inside a repository.
* ``CodeChunk``   — one row per chunked, embedded piece of a file.

Vector storage lives on ``CodeChunk.embedding`` (pgvector ``vector``).
The dimension is fixed at 768 (Gemini ``text-embedding-004``) but the
actual size is a deployment decision — adjust the SQL init script
when you switch embedding models.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


EMBEDDING_DIMENSIONS = 768


# SQLite needs INTEGER PRIMARY KEY for ROWID-backed autoincrement.
# BIGINT (BIGSERIAL) works on Postgres but fails on SQLite because the
# NotNull constraint blocks default-PK generation. Use a dialect-aware
# BigInteger for primary keys; foreign keys stay BIGINT (Postgres).
BigInt = BigInteger().with_variant(Integer, "sqlite")


# Possible values for ``Repository.status``. Kept as a Python set so the
# routers/services can validate transitions cheaply; the database
# column itself is plain ``Text`` (a true enum constraint would force
# an Alembic migration for every new state).
REPO_STATUSES: frozenset[str] = frozenset(
    {"queued", "cloning", "scanning", "chunking", "embedding", "storing", "ready", "failed"}
)


class Repository(Base):
    """An indexed codebase — a local folder in Phase 1, a GitHub URL in Phase 2.

    ``source`` describes how the repo was loaded: ``"local"`` for paths
    ingested via the existing ``POST /api/ingest`` endpoint, ``"github"``
    for repositories cloned from GitHub via ``POST /api/repositories``.
    ``source_uri`` is the path for local repos and the GitHub URL for
    remote ones.

    GitHub-specific metadata (``owner``, ``branch``, ``commit_sha``)
    is nullable so local-folder rows created in Phase 1 continue to
    work. Progress fields (``files_processed``, ``total_files``,
    ``chunks_created``) are kept in sync by the background indexer so
    the frontend can render a live progress bar without polling the
    full repo list.
    """

    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    files: Mapped[list["File"]] = relationship(
        "File", back_populates="repository", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["CodeChunk"]] = relationship(
        "CodeChunk", back_populates="repository", cascade="all, delete-orphan"
    )


class File(Base):
    """A source file inside a repository.

    ``path`` is repo-relative and uses forward slashes so the same
    file works on Windows hosts and Linux containers.
    """

    __tablename__ = "files"
    __table_args__ = (UniqueConstraint("repository_id", "path", name="uq_files_repo_path"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(
        BigInt,
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    repository: Mapped[Repository] = relationship("Repository", back_populates="files")
    chunks: Mapped[list["CodeChunk"]] = relationship(
        "CodeChunk", back_populates="file", cascade="all, delete-orphan"
    )


class CodeChunk(Base):
    """A chunk of source code with its embedding.

    ``content_hash`` is the sha256 of ``content`` and is unique per
    file so re-ingesting the same file is idempotent at the chunk
    level (the row is replaced in place on conflict).
    """

    __tablename__ = "code_chunks"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(
        BigInt,
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[int] = mapped_column(
        BigInt,
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    repository: Mapped[Repository] = relationship("Repository", back_populates="chunks")
    file: Mapped[File] = relationship("File", back_populates="chunks")


__all__ = ["Repository", "File", "CodeChunk", "EMBEDDING_DIMENSIONS", "REPO_STATUSES"]
