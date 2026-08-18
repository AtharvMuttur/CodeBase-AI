"""End-to-end ingestion orchestrator.

Walks a local folder, chunks every source file, embeds the chunks,
and persists ``Repository``, ``File``, and ``CodeChunk`` rows in a
single transaction. The router layer calls this and returns the
counts to the client.

Phase 1 keeps this synchronous and in-process — for the MVP we
process a repo in one shot and return. Phase 2+ will move this to
a background task with progress streaming.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import CodeChunk, File, Repository
from .embeddings import embed_texts
from .ingestion import chunk_text, discover_files


logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    repository_id: int
    file_count: int
    chunk_count: int
    skipped_files: int
    elapsed_seconds: float


class IngestionError(RuntimeError):
    """Raised when ingestion cannot proceed."""


def ingest_local_path(
    session: Session,
    *,
    name: str,
    local_path: str,
    repository_id: int | None = None,
    source: str = "local",
) -> IngestionResult:
    """Index ``local_path`` into the database.

    Steps:
      1. Discover source files (extension + size filtered).
      2. For each file: read text, chunk, embed, upsert.
      3. Update repository counters.

    ``repository_id`` reuses an existing row (Phase 2: the GitHub row
    already created by ``POST /api/repositories``). ``source`` records
    the row's origin and is preserved when reusing an existing row.
    """
    settings = get_settings()
    root = Path(local_path).expanduser().resolve()

    if not root.exists():
        raise IngestionError(f"path does not exist: {local_path}")
    if not root.is_dir():
        raise IngestionError(f"path is not a directory: {local_path}")

    started = time.perf_counter()

    discovered = discover_files(
        root,
        max_file_size_kb=settings.max_file_size_kb,
        max_files=settings.max_files_per_repo,
    )

    # Reuse the existing row (Phase 2) or create a fresh one (Phase 1).
    if repository_id is not None:
        repo = session.get(Repository, repository_id)
        if repo is None:
            raise IngestionError(f"repository {repository_id} not found")
        # Clear any previously indexed files/chunks so a re-index
        # replaces (rather than appends to) the existing data.
        session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).delete()
        session.query(File).filter(File.repository_id == repo.id).delete()
        session.flush()
        repo.name = name
        repo.source = source
        repo.source_uri = str(root)
        repo.status = "indexing"
        repo.error_message = None
    else:
        repo = Repository(
            name=name,
            source=source,
            source_uri=str(root),
            status="indexing",
        )
        session.add(repo)
    session.flush()  # populate repo.id

    total_chunks = 0
    skipped = 0
    embed_failures = 0
    embedable_files = 0  # files that reached the embed step

    for entry in discovered:
        try:
            text_content = entry.absolute_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            skipped += 1
            continue
        if not text_content.strip():
            # Skip empty files — they contribute no signal to retrieval.
            continue

        chunks = chunk_text(text_content)
        if not chunks:
            continue

        # Upsert the file row so re-ingestion of the same folder is idempotent.
        file_row = (
            session.query(File)
            .filter(File.repository_id == repo.id, File.path == entry.relative_path)
            .one_or_none()
        )
        if file_row is None:
            file_row = File(
                repository_id=repo.id,
                path=entry.relative_path,
                language=entry.language,
                size_bytes=entry.size_bytes,
            )
            session.add(file_row)
            session.flush()
        else:
            file_row.language = entry.language
            file_row.size_bytes = entry.size_bytes

        # Delete previous chunks for this file — simpler than diffing
        # content_hash for the MVP and still cheap at small scale.
        session.query(CodeChunk).filter(CodeChunk.file_id == file_row.id).delete()
        session.flush()

        # Embed in one batch per file. embed_texts() handles the
        # provider switch (real API vs hashed local fallback).
        embedable_files += 1
        try:
            vectors = embed_texts([c.content for c in chunks])
        except Exception as exc:
            embed_failures += 1
            skipped += 1
            # If the embedding backend is misconfigured (e.g. an
            # invalid Gemini key) every file will fail and the row
            # would otherwise be marked "ready" with 0 chunks —
            # indistinguishable from an empty repo. Log the first
            # failure so the operator can see what went wrong; the
            # systemic check after the loop promotes "all failures"
            # to a hard error on the repository row.
            if embed_failures == 1:
                logger.warning(
                    "ingest_embed_failed",
                    extra={
                        "repository_id": repo.id,
                        "file": entry.relative_path,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            # Keep going with the rest of the repo — one bad file
            # shouldn't abort the whole ingestion on its own.
            continue

        for chunk, vec in zip(chunks, vectors):
            session.add(
                CodeChunk(
                    repository_id=repo.id,
                    file_id=file_row.id,
                    chunk_index=chunk.chunk_index,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    embedding=vec.tolist(),
                    chunk_metadata=dict(chunk.metadata),
                )
            )

        file_row.chunk_count = len(chunks)
        total_chunks += len(chunks)
        # Update Phase 2 progress fields as we go so the frontend
        # can show a live counter while indexing is still in flight.
        repo.files_processed = repo.files_processed + 1
        repo.total_files = len(discovered)

    # Systemic embedding check: if every file that had content also
    # failed at the embed step, the repository row would otherwise be
    # marked "ready" with 0 chunks and the operator would have no
    # signal that the embedding backend is misconfigured (e.g. a bad
    # Gemini key, blocked outbound network). Promote that case to a
    # hard error so the row lands in "failed" with an actionable
    # error_message. Partial failures (some files embedded, some
    # didn't) still commit as a "ready" row with the succeeded files.
    if embedable_files > 0 and embed_failures == embedable_files:
        session.rollback()
        raise IngestionError(
            f"embedding failed for every file in the repository "
            f"({embed_failures}/{embedable_files}); check the "
            f"configured EMBEDDING_API_KEY / EMBEDDING_PROVIDER "
            f"and backend logs for the first failure."
        )

    repo.file_count = len(discovered) - skipped
    repo.chunk_count = total_chunks
    repo.status = "ready"
    repo.error_message = None
    session.commit()

    return IngestionResult(
        repository_id=repo.id,
        file_count=repo.file_count,
        chunk_count=repo.chunk_count,
        skipped_files=skipped,
        elapsed_seconds=time.perf_counter() - started,
    )


__all__ = ["ingest_local_path", "IngestionResult", "IngestionError"]
