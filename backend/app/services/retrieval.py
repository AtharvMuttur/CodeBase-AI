"""Semantic retrieval over pgvector.

A single function ``search(question, repository_id, top_k)`` that:

1. Embeds the question with the same backend used at ingestion time.
2. Executes a pgvector cosine-distance query (``ORDER BY embedding <=> q``).
3. Returns rows joined with their file paths so callers can cite.

pgvector's ``<=>`` operator is cosine *distance* (1 - similarity
for unit vectors), so lower is better; we convert back to a
similarity score (``1 - distance``) for the API response.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .embeddings import embed_query
from ..models import EMBEDDING_DIMENSIONS


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    file_id: int
    file_path: str
    language: Optional[str]
    start_line: int
    end_line: int
    content: str
    score: float          # cosine similarity in [0, 1] for unit vectors


def search(
    session: Session,
    *,
    question: str,
    repository_id: Optional[int] = None,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """Return the top-k chunks most similar to ``question``.

    The query is parameterized to avoid SQL injection. The vector
    literal is rendered by pgvector's SQLAlchemy type — we send
    ``:embedding`` as a Python list and the driver serializes it
    into the ``vector`` column literal form.
    """
    if not question.strip():
        return []

    embedding = embed_query(question).tolist()
    if len(embedding) != EMBEDDING_DIMENSIONS:
        # The hashed local backend always returns the configured
        # dim, so this only fires if someone changed settings
        # without re-creating the schema.
        raise ValueError(
            f"embedding has {len(embedding)} dims; "
            f"schema expects {EMBEDDING_DIMENSIONS}"
        )

    sql = text(
        """
        SELECT
            c.id           AS chunk_id,
            f.id           AS file_id,
            f.path         AS file_path,
            f.language     AS language,
            c.start_line   AS start_line,
            c.end_line     AS end_line,
            c.content      AS content,
            1 - (c.embedding <=> CAST(:embedding AS vector)) AS score
        FROM code_chunks c
        JOIN files f ON f.id = c.file_id
        WHERE c.embedding IS NOT NULL
          AND (:repository_id IS NULL OR c.repository_id = :repository_id)
        ORDER BY c.embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
        """
    )

    rows = session.execute(
        sql,
        {
            "embedding": embedding,
            "repository_id": repository_id,
            "top_k": top_k,
        },
    ).all()

    return [
        RetrievedChunk(
            chunk_id=int(r.chunk_id),
            file_id=int(r.file_id),
            file_path=str(r.file_path),
            language=r.language,
            start_line=int(r.start_line),
            end_line=int(r.end_line),
            content=str(r.content),
            score=float(r.score),
        )
        for r in rows
    ]


__all__ = ["search", "RetrievedChunk"]
