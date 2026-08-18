-- ============================================================
-- CodeBase AI — database initialization
-- Runs once on first container startup via
-- /docker-entrypoint-initdb.d/init_db.sql
-- ============================================================

-- The pgvector extension is provided by the pgvector image.
-- It must be created before any vector columns are defined.
CREATE EXTENSION IF NOT EXISTS vector;

-- ------------------------------------------------------------
-- Phase 1 schema: minimal RAG tables.
--   repositories : one row per indexed repo / local folder
--   files        : one row per source file inside a repository
--   code_chunks  : one row per chunked, embedded piece of a file
--
-- Vector column uses `vector(EMBEDDING_DIMENSIONS)`. The default
-- 1536 matches OpenAI's text-embedding-3-small; if you switch to a
-- model with a different dimensionality, run an Alembic migration
-- to recreate the column.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS repositories (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    source          TEXT NOT NULL,            -- "local" | "github" | "url"
    source_uri      TEXT,                     -- path/url the repo was loaded from
    owner           TEXT,                     -- GitHub owner (Phase 2; null for local)
    branch          TEXT,                     -- GitHub default branch (Phase 2)
    commit_sha      TEXT,                     -- HEAD commit at indexing time (Phase 2)
    file_count      INTEGER NOT NULL DEFAULT 0,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    files_processed INTEGER NOT NULL DEFAULT 0,  -- Phase 2 progress
    total_files     INTEGER NOT NULL DEFAULT 0,  -- Phase 2 progress
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | queued | cloning | scanning | chunking | embedding | storing | ready | failed
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS files (
    id            BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path          TEXT NOT NULL,            -- path relative to repo root, forward-slash separated
    language      TEXT,                     -- detected language, e.g. "python"
    size_bytes    INTEGER NOT NULL DEFAULT 0,
    chunk_count   INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (repository_id, path)
);

CREATE INDEX IF NOT EXISTS ix_files_repository_id ON files (repository_id);

-- code_chunks: vector column sized to EMBEDDING_DIMENSIONS.
-- Default 768 matches Gemini text-embedding-004; raise/lower to match
-- EMBEDDING_DIMENSIONS in backend/app/config.py when swapping models.
-- `metadata` carries chunk_type ("code" | "doc"), start_line, end_line.
CREATE TABLE IF NOT EXISTS code_chunks (
    id            BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    file_id       BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,         -- ordinal inside the file
    start_line    INTEGER NOT NULL,
    end_line      INTEGER NOT NULL,
    content       TEXT NOT NULL,
    content_hash  TEXT NOT NULL,            -- sha256 of content, used for dedup
    embedding     vector(768),
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_chunks_repository_id ON code_chunks (repository_id);
CREATE INDEX IF NOT EXISTS ix_chunks_file_id       ON code_chunks (file_id);
CREATE INDEX IF NOT EXISTS ix_repositories_source_owner_name
    ON repositories (source, owner, name);

-- IVFFlat index would normally speed up ANN search, but it requires
-- a non-empty table to build and the build cost is significant for
-- small repos. Phase 1 uses an exact ORDER BY embedding <=> embedding
-- query, which is plenty fast for the MVP and avoids the maintenance
-- burden. Phase 3+ will introduce an ANN index.

-- ============================================================
-- Phase 2 maintenance
--
-- If you bring up a fresh codebase_pgdata volume against an older
-- codebase_pgdata that already had the Phase 1 schema, run
-- backend/scripts/migrate_phase2.sql once to backfill the columns
-- the Phase 2 background indexer expects (owner, branch, commit_sha,
-- files_processed, total_files).
-- ============================================================
