"""Проверка CRUD, связей и правил предметной области."""

import asyncio
from contextlib import AsyncExitStack

from httpx import ASGITransport, AsyncClient

from app.main import app


async def register_test_user(client: AsyncClient, suffix: str) -> None:
    response = await client.post(
        "/auth/register",
        json={
            "username": f"tester_{suffix}",
            "email": f"tester_{suffix}@example.test",
            "password": "Reliable-password-2026",
        },
    )
    assert response.status_code == 201


async def run_crud_scenario() -> None:
    transport = ASGITransport(app=app)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(app.router.lifespan_context(app))
        client = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://test")
        )
        await register_test_user(client, "crud")
        owner = (
            await client.post(
                "/owners",
                json={"name": "Конный клуб Вектор", "contact": "+7 900 000-00-00"},
            )
        ).json()
        assert (await client.get(f"/owners/{owner['id']}")).status_code == 200
        updated_owner = await client.put(
            f"/owners/{owner['id']}",
            json={"name": "Клуб Вектор", "contact": "vector@example.test"},
        )
        assert updated_owner.json()["name"] == "Клуб Вектор"

        horse = (
            await client.post(
                "/horses",
                json={
                    "name": "Буран",
                    "birth_date": "2020-05-10",
                    "breed": "Орловская рысистая",
                    "owner_id": owner["id"],
                },
            )
        ).json()
        updated_horse = await client.put(
            f"/horses/{horse['id']}",
            json={**horse, "breed": "Орловский рысак"},
        )
        assert updated_horse.json()["breed"] == "Орловский рысак"

        jockey = (
            await client.post(
                "/jockeys",
                json={
                    "full_name": "Иван Петров",
                    "birth_date": "1995-03-20",
                    "weight_kg": 58.5,
                },
            )
        ).json()
        updated_jockey = await client.put(
            f"/jockeys/{jockey['id']}",
            json={**jockey, "weight_kg": 58.0},
        )
        assert updated_jockey.json()["weight_kg"] == 58.0

        competition = (
            await client.post(
                "/competitions",
                json={
                    "name": "Кубок Москвы",
                    "event_date": "2026-08-15",
                    "location": "Центральный ипподром",
                    "distance_m": 1600,
                    "status": "planned",
                },
            )
        ).json()
        updated_competition = await client.put(
            f"/competitions/{competition['id']}",
            json={**competition, "status": "completed"},
        )
        assert updated_competition.json()["status"] == "completed"

        result_response = await client.post(
            "/results",
            json={
                "competition_id": competition["id"],
                "horse_id": horse["id"],
                "jockey_id": jockey["id"],
                "position": 1,
                "time_seconds": 94.2,
                "disqualified": False,
            },
        )
        assert result_response.status_code == 201
        result = result_response.json()
        updated_result = await client.put(
            f"/results/{result['id']}",
            json={**result, "time_seconds": 93.9},
        )
        assert updated_result.json()["time_seconds"] == 93.9

        filtered_results = await client.get(
            "/results", params={"competition_id": competition["id"]}
        )
        assert [item["id"] for item in filtered_results.json()] == [result["id"]]
        assert len((await client.get("/owners")).json()) == 1
        assert len((await client.get("/horses")).json()) == 1
        assert len((await client.get("/jockeys")).json()) == 1
        assert len((await client.get("/competitions")).json()) == 1

        blocked_delete = await client.delete(f"/owners/{owner['id']}")
        assert blocked_delete.status_code == 409

        assert (await client.delete(f"/results/{result['id']}")).status_code == 204
        assert (await client.delete(f"/horses/{horse['id']}")).status_code == 204
        assert (await client.delete(f"/jockeys/{jockey['id']}")).status_code == 204
        assert (
            await client.delete(f"/competitions/{competition['id']}")
        ).status_code == 204
        assert (await client.delete(f"/owners/{owner['id']}")).status_code == 204


def test_crud_for_all_related_entities(postgres_database) -> None:
    asyncio.run(run_crud_scenario())


async def run_invalid_requests_scenario() -> None:
    transport = ASGITransport(app=app)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(app.router.lifespan_context(app))
        client = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://test")
        )
        await register_test_user(client, "invalid")
        invalid_horse = await client.post(
            "/horses",
            json={
                "name": "Будущая",
                "birth_date": "2999-01-01",
                "breed": "Тестовая",
                "owner_id": 999,
            },
        )
        assert invalid_horse.status_code == 422
        assert invalid_horse.json()["error"]["code"] == "validation_error"

        owner = (await client.post("/owners", json={"name": "Владелец"})).json()
        missing_owner = await client.post(
            "/horses",
            json={
                "name": "Нет владельца",
                "birth_date": "2020-01-01",
                "breed": "Тестовая",
                "owner_id": 999,
            },
        )
        assert missing_owner.status_code == 404

        horses = []
        jockeys = []
        for number in (1, 2):
            horses.append(
                (
                    await client.post(
                        "/horses",
                        json={
                            "name": f"Лошадь {number}",
                            "birth_date": "2020-01-01",
                            "breed": "Тестовая",
                            "owner_id": owner["id"],
                        },
                    )
                ).json()
            )
            jockeys.append(
                (
                    await client.post(
                        "/jockeys",
                        json={
                            "full_name": f"Жокей {number}",
                            "birth_date": f"199{number}-01-01",
                            "weight_kg": 58,
                        },
                    )
                ).json()
            )

        competition = (
            await client.post(
                "/competitions",
                json={
                    "name": "Тестовый заезд",
                    "event_date": "2026-05-01",
                    "location": "Ипподром",
                    "distance_m": 1000,
                },
            )
        ).json()
        first_result = {
            "competition_id": competition["id"],
            "horse_id": horses[0]["id"],
            "jockey_id": jockeys[0]["id"],
            "position": 1,
            "time_seconds": 61.5,
            "disqualified": False,
        }
        assert (await client.post("/results", json=first_result)).status_code == 201

        duplicate_horse = {
            **first_result,
            "jockey_id": jockeys[1]["id"],
            "position": 2,
        }
        response = await client.post("/results", json=duplicate_horse)
        assert response.status_code == 409
        assert "Лошадь" in response.json()["error"]["message"]

        duplicate_position = {
            **first_result,
            "horse_id": horses[1]["id"],
            "jockey_id": jockeys[1]["id"],
        }
        response = await client.post("/results", json=duplicate_position)
        assert response.status_code == 409
        assert "место" in response.json()["error"]["message"]

        no_disqualification_reason = {
            **duplicate_position,
            "position": 2,
            "disqualified": True,
        }
        response = await client.post("/results", json=no_disqualification_reason)
        assert response.status_code == 422

        not_found = await client.get("/owners/999")
        assert not_found.status_code == 404
        assert not_found.json()["error"]["code"] == "not_found"

        unknown_route = await client.get("/unknown")
        assert unknown_route.status_code == 404
        assert unknown_route.json()["error"]["code"] == "http_error"


def test_invalid_requests_and_domain_rules(postgres_database) -> None:
    asyncio.run(run_invalid_requests_scenario())


async def run_duplicate_catalog_scenario() -> None:
    transport = ASGITransport(app=app)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(app.router.lifespan_context(app))
        client = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://test")
        )
        await register_test_user(client, "duplicates")

        owner_data = {"name": "Одинаковый владелец", "contact": "same@example.test"}
        first_owner = await client.post("/owners", json=owner_data)
        second_owner = await client.post("/owners", json=owner_data)
        assert first_owner.status_code == second_owner.status_code == 201
        owner_id = first_owner.json()["id"]

        horse_data = {
            "name": "Одинаковая лошадь",
            "birth_date": "2020-01-01",
            "breed": "Одинаковая порода",
            "owner_id": owner_id,
        }
        assert (await client.post("/horses", json=horse_data)).status_code == 201
        assert (await client.post("/horses", json=horse_data)).status_code == 201

        jockey_data = {
            "full_name": "Одинаковый жокей",
            "birth_date": "1990-01-01",
            "weight_kg": 58,
        }
        assert (await client.post("/jockeys", json=jockey_data)).status_code == 201
        assert (await client.post("/jockeys", json=jockey_data)).status_code == 201

        competition_data = {
            "name": "Одинаковое состязание",
            "event_date": "2026-01-01",
            "location": "Одинаковое место",
            "distance_m": 1000,
        }
        first_competition = await client.post("/competitions", json=competition_data)
        second_competition = await client.post("/competitions", json=competition_data)
        assert first_competition.status_code == second_competition.status_code == 201


def test_duplicate_catalog_entities_are_allowed(postgres_database) -> None:
    asyncio.run(run_duplicate_catalog_scenario())


async def run_horse_search_scenario() -> None:
    transport = ASGITransport(app=app)

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(app.router.lifespan_context(app))
        client = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://test")
        )
        await register_test_user(client, "search")

        owner = (
            await client.post("/owners", json={"name": "Тестовый владелец"})
        ).json()

        for name in ("Буран", "Стрела"):
            await client.post(
                "/horses",
                json={
                    "name": name,
                    "birth_date": "2020-01-01",
                    "breed": "Тестовая",
                    "owner_id": owner["id"],
                },
            )

        response = await client.get("/horses", params={"name": "бур"})

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "Буран"


def test_horse_search(postgres_database) -> None:
    asyncio.run(run_horse_search_scenario())
