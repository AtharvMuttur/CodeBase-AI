-- ============================================================
-- CodeBase AI — Phase 2 migration
--
-- Adds the GitHub ingestion columns that were introduced after
-- the original Phase 1 init_db.sql was first applied to the
-- running codebase_pgdata volume. Idempotent: each ALTER is
-- guarded by IF NOT EXISTS so re-running this script is safe.
--
-- Run once via:
--   docker compose exec -T db psql \
--     -U codebase -d codebase_ai \
--     -f /docker-entrypoint-initdb.d/migrate_phase2.sql
-- ============================================================

-- Add the GitHub-specific metadata columns to repositories.
-- Each ALTER is guarded because the column may already exist
-- (e.g. a previous partial migration run).
ALTER TABLE repositories ADD COLUMN IF NOT EXISTS owner           TEXT;
ALTER TABLE repositories ADD COLUMN IF NOT EXISTS branch          TEXT;
ALTER TABLE repositories ADD COLUMN IF NOT EXISTS commit_sha      TEXT;

-- Add Phase 2 progress counters used by the background indexer
-- so the frontend can render a live progress bar.
ALTER TABLE repositories
    ADD COLUMN IF NOT EXISTS files_processed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE repositories
    ADD COLUMN IF NOT EXISTS total_files     INTEGER NOT NULL DEFAULT 0;

-- Composite index used by the deduplication query in
-- POST /api/repositories (lookup by source + owner + name).
CREATE INDEX IF NOT EXISTS ix_repositories_source_owner_name
    ON repositories (source, owner, name);
