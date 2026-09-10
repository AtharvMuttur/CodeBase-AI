"""Embedding generation.

Ships three backends behind a single ``embed_texts`` interface:

* ``remote``         — calls an OpenAI-compatible HTTP endpoint
  (``/v1/embeddings``). Used when ``EMBEDDING_PROVIDER=openai`` and
  ``EMBEDDING_API_KEY`` is set. Works with OpenAI, Together, vLLM,
  Ollama (with the OpenAI compat shim), etc.
* ``gemini_native``  — calls Gemini's native REST endpoint
  ``models/{model}:embedContent``. Used when ``EMBEDDING_PROVIDER=gemini``
  and ``EMBEDDING_API_KEY`` is set. Gemini does NOT expose an
  OpenAI-compatible ``/embeddings`` route on its public API, so the
  ``openai`` backend 404s against ``/v1beta/openai/embeddings`` —
  this backend uses the Google-native path instead.
* ``local``          — deterministic, dependency-free hashed embeddings.
  Used when no API key is configured. The vectors are not
  semantically meaningful in a deep sense, but they are stable, fit
  the schema, and let the rest of the pipeline (ingest → store →
  retrieve → answer) be exercised end-to-end without any network
  dependency.

All backends return float32 numpy arrays of shape ``(n, dim)``.
"""
from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import httpx
import numpy as np
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings


class EmbeddingError(RuntimeError):
    """Raised when the embedding backend fails permanently."""


def _settings():
    return get_settings()


# ---------- shared HTTP client (connection pooling) ----------

# A single httpx.Client per process reuses TCP+TLS connections across
# calls. Without it, every embed request opens a fresh TLS handshake to
# generativelanguage.googleapis.com — on a 200-file repo with ~3 chunks
# per file that's 600 handshakes, which dominates wall time. The Client
# is created lazily so unit tests can monkeypatch ``_post`` (and never
# touch the real network) without paying for an unused pool.
#
# http2=True would let us multiplex many concurrent requests over a
# single connection, but it pulls in the ``h2`` package — kept opt-in
# for now. Flip to True once h2 is added to requirements.
_client_lock = threading.Lock()
_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(
                    timeout=60.0,
                    limits=httpx.Limits(
                        max_keepalive_connections=20,
                        max_connections=50,
                    ),
                )
    return _client


def _post(url: str, *, json: dict, headers: dict, timeout: float = 60.0) -> httpx.Response:
    """Single POST entry point so tests can monkeypatch one symbol.

    Production routes through the shared client to reuse connections;
    tests replace ``embeddings._post`` directly with a fake.
    """
    return _get_client().post(url, json=json, headers=headers, timeout=timeout)


def _reset_client_for_tests() -> None:
    """Drop the cached client. Test-only helper so a monkeypatched
    transport doesn't leak across test files."""
    global _client
    with _client_lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
            _client = None


def _local_dim() -> int:
    """Embedding dimensionality from settings, clamped to a sane range."""
    dim = max(64, min(4096, _settings().embedding_dimensions))
    return dim


def _embed_local(texts: list[str]) -> np.ndarray:
    """Deterministic hashed embeddings.

    For each text we hash the byte sequence, expand it to fill
    ``dim`` floats, and L2-normalize. This produces unit-length
    vectors where similar (in token-set sense) inputs collide
    slightly more often than random ones — enough to validate the
    pipeline but obviously not a substitute for a real model.
    """
    dim = _local_dim()
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for i, text in enumerate(texts):
        # Stretch the digest by hashing chained counters until we
        # have enough pseudo-random bytes.
        needed_bytes = dim * 4  # float32 == 4 bytes
        buf = bytearray()
        counter = 0
        while len(buf) < needed_bytes:
            buf.extend(
                hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
            )
            counter += 1
        # Truncate to the exact byte count and reinterpret as float32.
        arr = np.frombuffer(bytes(buf[:needed_bytes]), dtype=np.uint8).astype(np.float32)
        # We asked for `dim * 4` bytes but uint8→float32 widens 1:1,
        # which gives us `dim * 4` floats. Take the first `dim` to
        # keep the public shape consistent.
        arr = arr[:dim]
        # Center around zero for nicer dot products.
        arr = (arr - 127.5) / 127.5
        # L2 normalize.
        norm = float(np.linalg.norm(arr))
        if norm > 0:
            arr = arr / norm
        out[i] = arr
    return out


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, EmbeddingError)),
)
def _embed_remote(texts: list[str]) -> np.ndarray:
    """Call an OpenAI-compatible /v1/embeddings endpoint.

    Used when ``EMBEDDING_PROVIDER=openai`` (or any other OpenAI-shaped
    provider like together/vLLM/Ollama-with-shim). The base URL is taken
    from ``EMBEDDING_BASE_URL`` and the ``/v1`` prefix is only added
    when the configured URL doesn't already point at an OpenAI-compatible
    namespace. Gemini is NOT routed here — its public API doesn't
    expose an OpenAI-compatible ``/embeddings`` route, so we route
    ``EMBEDDING_PROVIDER=gemini`` through ``_embed_gemini_native`` instead.
    """
    settings = _settings()
    api_key = settings.embedding_api_key
    if not api_key:
        raise EmbeddingError("EMBEDDING_API_KEY is not configured")

    base_url = (settings.embedding_base_url or "https://api.openai.com").rstrip("/")
    if base_url.endswith("/v1") or base_url.endswith("/openai"):
        url = f"{base_url}/embeddings"
    else:
        url = f"{base_url}/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.embedding_model,
        "input": texts,
    }
    try:
        resp = _post(url, headers=headers, json=payload, timeout=60.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise EmbeddingError(f"embedding request failed: {exc}") from exc

    data = resp.json()
    vectors = [item["embedding"] for item in data.get("data", [])]
    if len(vectors) != len(texts):
        raise EmbeddingError(
            f"embedding count mismatch: got {len(vectors)} for {len(texts)} inputs"
        )
    arr = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, EmbeddingError)),
)
def _embed_gemini_native(texts: list[str]) -> np.ndarray:
    """Call Gemini's native ``:embedContent`` endpoint.

    Gemini's public REST API exposes embeddings at
    ``https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent``
    (NOT under any ``/v1beta/openai`` OpenAI-compat namespace — that
    namespace only proxies chat completions, hence the 404 we got
    before this backend existed).

    Auth: ``x-goog-api-key: <key>`` header. The response shape is
    ``{"embedding": {"values": [float, ...]}}`` for a single input;
    we send one request per text because the native endpoint does
    not accept a batched ``inputs[]`` array.

    Returns unit-normalized float32 array of shape ``(n, dim)``
    where ``dim`` is the dimensionality reported by Gemini
    (typically 768 for the current ``gemini-embedding-001`` model
    when ``outputDimensionality`` is set, up to 3072 otherwise).

    Note: the older ``text-embedding-004`` model is no longer exposed
    on the ``v1beta`` REST endpoint and returns 404 — the supported
    model names are ``gemini-embedding-001``,
    ``gemini-embedding-2-preview``, and ``gemini-embedding-2``.
    """
    settings = _settings()
    api_key = settings.embedding_api_key
    if not api_key:
        raise EmbeddingError("EMBEDDING_API_KEY is not configured")

    base_url = (
        settings.embedding_base_url
        or "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    model = settings.embedding_model or "gemini-embedding-001"
    # Pin the output dimensionality to the configured value so we
    # always fit the ``vector(N)`` column size — the new gemini-embedding-*
    # models default to 3072 dims and would otherwise fail to insert.
    out_dim = max(64, min(3072, settings.embedding_dimensions))
    url = f"{base_url}/models/{model}:embedContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    vectors: list[list[float]] = []
    # Gemini's :embedContent endpoint accepts one input per request, so
    # we issue all requests concurrently. With a shared httpx.Client the
    # underlying connections are reused, so this scales linearly with
    # the slowest single request instead of with the sum of latencies.
    # For a 600-chunk repo at ~300 ms/RTT this is the difference between
    # 3 minutes (sequential) and ~5 seconds (16-way parallel).
    def _fetch_one(text: str) -> list[float]:
        payload = {
            "model": f"models/{model}",
            "content": {
                "parts": [{"text": text}],
            },
            "outputDimensionality": out_dim,
        }
        try:
            resp = _post(url, headers=headers, json=payload, timeout=60.0)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingError(
                f"gemini embedContent request failed: {exc}"
            ) from exc

        data = resp.json()
        try:
            return list(data["embedding"]["values"])
        except (KeyError, TypeError) as exc:
            raise EmbeddingError(
                f"gemini embedContent returned unexpected shape: {data!r}"
            ) from exc

    # Gemini rate-limits concurrent requests aggressively on many plans.
    # Keep this below the provider's burst limit so a repository does not
    # spend several retry cycles receiving HTTP 429 responses.
    max_workers = min(4, max(1, len(texts)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # map() preserves input order so the output rows line up with
        # the input chunks — critical because pipeline.py zips them.
        vectors = list(pool.map(_fetch_one, texts))

    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[0] != len(texts):
        raise EmbeddingError(
            f"gemini embedContent returned shape {arr.shape}; "
            f"expected ({len(texts)}, dim)"
        )
    # L2-normalize so dot-product == cosine similarity and we can
    # use a single ORDER BY ... <=> query in pgvector.
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def embed_texts(texts: Iterable[str]) -> np.ndarray:
    """Embed a batch of strings. Returns float32 array, shape ``(n, dim)``.

    Backend selection (in order):

    1. If ``EMBEDDING_PROVIDER=gemini`` and ``EMBEDDING_API_KEY`` is set
       → ``_embed_gemini_native`` (Gemini's ``:embedContent``).
    2. Otherwise if ``EMBEDDING_API_KEY`` is set
       → ``_embed_remote`` (OpenAI-compatible ``/v1/embeddings``).
    3. Otherwise → ``_embed_local`` (deterministic hashed embeddings).

    The dimensionality comes from the upstream provider (or, for the
    local fallback, from ``EMBEDDING_DIMENSIONS``) and must match the
    ``vector(N)`` column size in ``init_db.sql`` — change both at once
    when you swap embedding models.
    """
    batch = [t for t in texts]
    if not batch:
        return np.zeros((0, _local_dim()), dtype=np.float32)
    settings = _settings()
    provider = (settings.embedding_provider or "openai").lower()
    if settings.embedding_api_key:
        if provider == "gemini":
            return _embed_gemini_native(batch)
        return _embed_remote(batch)
    return _embed_local(batch)


def embed_query(text: str) -> np.ndarray:
    """Convenience wrapper for the single-string case."""
    arr = embed_texts([text])
    return arr[0]


__all__ = ["embed_texts", "embed_query", "EmbeddingError"]
