"""Tests for the GitHub URL parser and the background indexer orchestration.

These tests do not hit the network — ``default_branch`` and
``clone_to_temp`` are exercised through monkeypatching ``subprocess.run``
so the suite stays hermetic and fast.

We also exercise the Phase 2 ``POST /api/repositories`` route to confirm
URL validation surfaces as 400. The route-level tests install an
in-memory SQLite override so they don't depend on a live Postgres.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import User
from app.services.security import get_current_user
from app.services.github import (
    GithubRef,
    GithubURLError,
    _build_auth_url,
    clone_to_temp,
    default_branch,
    parse_github_url,
)


@pytest.fixture()
def hermetic_db():
    """In-memory SQLite override for the route-level happy path test.

    Without this fixture the request hits the real Postgres host
    (``db``) which isn't available on a developer machine — the
    route would return 500 instead of the expected 202.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
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
    yield SessionLocal
    app.dependency_overrides.clear()


# ---------- parse_github_url ----------


@pytest.mark.parametrize(
    "url,expected_name",
    [
        ("https://github.com/octocat/Hello-World", "Hello-World"),
        ("https://github.com/octocat/Hello-World.git", "Hello-World"),
        ("http://github.com/octocat/Hello-World", "Hello-World"),
        ("https://github.com/octocat/Hello-World/", "Hello-World"),
    ],
)
def test_parse_accepts_public_github_url(url: str, expected_name: str) -> None:
    ref = parse_github_url(url)
    assert isinstance(ref, GithubRef)
    assert ref.owner == "octocat"
    assert ref.name == expected_name
    assert ref.full_name == "octocat/Hello-World"
    assert ref.clone_url == "https://github.com/octocat/Hello-World.git"


@pytest.mark.parametrize(
    "url,reason",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("github.com/octocat/Hello-World", "scheme"),
        ("https://gist.github.com/octocat/1", "wrong host"),
        ("https://github.com/octocat", "missing repo"),
        ("https://github.com/octocat/Hello-World/extra/path", "extra path"),
        ("https://github.com/octocat/Hello-World?ref=main", "query string"),
        ("https://github.com/octocat/Hello-World#readme", "fragment"),
        ("https://github.com/octocat/-bad-/repo", "bad name"),
        ("https://github.com/.bad/repo", "bad owner"),
    ],
)
def test_parse_rejects_invalid_urls(url: str, reason: str) -> None:
    with pytest.raises(GithubURLError):
        parse_github_url(url)


def test_parse_rejects_too_long_owner() -> None:
    long_owner = "a" * 101
    with pytest.raises(GithubURLError):
        parse_github_url(f"https://github.com/{long_owner}/repo")


# ---------- _build_auth_url ----------


def test_build_auth_url_no_token_returns_clone_url() -> None:
    ref = parse_github_url("https://github.com/octocat/Hello-World")
    assert _build_auth_url(ref, None) == ref.clone_url


def test_build_auth_url_with_token_injects_credential() -> None:
    ref = parse_github_url("https://github.com/octocat/Hello-World")
    url = _build_auth_url(ref, "ghp_secret")
    # Credential lives in the basic-auth segment of the URL.
    assert "x-access-token:ghp_secret@" in url
    assert url.startswith("https://")
    assert ref.full_name in url


# ---------- default_branch ----------


def test_default_branch_parses_symref(monkeypatch) -> None:
    ref = parse_github_url("https://github.com/octocat/Hello-World")

    def fake_run(argv, **_kw):
        class Result:
            returncode = 0
            stdout = "ref: refs/heads/main\tHEAD\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert default_branch(ref) == "main"


def test_default_branch_handles_non_zero(monkeypatch) -> None:
    ref = parse_github_url("https://github.com/octocat/Hello-World")

    def fake_run(argv, **_kw):
        class Result:
            returncode = 128
            stdout = ""
            stderr = "fatal: repository not found"

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(GithubURLError):
        default_branch(ref)


# ---------- clone_to_temp ----------


def test_clone_to_temp_returns_path_and_commit(monkeypatch, tmp_path: Path) -> None:
    ref = parse_github_url("https://github.com/octocat/Hello-World")

    # Pretend the clone succeeded — write a fake .git/HEAD so the second
    # ``git rev-parse HEAD`` invocation reads from the directory we made.
    captured: dict[str, list] = {}

    def fake_run(argv, **_kw):
        captured.setdefault("argv", []).append(argv)
        if argv[0] == "git" and argv[1] == "clone":
            target = Path(argv[-1])
            (target / ".git").mkdir(parents=True, exist_ok=True)
            (target / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()
        if argv[0] == "git" and argv[1] == "rev-parse":
            class Result:
                returncode = 0
                stdout = "0123456789abcdef0123456789abcdef01234567\n"
                stderr = ""

            return Result()
        raise AssertionError(f"unexpected argv: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    target, sha = clone_to_temp(ref, branch="main", workspace_root=tmp_path)
    try:
        assert target.exists()
        assert target.parent == tmp_path
        assert sha == "0123456789abcdef0123456789abcdef01234567"
        # The clone subprocess was called with --depth 1 and --branch main.
        assert any(
            "--depth" in argv and "--branch" in argv
            for argv in captured["argv"]
        )
    finally:
        # The clone helper creates a sibling under tmp_path; clean it up
        # so the test fixture's `tmp_path` doesn't accumulate leftover dirs.
        for child in tmp_path.iterdir():
            if child.is_dir() and child.name.startswith("github-"):
                import shutil
                shutil.rmtree(child, ignore_errors=True)


# ---------- router ----------


client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_test_user():
    """Keep route tests authenticated without weakening production routes."""
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1,
        email="test@example.com",
        password_hash="unused",
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_create_repository_rejects_invalid_url() -> None:
    # Bad URL -> 400 (validation surfaces as an HTTPException).
    response = client.post("/api/repositories", json={"url": "not-a-url"})
    assert response.status_code == 400


def test_create_repository_accepts_well_formed_url(hermetic_db) -> None:
    # With the hermetic SQLite override the route can commit the row
    # and the response should be 202 (queued for indexing). Anything
    # other than 202 here would indicate a regression in the create
    # path even on the happy case.
    SessionLocal = hermetic_db
    response = client.post(
        "/api/repositories",
        json={"url": "https://github.com/octocat/Hello-World"},
    )
    assert response.status_code == 202, response.text


def test_create_repository_rejects_query_string_url() -> None:
    response = client.post(
        "/api/repositories",
        json={"url": "https://github.com/octocat/Hello-World?ref=main"},
    )
    assert response.status_code == 400


def test_openapi_lists_create_repository_route() -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/repositories" in schema["paths"]
    # The POST method is the Phase 2 create endpoint.
    assert "post" in schema["paths"]["/api/repositories"]
