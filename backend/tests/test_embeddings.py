"""Tests for the embedding backends.

The local backend tests run without any API keys and validate
shape, determinism, and L2-normalization. The Gemini-native
backend test monkeypatches ``httpx.post`` so it stays hermetic
and doesn't actually hit Google's API.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.config import Settings, get_settings
from app.services import embeddings
from app.services.embeddings import embed_texts, _embed_gemini_native


# ---------- local backend ----------


def _override_settings(**overrides) -> None:
    """Patch the cached settings with the given overrides.

    The settings object is cached with ``lru_cache``; we mutate the
    cached instance in place so the test never has to clear the cache.
    """
    settings = get_settings()
    for key, value in overrides.items():
        setattr(settings, key, value)


def test_empty_input_returns_empty_array() -> None:
    _override_settings(embedding_api_key=None)
    out = embed_texts([])
    assert out.shape[0] == 0
    assert out.dtype == np.float32


def test_local_backend_produces_l2_normalized_vectors() -> None:
    _override_settings(embedding_api_key=None)
    out = embed_texts(["hello world", "goodbye world"])
    assert out.shape[0] == 2
    assert out.shape[1] == get_settings().embedding_dimensions
    norms = np.linalg.norm(out, axis=1)
    np.testing.assert_allclose(norms, [1.0, 1.0], atol=1e-5)


def test_local_backend_is_deterministic() -> None:
    _override_settings(embedding_api_key=None)
    a = embed_texts(["def foo(): return 1"])
    b = embed_texts(["def foo(): return 1"])
    np.testing.assert_array_equal(a, b)


def test_local_backend_different_inputs_differ() -> None:
    _override_settings(embedding_api_key=None)
    a = embed_texts(["alpha"])
    b = embed_texts(["beta"])
    # Vectors must not be identical — this would mean the hashing is broken.
    assert not np.array_equal(a, b)


# ---------- Gemini native backend ----------


def test_gemini_native_returns_normalized_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive ``_embed_gemini_native`` against a fake HTTP layer.

    We never hit the real Google API in tests. The fake returns a
    768-dim vector per input, so we can assert shape and
    L2-normalization without any network.
    """
    _override_settings(
        embedding_provider="gemini",
        embedding_api_key="test-key",
        embedding_model="text-embedding-004",
        embedding_base_url="https://generativelanguage.googleapis.com/v1beta",
    )

    captured: dict[str, list] = {"calls": [], "urls": [], "headers": []}

    def fake_post(url, *, json, headers, timeout):
        # Record what the client sends so the test asserts on it.
        captured["urls"].append(url)
        captured["headers"].append(dict(headers))
        captured["calls"].append(json)
        # Build a 768-dim deterministic vector from the input text so
        # distinct inputs produce distinct responses (mirrors real
        # provider behaviour without any randomness).
        text = json["content"]["parts"][0]["text"]
        rng = np.random.default_rng(abs(hash(text)) % (2**32))
        values = rng.standard_normal(768).astype(np.float32).tolist()

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"embedding": {"values": values}}

        return Response()

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    out = _embed_gemini_native(["alpha", "beta"])

    # Two texts in -> two vectors out.
    assert out.shape == (2, 768)
    assert out.dtype == np.float32
    norms = np.linalg.norm(out, axis=1)
    np.testing.assert_allclose(norms, [1.0, 1.0], atol=1e-5)

    # The URL and headers should match Gemini's native schema.
    assert captured["urls"] == [
        "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent",
        "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent",
    ]
    assert all(h.get("x-goog-api-key") == "test-key" for h in captured["headers"])
    # One HTTP call per text (the native endpoint is not batched).
    assert len(captured["calls"]) == 2


def test_gemini_native_surfaces_unexpected_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """If Gemini returns a payload we don't recognise, raise a clean error."""
    _override_settings(
        embedding_provider="gemini",
        embedding_api_key="test-key",
    )

    def fake_post(url, *, json, headers, timeout):
        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"not": "what we expected"}

        return Response()

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)
    with pytest.raises(embeddings.EmbeddingError):
        _embed_gemini_native(["alpha"])
