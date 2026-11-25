"""Проверка регистрации, входа, выхода и защиты данных."""

import asyncio
from contextlib import AsyncExitStack

from httpx import ASGITransport, AsyncClient

from app.main import app


async def run_auth_scenario() -> None:
    transport = ASGITransport(app=app)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(app.router.lifespan_context(app))
        client = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://test")
        )

        assert (await client.get("/owners")).status_code == 401

        credentials = {
            "username": "rider_admin",
            "email": "admin@example.test",
            "password": "Strong-password-2026",
        }
        registered = await client.post("/auth/register", json=credentials)
        assert registered.status_code == 201
        assert registered.json()["username"] == "rider_admin"
        assert "password" not in registered.json()
        assert (await client.get("/owners")).status_code == 200

        duplicate = await client.post("/auth/register", json=credentials)
        assert duplicate.status_code == 409

        assert (await client.post("/auth/logout")).status_code == 204
        assert (await client.get("/auth/me")).status_code == 401

        failed = await client.post(
            "/auth/login", json={"username": "rider_admin", "password": "wrong"}
        )
        assert failed.status_code == 401

        logged_in = await client.post(
            "/auth/login",
            json={"username": "rider_admin", "password": credentials["password"]},
        )
        assert logged_in.status_code == 200
        assert (await client.get("/auth/me")).json()["email"] == credentials["email"]


def test_registration_login_logout_and_protection(postgres_database) -> None:
    asyncio.run(run_auth_scenario())
