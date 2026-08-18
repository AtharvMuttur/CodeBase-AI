"""Tests for the LLM service.

We only test the extractive fallback because the remote path requires
a network round-trip. The contract is: when ``LLM_API_KEY`` is unset,
``generate_answer`` returns the extractive-fallback model name and a
string that includes the cited chunk.
"""
from __future__ import annotations

from app.config import get_settings
from app.services.llm import ContextChunk, generate_answer


def _chunks() -> list[ContextChunk]:
    return [
        ContextChunk(
            file_path="src/example.py",
            start_line=1,
            end_line=5,
            content="def add(a, b):\n    return a + b\n",
        ),
        ContextChunk(
            file_path="src/example.py",
            start_line=10,
            end_line=15,
            content="class Calc:\n    def mul(self, a, b):\n        return a * b\n",
        ),
    ]


def test_extractive_fallback_when_no_api_key(monkeypatch) -> None:
    # Force the unset-API-key path even if the developer has one locally.
    monkeypatch.setattr(get_settings(), "llm_api_key", None)
    answer, model = generate_answer("What does add do?", _chunks())
    assert model == "extractive-fallback"
    assert "src/example.py" in answer
    assert "def add(a, b):" in answer


def test_no_chunks_returns_explanatory_message(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_api_key", None)
    answer, model = generate_answer("anything", [])
    assert "No relevant chunks" in answer
    # Model name is still echoed so the frontend can display it.
    assert isinstance(model, str)