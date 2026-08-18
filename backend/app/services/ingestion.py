"""File discovery and chunking for the ingestion pipeline.

Phase 1 keeps this deliberately simple:

* File discovery walks a local directory and applies an allow/deny
  filter based on extension and directory name.
* Chunking is line-based: a sliding window over the source. This
  isn't a tree-sitter AST chunker (that's Phase 3) but it is fast,
  deterministic, and good enough to surface relevant context for the
  MVP retrieval tests.

Both pieces run as plain functions — no async, no external state.
The orchestration (calling them in the right order, persisting rows,
handling errors) lives in the API layer.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


# ---------- File discovery ----------

# Directories we never want to walk into. These typically contain
# generated code, vendored deps, or huge blobs that dwarf the actual
# source.
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "out",
        "coverage",
        ".idea",
        ".vscode",
        ".next",
        ".nuxt",
        "target",          # java/rust
        "vendor",          # php/go
        ".docker",
        ".gradle",
        ".terraform",
    }
)

# Allowlist of extensions considered source. Anything not listed is
# skipped — we don't index images, binaries, archives, lock files,
# minified JS, etc.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".pyi",
        ".js", ".jsx", ".mjs", ".cjs",
        ".ts", ".tsx",
        ".go",
        ".rs",
        ".java", ".kt", ".kts",
        ".rb",
        ".php",
        ".cs",
        ".cpp", ".cc", ".cxx", ".hpp", ".hxx", ".h",
        ".c",
        ".swift",
        ".m", ".mm",
        ".scala",
        ".sh", ".bash", ".zsh",
        ".sql",
        ".html", ".htm",
        ".css", ".scss", ".less",
        ".md", ".mdx", ".rst", ".txt",
        ".yml", ".yaml", ".toml", ".json", ".ini", ".cfg",
        ".dockerfile",
        ".proto",
        ".lua",
        ".ex", ".exs",
        ".vue", ".svelte",
    }
)

# Some files are source but have no useful extension (Dockerfile,
# Makefile, etc.). Map basename -> language.
SPECIAL_FILENAMES: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "makefile",
    "Rakefile": "ruby",
    "Gemfile": "ruby",
    "CMakeLists.txt": "cmake",
}


@dataclass(frozen=True)
class DiscoveredFile:
    """A single source file on disk, after filtering."""

    absolute_path: Path
    relative_path: str  # forward-slash separated, repo-relative
    size_bytes: int
    language: str | None


def detect_language(path: Path) -> str | None:
    """Best-effort language detection by filename/extension."""
    if path.name in SPECIAL_FILENAMES:
        return SPECIAL_FILENAMES[path.name]
    ext = path.suffix.lower()
    if not ext:
        return None
    # Strip leading dot
    return ext.lstrip(".")


def discover_files(
    root: Path,
    *,
    max_file_size_kb: int,
    max_files: int,
) -> list[DiscoveredFile]:
    """Walk ``root`` and return a filtered list of source files.

    The walk is iterative (no recursion depth blowups) and applies
    three filters in order:

    1. Skip excluded directory names.
    2. Skip files whose extension isn't in the allowlist (with a
       special-case for files like ``Dockerfile``).
    3. Skip files larger than ``max_file_size_kb`` — these are
       almost always generated or vendored.

    The function never raises for permission errors on individual
    entries; it just skips them. A missing root raises ``FileNotFoundError``
    so the caller can return a clear 4xx to the client.
    """
    if not root.exists():
        raise FileNotFoundError(f"path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"path is not a directory: {root}")

    max_bytes = max_file_size_kb * 1024
    out: list[DiscoveredFile] = []
    for entry in _walk(root):
        try:
            if not entry.is_file():
                continue
        except OSError:
            continue

        ext = entry.suffix.lower()
        if entry.name not in SPECIAL_FILENAMES and ext not in ALLOWED_EXTENSIONS:
            continue

        try:
            size = entry.stat().st_size
        except OSError:
            continue
        if size > max_bytes:
            continue

        rel = entry.relative_to(root).as_posix()
        out.append(
            DiscoveredFile(
                absolute_path=entry,
                relative_path=rel,
                size_bytes=size,
                language=detect_language(entry),
            )
        )
        if len(out) >= max_files:
            break
    return out


def _walk(root: Path):
    """Yield paths under ``root`` while skipping excluded directories in-place."""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            iterator = iter(current.iterdir())
        except OSError:
            continue
        for entry in iterator:
            try:
                if entry.is_dir():
                    if entry.name in EXCLUDED_DIR_NAMES:
                        continue
                    if entry.name.startswith(".") and entry.name not in {".github"}:
                        # skip dot-dirs but keep .github for CI workflows
                        continue
                    stack.append(entry)
                else:
                    yield entry
            except OSError:
                continue


# ---------- Chunking ----------


@dataclass(frozen=True)
class CodeChunkData:
    """A chunked piece of source, ready to be embedded and stored."""

    chunk_index: int
    start_line: int       # 1-indexed, inclusive
    end_line: int         # 1-indexed, inclusive
    content: str
    content_hash: str
    metadata: dict[str, object]


def chunk_text(
    content: str,
    *,
    chunk_size_lines: int = 60,
    chunk_overlap_lines: int = 15,
) -> list[CodeChunkData]:
    """Split a source file into overlapping line windows.

    Phase 1 deliberately avoids language-aware AST chunking — the goal
    is a working MVP, not the optimal retrieval unit. We use a simple
    sliding window with overlap. Phase 3 will replace this with a
    tree-sitter-based chunker.

    Empty files produce an empty list (no chunks).
    """
    lines = content.splitlines()
    if not lines:
        return []

    chunks: list[CodeChunkData] = []
    stride = max(1, chunk_size_lines - chunk_overlap_lines)
    chunk_index = 0
    for start in range(0, len(lines), stride):
        end = min(start + chunk_size_lines, len(lines))
        body = "\n".join(lines[start:end])
        chunks.append(
            CodeChunkData(
                chunk_index=chunk_index,
                start_line=start + 1,
                end_line=end,
                content=body,
                content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
                metadata={"kind": "code", "lines": end - start},
            )
        )
        chunk_index += 1
        if end >= len(lines):
            break
    return chunks


__all__ = [
    "DiscoveredFile",
    "CodeChunkData",
    "discover_files",
    "chunk_text",
    "detect_language",
]
