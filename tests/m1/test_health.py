from __future__ import annotations

from fastapi.testclient import TestClient

from yourvpn_api.main import create_app as create_api_app
from yourvpn_core.config import AppSettings
from yourvpn_worker.main import build_worker_health
from yourvpn_wg_agent.main import create_app as create_wg_agent_app


def test_api_health() -> None:
    app = create_api_app(AppSettings(environment="test"))
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "api"
    assert body["status"] == "ok"
    assert body["environment"] == "test"


def test_worker_health() -> None:
    health = build_worker_health(AppSettings(environment="test"))

    assert health.service == "worker"
    assert health.status == "ok"
    assert health.details["job_polling"] == "database"


def test_wg_agent_health_never_uses_database() -> None:
    app = create_wg_agent_app(AppSettings(environment="test"))
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "wg-agent"
    assert body["details"]["database_access"] is False
