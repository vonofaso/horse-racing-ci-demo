"""Доступность приложения и безопасная диагностика отказа БД."""

from unittest.mock import Mock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app


@pytest.mark.parametrize(
    "failure", [False, psycopg.OperationalError("private connection data")]
)
def test_health_database_failure_returns_safe_503(monkeypatch, failure):
    check = (
        Mock(side_effect=failure)
        if isinstance(failure, Exception)
        else Mock(return_value=failure)
    )
    monkeypatch.setattr(database, "check_database", check)
    # Без контекстного менеджера lifespan не запускается: настоящая БД не нужна.
    response = TestClient(app).get("/health")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "private connection data" not in response.text


def test_health_success(monkeypatch):
    monkeypatch.setattr(database, "check_database", Mock(return_value=True))
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
