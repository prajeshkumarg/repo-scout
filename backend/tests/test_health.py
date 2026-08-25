"""Health endpoint tests. No network: the probes are patched."""

import pytest
from fastapi.testclient import TestClient

from api import health
from api.main import app
from api.models import DependencyStatus


@pytest.fixture
def client():
    return TestClient(app)


def test_health_ok_when_all_dependencies_reachable(client, monkeypatch):
    monkeypatch.setattr(health, "check_postgres", lambda: DependencyStatus(ok=True))
    monkeypatch.setattr(health, "check_redis", lambda: DependencyStatus(ok=True))

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == health.VERSION
    assert body["dependencies"]["postgres"] == {"ok": True, "detail": None}
    assert body["dependencies"]["redis"] == {"ok": True, "detail": None}


def test_health_degraded_when_a_dependency_is_down(client, monkeypatch):
    monkeypatch.setattr(health, "check_postgres", lambda: DependencyStatus(ok=True))
    monkeypatch.setattr(
        health,
        "check_redis",
        lambda: DependencyStatus(ok=False, detail="connection refused"),
    )

    response = client.get("/health")

    # Degraded is still a 200. The body carries the bad news, not the status
    # code, so the process stays in rotation.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["redis"]["detail"] == "connection refused"
