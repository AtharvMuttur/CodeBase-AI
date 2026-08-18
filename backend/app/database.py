"""Database engine and session management.

We use SQLAlchemy 2.x with the synchronous psycopg driver for Phase 1.
The session is dependency-injected into request handlers via
`get_db()`. Async support can be added later by swapping the
engine and `get_db` for their async counterparts — the public
shape of `get_db` will stay the same.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


settings = get_settings()

# `pool_pre_ping` cheaply validates connections before each checkout
# so a stale connection (e.g. after Postgres restart) does not
# surface as a 500 to the user.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models.

    Inheriting from `Base` is enough to register a model — no
    decorator needed (SQLAlchemy 2.x style).
    """


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped DB session.

    The session is closed automatically when the request finishes,
    even if an exception is raised.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database() -> bool:
    """Return True if the database is reachable.

    Used by the health endpoint. We use a trivial `SELECT 1` rather
    than opening a full session so the check stays cheap.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
