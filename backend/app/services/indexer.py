"""Background indexer for GitHub repositories.

This module bridges the GitHub clone layer with the Phase 1
``ingest_local_path`` pipeline. It runs in a daemon thread spawned
by ``routers/repositories.create_repository`` and is responsible for:

1. Validating the URL.
2. Updating the ``repositories.status`` column at every transition so
   the frontend can poll ``GET /api/repositories/{id}`` for progress.
3. Cloning to a temp directory.
4. Reusing ``services.pipeline.ingest_local_path`` on the cloned tree.
5. Cleaning up the temp directory.
6. Marking the row ``"ready"`` (or ``"failed"`` with ``error_message``).

The pipeline is reused unmodified — Phase 1 is the canonical ingestion
path. We are just feeding it a different local path.
"""
from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path

from ..config import get_settings
from ..database import SessionLocal
from ..models import Repository
from .github import (
    GithubURLError,
    clone_to_temp,
    default_branch,
    parse_github_url,
    remove_temp,
)
from .pipeline import IngestionError, ingest_local_path


logger = logging.getLogger(__name__)


def _truncate(message: str, limit: int = 500) -> str:
    """Keep the on-disk error message bounded so a 10 MB stack trace
    doesn't poison the row."""
    msg = (message or "").strip().replace("\r", " ")
    if len(msg) <= limit:
        return msg
    return msg[: limit - 3] + "..."


def _update_status(
    repository_id: int,
    *,
    status: str | None = None,
    error_message: str | None = None,
    clear_error: bool = False,
    branch: str | None = None,
    commit_sha: str | None = None,
    files_processed: int | None = None,
    total_files: int | None = None,
    file_count: int | None = None,
    chunk_count: int | None = None,
) -> None:
    """Update one repositories row. Commits immediately so the next
    GET observes the new state.

    Each call opens its own short-lived session because this runs in
    a background thread with no FastAPI request lifecycle in scope.
    """
    session = SessionLocal()
    try:
        repo = session.get(Repository, repository_id)
        if repo is None:
            logger.warning(
                "indexer_update_missing_repo",
                extra={"repository_id": repository_id, "status": status},
            )
            return
        if status is not None:
            repo.status = status
        if branch is not None:
            repo.branch = branch
        if commit_sha is not None:
            repo.commit_sha = commit_sha
        if files_processed is not None:
            repo.files_processed = files_processed
        if total_files is not None:
            repo.total_files = total_files
        if file_count is not None:
            repo.file_count = file_count
        if chunk_count is not None:
            repo.chunk_count = chunk_count
        if error_message is not None:
            repo.error_message = error_message
        elif clear_error:
            repo.error_message = None
        session.commit()
    except Exception:  # noqa: BLE001 — log and swallow
        session.rollback()
        logger.exception(
            "indexer_update_failed",
            extra={"repository_id": repository_id, "status": status},
        )
    finally:
        session.close()


def index_github_repository(
    repository_id: int,
    url: str,
    github_token: str | None = None,
) -> None:
    """End-to-end indexer. Runs in a daemon thread.

    Safe to call multiple times for the same ``repository_id`` — the
    new attempt resets the counters and status, then walks through
    the transitions. If a previous attempt is still running it will
    keep writing to the row until it completes; whichever commit
    lands last wins, but the final state is always ``"ready"`` or
    ``"failed"`` because both branches terminate with an update.
    """
    started = time.perf_counter()
    settings = get_settings()
    token = github_token or settings.github_token or None

    # Reset counters up front so the frontend immediately sees the
    # row in "queued" state with progress zeroed.
    _update_status(
        repository_id,
        status="queued",
        files_processed=0,
        total_files=0,
        file_count=0,
        chunk_count=0,
        clear_error=True,
    )
    logger.info(
        "indexer_start",
        extra={
            "repository_id": repository_id,
            "url": url,
            "github_token_supplied": bool(token),
        },
    )

    temp_path: Path | None = None
    try:
        # 1) Validate URL
        try:
            ref = parse_github_url(url)
        except GithubURLError as exc:
            _update_status(
                repository_id, status="failed", error_message=str(exc)
            )
            return

        # 2) Discover the default branch.
        _update_status(repository_id, status="checking_access")
        try:
            branch = default_branch(ref, token=token)
        except GithubURLError as exc:
            _update_status(
                repository_id, status="failed", error_message=str(exc)
            )
            return

        # 3) Clone.
        _update_status(repository_id, status="cloning")
        try:
            temp_path, commit_sha = clone_to_temp(ref, branch=branch, token=token)
        except GithubURLError as exc:
            _update_status(
                repository_id, status="failed", error_message=str(exc)
            )
            return
        except Exception as exc:  # noqa: BLE001
            _update_status(
                repository_id,
                status="failed",
                error_message=_truncate(f"clone failed: {exc}"),
            )
            return

        _update_status(
            repository_id,
            status="scanning",
            branch=branch,
            commit_sha=commit_sha,
        )

        # 4) Run the Phase 1 pipeline on the cloned tree.
        session = SessionLocal()
        try:
            try:
                # Promote status to "chunking" right before delegating;
                # the pipeline will overwrite status="ready" on success.
                _update_status(repository_id, status="chunking")

                # Embedding is the longest step — the local fallback
                # is fast, but a real embedding API can take a while
                # for medium-size repos.
                _update_status(repository_id, status="embedding")

                result = ingest_local_path(
                    session,
                    name=ref.full_name,
                    local_path=str(temp_path),
                    repository_id=repository_id,
                    source="github",
                    progress_callback=lambda processed, total: _update_status(
                        repository_id,
                        status="embedding",
                        files_processed=processed,
                        total_files=total,
                    ),
                )
            except IngestionError as exc:
                _update_status(
                    repository_id,
                    status="failed",
                    error_message=f"ingestion error: {exc}",
                )
                return
            except Exception as exc:  # noqa: BLE001
                _update_status(
                    repository_id,
                    status="failed",
                    error_message=_truncate(
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
                logger.exception(
                    "indexer_pipeline_failed",
                    extra={"repository_id": repository_id},
                )
                return
        finally:
            try:
                session.close()
            except Exception:
                pass

        # 5) Pipeline returned successfully — finalise the row.
        _update_status(
            repository_id,
            status="ready",
            file_count=result.file_count,
            chunk_count=result.chunk_count,
            files_processed=result.file_count,
            total_files=result.file_count,
            clear_error=True,
        )
    except Exception as exc:  # noqa: BLE001 — last-resort safety net
        logger.exception(
            "indexer_unhandled",
            extra={"repository_id": repository_id},
        )
        _update_status(
            repository_id,
            status="failed",
            error_message=_truncate(
                f"unhandled {type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            ),
        )
    finally:
        if temp_path is not None:
            remove_temp(temp_path)
        elapsed = time.perf_counter() - started
        logger.info(
            "indexer_done",
            extra={
                "repository_id": repository_id,
                "elapsed_s": round(elapsed, 2),
            },
        )


__all__ = ["index_github_repository"]
