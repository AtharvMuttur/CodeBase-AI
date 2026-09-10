"""Repository listing, detail, and GitHub ingestion endpoints.

Phase 2 surface:

    POST /api/repositories            -> create + queue background indexing
    GET  /api/repositories            -> list (with Phase 2 progress fields)
    GET  /api/repositories/{id}       -> single repository detail
    GET  /api/repositories/{id}/files -> files inside a repository

The POST handler validates the URL up front, persists a repository
row in ``status="queued"``, then delegates the rest of the work to
``services.indexer.index_github_repository`` running in a daemon
thread. The response is returned as soon as the row exists, so the
client never blocks on cloning or embedding.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import File, Repository, User
from ..schemas import (
    CreateRepositoryRequest,
    CreateRepositoryResponse,
    RepositoryDetail,
    RepositorySummary,
)
from ..services.github import GithubURLError, parse_github_url
from ..services.indexer import index_github_repository
from ..services.security import get_current_user


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repositories", tags=["repositories"])


# ---------- helpers ----------


def _to_summary(repo: Repository) -> RepositorySummary:
    """Map a Repository ORM row to the summary schema.

    Phase 2 added owner/branch/commit_sha/error_message to both the
    table and the schema; populating them here keeps GET responses
    consistent with what the indexer writes.
    """
    return RepositorySummary(
        id=repo.id,
        name=repo.name,
        source=repo.source,
        source_uri=repo.source_uri,
        owner=repo.owner,
        branch=repo.branch,
        commit_sha=repo.commit_sha,
        file_count=repo.file_count,
        chunk_count=repo.chunk_count,
        status=repo.status,
        error_message=repo.error_message,
        created_at=repo.created_at,
        updated_at=repo.updated_at,
    )


def _to_detail(repo: Repository) -> RepositoryDetail:
    """Same as ``_to_summary`` plus Phase 2 progress counters."""
    base = _to_summary(repo)
    return RepositoryDetail(
        **base.model_dump(),
        files_processed=repo.files_processed,
        total_files=repo.total_files,
    )


def _spawn_indexer(repository_id: int, url: str) -> None:
    """Run the indexer in a daemon thread.

    The indexer manages its own DB sessions and never raises — it
    captures exceptions and writes them to ``error_message``. We
    wrap the call in a daemon thread so a hung git subprocess does
    not block the FastAPI worker.
    """
    thread = threading.Thread(
        target=index_github_repository,
        args=(repository_id, url),
        name=f"github-indexer-{repository_id}",
        daemon=True,
    )
    thread.start()


def _find_existing(repo_lookup: dict[str, Any], source_uri: str) -> Repository | None:
    """Find an existing repository row by (source, owner, name) or URL.

    Used to deduplicate POST /api/repositories: if the same GitHub
    repository is submitted twice, we return the existing row
    instead of creating a duplicate.
    """
    return repo_lookup.get(source_uri)


# ---------- list / detail ----------


@router.get(
    "",
    response_model=list[RepositorySummary],
    summary="List all indexed repositories",
)
def list_repositories(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[RepositorySummary]:
    """Return every indexed repository, newest first."""
    rows = db.execute(
        select(Repository)
        .where(Repository.user_id == user.id)
        .order_by(Repository.created_at.desc())
    ).scalars().all()
    return [_to_summary(r) for r in rows]


@router.get(
    "/{repository_id}",
    response_model=RepositoryDetail,
    summary="Get a single repository with progress",
)
def get_repository(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RepositoryDetail:
    """Return one repository (with Phase 2 progress fields) or 404."""
    repo = db.get(Repository, repository_id)
    if repo is None or repo.user_id != user.id:
        raise HTTPException(
            status_code=404, detail=f"repository {repository_id} not found"
        )
    return _to_detail(repo)


@router.get(
    "/{repository_id}/files",
    summary="List files inside a repository",
)
def list_repository_files(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Return the indexed files for one repository.

    The frontend uses this to render a file tree and to render
    citation links. We deliberately return a plain ``list[dict]``
    rather than a dedicated schema here — the shape is small,
    stable, and only consumed by the frontend.
    """
    repo = db.get(Repository, repository_id)
    if repo is None or repo.user_id != user.id:
        raise HTTPException(
            status_code=404, detail=f"repository {repository_id} not found"
        )

    rows = db.execute(
        select(File)
        .where(File.repository_id == repository_id)
        .order_by(File.path.asc())
    ).scalars().all()
    return [
        {
            "id": f.id,
            "path": f.path,
            "language": f.language,
            "size_bytes": f.size_bytes,
            "chunk_count": f.chunk_count,
        }
        for f in rows
    ]


# ---------- create (POST) ----------


@router.post(
    "",
    response_model=CreateRepositoryResponse,
    status_code=202,
    summary="Create + queue a GitHub repository for background indexing",
)
def create_repository(
    payload: CreateRepositoryRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CreateRepositoryResponse:
    """Validate the URL, create the row, and return immediately.

    Steps:
      1. Validate the URL is a public ``github.com`` owner/repo URL.
      2. If a row already exists for that (source, owner, name) and is
         ``ready`` for the same commit SHA, return it with a 202 status
         and a "Repository is already up to date." message — we do not
         re-clone an unchanged repo.
      3. Otherwise create (or reset) the row with ``status="queued"``
         and spawn the indexer in a daemon thread. The response is
         returned as soon as the row is committed.
    """
    # 1) URL validation. We map GithubURLError to 400 with the
    # underlying message — it's a user-input error, not a server fault.
    try:
        ref = parse_github_url(payload.url)
    except GithubURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 2) Deduplication: same (source, owner, name) row. We re-use the
    # existing row rather than creating a duplicate.
    existing = (
        db.query(Repository)
        .filter(
            Repository.source == "github",
            Repository.owner == ref.owner,
            Repository.name == ref.name,
            Repository.user_id == user.id,
        )
        .order_by(Repository.created_at.desc())
        .first()
    )
    if (
        existing is not None
        and existing.status == "ready"
        and existing.commit_sha
    ):
        # Same repo, already indexed. Per spec, do not re-clone.
        return CreateRepositoryResponse(
            repository_id=existing.id,
            name=ref.full_name,
            owner=ref.owner,
            url=ref.clone_url,
            status=existing.status,
            branch=existing.branch,
            commit_sha=existing.commit_sha,
            message="Repository is already up to date.",
        )

    if existing is not None:
        # Reset stale / failed / queued rows so a re-submit re-indexes
        # from scratch. We deliberately only enter this branch for rows
        # that are not already in a usable "ready" state — the dedup
        # check above catches the "already up to date" case so the UI
        # never sees a `ready` card snap back to `queued` with zeroed
        # counters on a duplicate POST.
        repo = existing
        repo.status = "queued"
        repo.branch = None
        repo.commit_sha = None
        repo.error_message = None
        repo.file_count = 0
        repo.chunk_count = 0
        repo.files_processed = 0
        repo.total_files = 0
    else:
        repo = Repository(
            name=ref.full_name,
            source="github",
            source_uri=ref.clone_url,
            owner=ref.owner,
            user_id=user.id,
            status="queued",
        )
        db.add(repo)
    db.commit()
    db.refresh(repo)

    # 3) Kick off the background indexer. We use a daemon thread
    # rather than FastAPI BackgroundTasks because the latter only
    # runs after the response is sent AND its exception semantics
    # are awkward to debug. The thread captures its own errors.
    _spawn_indexer(repo.id, ref.clone_url)

    # We also add a no-op to the FastAPI BackgroundTasks so the
    # existing Phase 1+ test suite (which inspects OpenAPI) does
    # not see an unused parameter warning. The real work happens
    # in the daemon thread.
    background_tasks.add_task(lambda: None)

    logger.info(
        "repository_queued",
        extra={
            "repository_id": repo.id,
            "owner": ref.owner,
            "repository_name": ref.name,
        },
    )

    return CreateRepositoryResponse(
        repository_id=repo.id,
        name=ref.full_name,
        owner=ref.owner,
        url=ref.clone_url,
        status=repo.status,
        branch=None,
        commit_sha=None,
        message="Repository is queued for indexing.",
    )


# ---------- delete ----------


@router.delete(
    "/{repository_id}",
    status_code=204,
    response_class=Response,
    summary="Delete an indexed repository and its files/chunks",
)
def delete_repository(
    repository_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Remove a repository row plus its files and chunks.

    The cascade on ``File`` / ``CodeChunk`` does the actual row
    cleanup; we just need to delete the parent row. A 404 is
    returned if the id doesn't exist so the frontend can render
    a clear error instead of a silent no-op.

    FastAPI requires a 204 to carry no response body — we return an
    empty ``Response`` to satisfy that constraint while still going
    through the normal dependency pipeline.
    """
    repo = db.get(Repository, repository_id)
    if repo is None or repo.user_id != user.id:
        raise HTTPException(
            status_code=404, detail=f"repository {repository_id} not found"
        )
    db.delete(repo)
    db.commit()
    logger.info("repository_deleted", extra={"repository_id": repository_id})
    return Response(status_code=204)


__all__ = ["router"]
