"""LLM response generation.

Single function ``generate_answer(question, chunks, ...)`` that builds
a context-grounded prompt and calls Google's Gemini
``/v1beta/models/{model}:generateContent`` endpoint. If
``LLM_API_KEY`` is unset we fall back to an extractive answer — we
concatenate the top chunks and prepend a short lead-in. The
retrieval pipeline still works end-to-end; we just don't have a
generative model in the loop.

The system prompt enforces two Phase 1 constraints:

1. Only answer from the provided context.
2. Cite the source file path and line range for every claim.

Citation format is plain text (``[path:start-end]``) so the frontend
doesn't have to do any parsing to render it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings


SYSTEM_PROMPT = (
    "You are CodeBase AI, a code understanding assistant. "
    "Answer the user's question using ONLY the code snippets provided "
    "in the context. If the answer is not contained in the context, say "
    "so explicitly. For every claim, cite the source file path and the "
    "line range in square brackets, e.g. [backend/app/main.py:1-30]. "
    "Do not invent function names, file paths, or behaviour."
)


class LLMError(RuntimeError):
    """Raised when the LLM backend fails permanently."""


@dataclass(frozen=True)
class ContextChunk:
    """A chunk handed to the LLM as context."""

    file_path: str
    start_line: int
    end_line: int
    content: str


def _settings():
    return get_settings()


def _format_context(chunks: Iterable[ContextChunk]) -> str:
    parts: list[str] = []
    for c in chunks:
        parts.append(
            f"--- {c.file_path} (lines {c.start_line}-{c.end_line}) ---\n{c.content}\n"
        )
    return "\n".join(parts)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, LLMError)),
)
def _call_remote(messages: list[dict[str, str]], model: str) -> str:
    settings = _settings()
    api_key = settings.llm_api_key
    if not api_key:
        raise LLMError("LLM_API_KEY is not configured")

    # Native Gemini generateContent endpoint.
    # The configured base URL is expected to end in /v1beta (or be left
    # blank to default to the public host). We strip any trailing slash
    # and append the per-model path with the key as a query parameter.
    base_url = (settings.llm_base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    url = f"{base_url}/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}

    # Gemini's generateContent takes a flat list of {role, parts:[{text}]}
    # turns. Map OpenAI-style messages (system/user) onto that shape —
    # system turns become user-role "system" instructions so older Gemini
    # models that don't accept a `systemInstruction` field still work.
    contents: list[dict] = []
    for m in messages:
        role = "user" if m["role"] in {"system", "user"} else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    payload: dict = {"contents": contents}
    # Match the temperature we used on the OpenAI-compat path.
    payload["generationConfig"] = {"temperature": 0.2}

    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected LLM response shape: {data}") from exc


def _extractive_answer(question: str, chunks: list[ContextChunk]) -> str:
    """Fallback when no LLM API key is configured.

    We don't pretend to have generated an answer — we make it clear
    the response is an extract and the operator should configure
    ``LLM_API_KEY`` for real generation.
    """
    if not chunks:
        return (
            "I could not find any relevant code in the indexed repository for "
            "your question. Configure LLM_API_KEY in .env to enable generative answers."
        )
    body = _format_context(chunks[:3])
    lead = (
        "LLM_API_KEY is not configured, so this is an extractive answer from "
        "the most relevant chunks. Configure LLM_API_KEY in .env to enable "
        "generative answers.\n\n"
    )
    return lead + body


def generate_answer(
    question: str,
    chunks: list[ContextChunk],
    *,
    model: str | None = None,
) -> tuple[str, str]:
    """Return (answer, model_name).

    ``model_name`` is reported back to the caller so the API can
    echo which model produced the response (or that the extractive
    fallback was used).
    """
    settings = _settings()
    model_name = model or settings.llm_model

    if not chunks:
        return (
            "No relevant chunks were retrieved for this question. The indexed "
            "repository may be empty, or your question is unrelated to its contents.",
            model_name,
        )

    if not settings.llm_api_key:
        return _extractive_answer(question, chunks), "extractive-fallback"

    user_prompt = (
        f"Context:\n{_format_context(chunks)}\n\n"
        f"Question: {question}\n\n"
        "Answer (with citations):"
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    return _call_remote(messages, model_name), model_name


__all__ = ["generate_answer", "ContextChunk", "LLMError"]
