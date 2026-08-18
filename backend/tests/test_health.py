"""Smoke test for the /api/health endpoint."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_returns_expected_shape() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["status"] in {"ok", "degraded", "error"}
    assert "version" in body
    assert isinstance(body["database"], bool)
    assert "timestamp" in body
    assert "details" in body


def test_root_endpoint() -> None:
    # The friendly root lives inside the health router, which is
    # mounted under /api — so the actual path is /api/.
    response = client.get("/api/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "CodeBase AI"
    assert body["health"] == "/api/health"


def test_openapi_schema_is_served() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "CodeBase AI"
    assert "/api/health" in schema["paths"]
