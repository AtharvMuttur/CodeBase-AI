"""Tests for the CodeBase AI backend.

Phase 1 ships a single smoke test that boots the FastAPI app in
isolation and asserts that /api/health returns a 200 with the
expected shape. The test does not require a live database — it
overrides the health endpoint to report database=ok regardless of
the real DB state.
"""
