# =============================================================
# CodeBase AI — backend image
# Multi-stage layout reserved for later phases; Phase 1 uses
# a single builder+runtime image for simplicity.
# =============================================================

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps. git is here for the Phase 2 ingestion layer.
# build-essential is kept for any C-extension wheels (e.g. tree-sitter).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Workspace used by the Phase 2+ ingestion layer for cloned repos
# and the Phase 3+ parser cache.
RUN mkdir -p /app/workspace

EXPOSE 8000

# `--reload` for development; remove for production.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
