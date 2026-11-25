"""Призовой фонд проходит через API и сохраняется в PostgreSQL."""

import psycopg
import pytest

from app import database


def test_prize_fund_create_update_and_validation(client):
    client.post(
        "/auth/register",
        json={
            "username": "prize_admin",
            "email": "prize@example.test",
            "password": "Password-2026",
        },
    )
    data = {
        "name": "Кубок",
        "event_date": "2026-01-01",
        "location": "Москва",
        "distance_m": 1600,
    }
    created = client.post("/competitions", json=data)
    assert created.status_code == 201
    competition_id = created.json()["id"]
    assert created.json()["prize_fund_rub"] == 0

    updated = client.put(
        f"/competitions/{competition_id}",
        json={**data, "prize_fund_rub": 150_000},
    )
    assert updated.status_code == 200
    assert (
        client.get(f"/competitions/{competition_id}").json()["prize_fund_rub"]
        == 150_000
    )
    assert (
        database.fetch_one(
            "SELECT prize_fund_rub FROM competitions WHERE id = %s", (competition_id,)
        )["prize_fund_rub"]
        == 150_000
    )

    invalid = client.put(
        f"/competitions/{competition_id}",
        json={**data, "prize_fund_rub": -1},
    )
    assert invalid.status_code == 422
    assert (
        client.get(f"/competitions/{competition_id}").json()["prize_fund_rub"]
        == 150_000
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        database.execute(
            "UPDATE competitions SET prize_fund_rub = -1 WHERE id = %s",
            (competition_id,),
        )
