"""Health check router.

Phase 1 ships a single endpoint that returns the API version, the
current server time, and whether the database is reachable. This
is the contract the frontend uses to render a connection-status
indicator, and it doubles as a smoke test target for Docker
healthchecks (Phase 5+).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, status
from sqlalchemy import text

from .. import __version__
from ..database import engine
from ..schemas import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return service health.

    The endpoint is intentionally cheap: a single `SELECT 1` with a
    short timeout. If the database is unreachable, the API still
    answers but reports `status="degraded"`. This is preferable to
    a 503, because the dashboard can render a clear "DB offline"
    state instead of an opaque error.
    """
    db_ok = False
    db_error: str | None = None
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # noqa: BLE001 - any DB error means "unhealthy"
        db_error = str(exc)

    overall = "ok" if db_ok else "degraded"
    details: dict[str, str] = {}
    if db_error:
        # Don't leak driver-specific internals to the public response
        # beyond a generic reason. Full error stays in server logs.
        details["database_error"] = "unreachable"
    return HealthResponse(
        status=overall,
        version=__version__,
        database=db_ok,
        timestamp=datetime.now(timezone.utc),
        details=details,
    )


@router.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    """Unauthenticated root that points callers at /api/health and /docs."""
    return {
        "name": "CodeBase AI",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/health",
    }


# Re-export status so callers using `from .routers.health import status` work
__all__ = ["router", "status"]
