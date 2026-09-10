-- Add authentication tables and repository ownership to an existing database.
-- Existing repositories remain unowned until they are assigned manually or
-- removed; authenticated users can only see repositories with their user_id.

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE repositories
    ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS ix_repositories_user_id ON repositories (user_id);