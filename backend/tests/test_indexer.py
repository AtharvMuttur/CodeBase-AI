"""Tests for the GitHub background indexer orchestration.

We don't actually clone anything in these tests — we monkeypatch
``clone_to_temp`` and ``ingest_local_path`` so the indexer can run
its status-update code path against a transient in-memory SQLite.
The point of the test is to confirm the state machine (queued ->
cloning -> scanning -> ready / failed) drives the row correctly.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Repository
from app.services import indexer
from app.services.indexer import index_github_repository


# ---------- in-memory DB fixture ----------


@pytest.fixture()
def memory_db(monkeypatch):
    """Replace the engine with an in-memory SQLite instance.

    pgvector-only features (vector column) aren't exercised here — we
    only touch Repository.status and the simple fields, which exist on
    every backend. We also override the FastAPI ``get_db`` dependency so
    the routes see the same session.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    # SQLite doesn't have pgvector — create_all will still build the
    # Repository / File / CodeChunk tables but skip the Vector column.
    # That's fine because these tests never embed anything; they only
    # flip Repository.status.
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    # Drop the Vector column on code_chunks — SQLite doesn't have it.
    with engine.begin() as conn:
        # Best-effort: the table may or may not exist depending on
        # how SQLAlchemy handled the unsupported type.
        try:
            conn.execute(text("ALTER TABLE code_chunks DROP COLUMN embedding"))
        except Exception:
            pass

    monkeypatch.setattr(indexer, "SessionLocal", SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield SessionLocal

    app.dependency_overrides.clear()


def _create_repo(SessionLocal, url: str) -> int:
    with SessionLocal() as session:
        repo = Repository(name="octocat/Hello-World", source="github", source_uri=url, status="queued")
        session.add(repo)
        session.commit()
        session.refresh(repo)
        return repo.id


def test_indexer_marks_ready_on_success(monkeypatch, memory_db) -> None:
    SessionLocal = memory_db
    repository_id = _create_repo(SessionLocal, "https://github.com/octocat/Hello-World")

    # Stub out the network / filesystem pipeline.
    monkeypatch.setattr(indexer, "parse_github_url", lambda url: _FakeRef())
    monkeypatch.setattr(indexer, "default_branch", lambda ref, token=None: "main")
    monkeypatch.setattr(
        indexer,
        "clone_to_temp",
        lambda ref, *, branch, token=None, workspace_root=None: (Path("/tmp/fake-clone"), "abcdef1234567890"),
    )

    class FakeResult:
        file_count = 3
        chunk_count = 7

    monkeypatch.setattr(
        indexer,
        "ingest_local_path",
        lambda session, *, name, local_path, repository_id, source: FakeResult(),
    )

    # Run synchronously.
    index_github_repository(repository_id, "https://github.com/octocat/Hello-World")

    with SessionLocal() as session:
        repo = session.get(Repository, repository_id)
        assert repo.status == "ready"
        assert repo.file_count == 3
        assert repo.chunk_count == 7
        assert repo.branch == "main"
        assert repo.commit_sha == "abcdef1234567890"
        assert repo.error_message is None


def test_indexer_marks_failed_on_bad_url(monkeypatch, memory_db) -> None:
    SessionLocal = memory_db
    repository_id = _create_repo(SessionLocal, "not-a-url")

    from app.services.github import GithubURLError

    def boom(_url):
        raise GithubURLError("bad url")

    monkeypatch.setattr(indexer, "parse_github_url", boom)

    index_github_repository(repository_id, "not-a-url")

    with SessionLocal() as session:
        repo = session.get(Repository, repository_id)
        assert repo.status == "failed"
        assert "bad url" in (repo.error_message or "")


def test_indexer_marks_failed_on_clone_error(monkeypatch, memory_db) -> None:
    SessionLocal = memory_db
    repository_id = _create_repo(SessionLocal, "https://github.com/octocat/Hello-World")

    monkeypatch.setattr(indexer, "parse_github_url", lambda url: _FakeRef())
    monkeypatch.setattr(indexer, "default_branch", lambda ref, token=None: "main")

    from app.services.github import GithubURLError

    def boom(*_a, **_kw):
        raise GithubURLError("clone failed for x/y: not found")

    monkeypatch.setattr(indexer, "clone_to_temp", boom)

    index_github_repository(repository_id, "https://github.com/octocat/Hello-World")

    with SessionLocal() as session:
        repo = session.get(Repository, repository_id)
        assert repo.status == "failed"
        assert "clone failed" in (repo.error_message or "")


def test_indexer_resets_progress_at_start(monkeypatch, memory_db) -> None:
    SessionLocal = memory_db
    # Pre-populate counters so we can confirm the indexer zeroes them.
    with SessionLocal() as session:
        repo = Repository(
            name="octocat/Hello-World",
            source="github",
            source_uri="https://github.com/octocat/Hello-World",
            status="failed",
            file_count=99,
            chunk_count=999,
            files_processed=99,
            total_files=99,
            error_message="previous error",
        )
        session.add(repo)
        session.commit()
        session.refresh(repo)
        repository_id = repo.id

    monkeypatch.setattr(indexer, "parse_github_url", lambda url: _FakeRef())
    monkeypatch.setattr(indexer, "default_branch", lambda ref, token=None: "main")
    monkeypatch.setattr(
        indexer,
        "clone_to_temp",
        lambda ref, *, branch, token=None, workspace_root=None: (Path("/tmp/fake-clone"), "deadbeef"),
    )

    class FakeResult:
        file_count = 1
        chunk_count = 1

    monkeypatch.setattr(
        indexer,
        "ingest_local_path",
        lambda session, *, name, local_path, repository_id, source: FakeResult(),
    )

    index_github_repository(repository_id, "https://github.com/octocat/Hello-World")

    with SessionLocal() as session:
        repo = session.get(Repository, repository_id)
        assert repo.status == "ready"
        assert repo.error_message is None
        assert repo.file_count == 1
        assert repo.chunk_count == 1


# ---------- helpers ----------


class _FakeRef:
    """Minimal stand-in for a GithubRef used inside the indexer."""

    owner = "octocat"
    name = "Hello-World"
    full_name = "octocat/Hello-World"
    clone_url = "https://github.com/octocat/Hello-World.git"
