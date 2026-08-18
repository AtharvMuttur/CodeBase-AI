"""Tests for the chunker and file discovery.

These tests are pure-Python (no DB, no network) so they're cheap
and deterministic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.ingestion import (
    ALLOWED_EXTENSIONS,
    EXCLUDED_DIR_NAMES,
    chunk_text,
    discover_files,
)


# ---------- chunk_text ----------


def test_chunk_empty_text_returns_empty_list() -> None:
    assert chunk_text("") == []


def test_chunk_whitespace_only_text_does_not_crash() -> None:
    # The chunker is intentionally permissive — it doesn't try to
    # detect "all whitespace". We just assert it terminates and
    # produces chunks that round-trip without raising.
    chunks = chunk_text("\n\n\n")
    assert isinstance(chunks, list)
    assert all(isinstance(c.content, str) for c in chunks)


def test_chunk_short_text_produces_one_chunk() -> None:
    body = "print('hi')\nprint('there')"
    chunks = chunk_text(body, chunk_size_lines=60, chunk_overlap_lines=15)
    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 2
    assert chunks[0].content == body
    # sha256 of the content
    assert len(chunks[0].content_hash) == 64


def test_chunk_long_text_overlaps() -> None:
    lines = [f"line {i}" for i in range(1, 101)]  # 100 lines
    body = "\n".join(lines)
    chunks = chunk_text(body, chunk_size_lines=20, chunk_overlap_lines=5)
    assert len(chunks) > 1
    # Stride = 20 - 5 = 15. Starting at 0, 15, 30, 45, 60, 75, 90.
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    # Each chunk except possibly the last should be exactly 20 lines.
    assert all(c.end_line - c.start_line + 1 == 20 for c in chunks[:-1])
    # Line numbers are 1-indexed and inclusive.
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 20


# ---------- discover_files ----------


def test_discover_files_filters_out_excluded_dirs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("var x = 1;\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    found = discover_files(tmp_path, max_file_size_kb=64, max_files=100)
    rels = sorted(f.relative_path for f in found)
    assert rels == ["src/main.py"]


def test_discover_files_filters_by_extension(tmp_path: Path) -> None:
    (tmp_path / "code.py").write_text("x = 1\n")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n")

    found = discover_files(tmp_path, max_file_size_kb=64, max_files=100)
    names = sorted(f.relative_path for f in found)
    assert names == ["Dockerfile", "code.py"]


def test_discover_files_respects_max_size(tmp_path: Path) -> None:
    big = "x" * (300 * 1024)  # 300 KB
    (tmp_path / "big.py").write_text(big)
    (tmp_path / "small.py").write_text("x = 1\n")

    found = discover_files(tmp_path, max_file_size_kb=64, max_files=100)
    names = [f.relative_path for f in found]
    assert names == ["small.py"]


def test_discover_files_raises_for_missing_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_files(tmp_path / "nope", max_file_size_kb=64, max_files=100)


def test_discover_files_raises_for_file_root(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("x = 1\n")
    with pytest.raises(NotADirectoryError):
        discover_files(f, max_file_size_kb=64, max_files=100)


def test_excluded_dirs_and_allowed_extensions_are_frozensets() -> None:
    # Sanity check that the constants are immutable so a downstream
    # mutation doesn't accidentally shrink the allowlist.
    assert isinstance(EXCLUDED_DIR_NAMES, frozenset)
    assert isinstance(ALLOWED_EXTENSIONS, frozenset)