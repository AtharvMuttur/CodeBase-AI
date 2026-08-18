"""Question-answering endpoint.

Phase 1 ships a single endpoint:

    POST /api/query
        body: { question, repository_id?, top_k? }
        returns: { answer, chunks: [...], model, repository_id }

The handler:
  1. Calls retrieval.search() to find the most relevant chunks.
  2. Builds a context-grounded prompt.
  3. Calls the LLM (or the extractive fallback) for the final answer.
  4. Returns the answer plus the citations so the frontend can render
     links to the source file/line range.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import ChunkCitation, QueryRequest, QueryResponse
from ..services.llm import ContextChunk, LLMError, generate_answer
from ..services.retrieval import search


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])


@router.post(
    "",
    response_model=QueryResponse,
    summary="Ask a question about the indexed codebase",
)
def ask_question(
    payload: QueryRequest,
    db: Session = Depends(get_db),
) -> QueryResponse:
    """Embed the question, retrieve the top-k chunks, and ask the LLM."""
    try:
        chunks = search(
            db,
            question=payload.question,
            repository_id=payload.repository_id,
            top_k=payload.top_k,
        )
    except Exception as exc:  # noqa: BLE001 — any retrieval failure is a 500
        logger.exception("query retrieval failed")
        raise HTTPException(status_code=500, detail=f"retrieval failed: {exc}") from exc

    context_for_llm = [
        ContextChunk(
            file_path=c.file_path,
            start_line=c.start_line,
            end_line=c.end_line,
            content=c.content,
        )
        for c in chunks
    ]

    try:
        answer, model_name = generate_answer(
            payload.question,
            context_for_llm,
        )
    except LLMError as exc:
        logger.exception("LLM generation failed")
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {exc}") from exc

    return QueryResponse(
        answer=answer,
        chunks=[
            ChunkCitation(
                chunk_id=c.chunk_id,
                file_id=c.file_id,
                file_path=c.file_path,
                language=c.language,
                start_line=c.start_line,
                end_line=c.end_line,
                content=c.content,
                score=round(c.score, 4),
            )
            for c in chunks
        ],
        model=model_name,
        repository_id=payload.repository_id,
    )


__all__ = ["router"]
