"""Ошибочные HTTP-данные и точная граница срока сессии в настоящей БД."""

from datetime import datetime, timezone

import pytest

from app import auth, database


@pytest.mark.parametrize(
    "route,payload",
    [
        ("/owners", {"name": " "}),
        (
            "/horses",
            {
                "name": "Лошадь",
                "birth_date": "2020-01-01",
                "breed": "Порода",
                "owner_id": 0,
            },
        ),
        (
            "/jockeys",
            {"full_name": "Жокей", "birth_date": "1990-01-01", "weight_kg": "Infinity"},
        ),
        (
            "/competitions",
            {
                "name": "Заезд",
                "event_date": "invalid-date",
                "location": "Город",
                "distance_m": 1000,
            },
        ),
        (
            "/competitions",
            {
                "name": "Заезд",
                "event_date": "2026-01-01",
                "location": "Город",
                "distance_m": 0,
            },
        ),
        (
            "/results",
            {
                "competition_id": 1,
                "horse_id": 1,
                "jockey_id": 1,
                "position": 1,
                "time_seconds": "NaN",
            },
        ),
        (
            "/results",
            {
                "competition_id": 1,
                "horse_id": 1,
                "jockey_id": 1,
                "position": 1,
                "time_seconds": 1,
                "disqualified": True,
            },
        ),
    ],
)
def test_invalid_payload_returns_uniform_error_without_writes(client, route, payload):
    response = client.post(
        "/auth/register",
        json={
            "username": "tester",
            "email": "tester@example.test",
            "password": "password",
        },
    )
    assert response.status_code == 201
    result = client.post(route, json=payload)
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "validation_error"
    assert result.json()["error"]["details"]
    assert database.fetch_all(f"SELECT * FROM {route[1:]}") == []


def test_session_expiring_exactly_now_is_rejected(client, monkeypatch):
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    monkeypatch.setattr(auth, "_now", lambda: now)
    assert (
        client.post(
            "/auth/register",
            json={
                "username": "tester",
                "email": "tester@example.test",
                "password": "password",
            },
        ).status_code
        == 201
    )
    database.execute("UPDATE user_sessions SET expires_at = %s", (now,))
    assert client.get("/auth/me").status_code == 401
    assert client.get("/owners").status_code == 401
