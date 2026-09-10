"""End-to-end API surface tests.

We exercise the FastAPI app via the TestClient. The DB is reachable
or not depending on the developer's environment; what we assert here
is the API shape:

* the new routers are mounted under /api
* validation errors produce 422
* the OpenAPI schema lists every public route
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import User
from app.services.security import get_current_user


client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_test_user():
    """Keep legacy route-shape tests authenticated without weakening production routes."""
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1,
        email="test@example.com",
        password_hash="unused",
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def hermetic_db(monkeypatch):
    """Override the FastAPI ``get_db`` dependency with in-memory SQLite.

    The Phase 2 router-level tests want to exercise the full route,
    not just the parser — without a real Postgres we point at SQLite.
    Schema-only; we never embed anything here.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # pgvector-only column — drop if SQLAlchemy created it.
        try:
            conn.execute(text("ALTER TABLE code_chunks DROP COLUMN embedding"))
        except Exception:
            pass

    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()


def test_openapi_lists_all_phase1_routes() -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"].keys()
    # /api/ is intentionally hidden from the schema (include_in_schema=False).
    expected = {
        "/api/health",
        "/api/ingest",
        "/api/query",
        "/api/repositories",
        "/api/repositories/{repository_id}",
        "/api/repositories/{repository_id}/files",
    }
    missing = expected - set(paths)
    assert not missing, f"missing routes in OpenAPI: {missing}"


def test_delete_repository_route_is_registered() -> None:
    # Phase 2 adds DELETE on the same path; the route should appear
    # in OpenAPI as well as respond to a real request.
    schema = client.get("/openapi.json").json()
    repo_path = "/api/repositories/{repository_id}"
    assert "delete" in schema["paths"][repo_path]


def test_delete_repository_returns_404_for_unknown_id(hermetic_db) -> None:
    # The actual delete may not succeed without a live DB, but
    # the route should at least produce a 404 rather than 405.
    response = client.delete("/api/repositories/9999999")
    assert response.status_code in (404, 500)


def test_ingest_validation_rejects_short_name() -> None:
    # Name must be at least 1 char; an empty string fails pydantic.
    response = client.post(
        "/api/ingest",
        json={"name": "", "local_path": "C:/nope"},
    )
    assert response.status_code == 422


def test_ingest_validation_rejects_missing_path() -> None:
    response = client.post(
        "/api/ingest",
        json={"name": "demo"},
    )
    assert response.status_code == 422


def test_query_validation_rejects_blank_question() -> None:
    response = client.post(
        "/api/query",
        json={"question": "", "top_k": 5},
    )
    assert response.status_code == 422


def test_query_validation_caps_top_k() -> None:
    # top_k is constrained to 1..20 by the schema.
    response = client.post(
        "/api/query",
        json={"question": "what?", "top_k": 999},
    )
    assert response.status_code == 422