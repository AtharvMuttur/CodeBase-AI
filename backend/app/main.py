"""FastAPI application entry point.

The `create_app` factory keeps state out of module-level globals,
which makes the application easier to test (each test can build
its own app with overridden dependencies).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_settings
from .core.logging import configure_logging
from .routers import auth, health, ingest, query, repositories


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Application startup and shutdown hooks.

    Currently we just configure logging. Phase 2+ will use this
    hook to warm the embedding model cache and verify required
    external credentials.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("codebase_ai_starting", extra={"version": __version__})
    yield
    logger.info("codebase_ai_stopping", extra={"version": __version__})


def create_app() -> FastAPI:
    """Application factory.

    Returns a fully configured FastAPI instance. The factory pattern
    is what lets tests construct the app with isolated state.
    """
    settings = get_settings()

    app = FastAPI(
        title="CodeBase AI",
        version=__version__,
        description=(
            "CodeBase AI is a RAG assistant for repository understanding. "
            "Index a GitHub repository and ask natural-language questions "
            "about its code, with citations back to the source."
        ),
        lifespan=lifespan,
        # Surface the OpenAPI schema at both /openapi.json and /api/openapi.json
        # for compatibility with various tooling.
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS — the frontend lives on a different origin during development.
    # We allow the configured FRONTEND_URL plus the typical Vite ports
    # so the developer does not have to keep tweaking env vars while
    # the frontend shape evolves.
    allowed_origins = {
        settings.frontend_url,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    }
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(repositories.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(query.router, prefix="/api")

    return app


app = create_app()
