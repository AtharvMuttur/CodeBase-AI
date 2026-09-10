"""Repository ingestion router.

Phase 1 ships a single endpoint:

    POST /api/ingest
        body: { name, local_path }
        returns: repository id + file/chunk counts

The handler delegates all the work to ``services.pipeline.ingest_local_path``.
Validation errors raise ``HTTPException(400)``; the orchestrator raises
``IngestionError`` for bad paths, which the router also maps to 400.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import IngestRequest, IngestResponse
from ..services.security import get_current_user
from ..services.pipeline import IngestionError, ingest_local_path


router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post(
    "",
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Index a local repository folder",
)
def ingest_repository(
    payload: IngestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IngestResponse:
    """Walk ``payload.local_path``, chunk every source file, embed,
    and persist rows in pgvector.
    """
    try:
        result = ingest_local_path(
            db,
            name=payload.name,
            local_path=payload.local_path,
            user_id=user.id,
        )
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface anything else as 500
        raise HTTPException(status_code=500, detail=f"ingestion failed: {exc}") from exc

    return IngestResponse(
        repository_id=result.repository_id,
        name=payload.name,
        status="ready",
        file_count=result.file_count,
        chunk_count=result.chunk_count,
        skipped_files=result.skipped_files,
        elapsed_seconds=round(result.elapsed_seconds, 2),
    )


__all__ = ["router"]
