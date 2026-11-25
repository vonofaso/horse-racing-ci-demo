"""Тесты запуска, схемы данных и служебного адреса."""

import asyncio
from contextlib import AsyncExitStack

from httpx import ASGITransport, AsyncClient

from app import database
from app.main import app


async def request_system_endpoints():
    """Запросить системные адреса без отдельного сервера."""
    transport = ASGITransport(app=app)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(app.router.lifespan_context(app))
        client = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://test")
        )
        return (
            await client.get("/"),
            await client.get("/api/system"),
            await client.get("/health"),
            await client.get("/docs"),
            await client.get("/redoc"),
            await client.get("/openapi.json"),
        )


def test_root_uses_postgresql_database(postgres_database) -> None:
    (
        response,
        system_response,
        health_response,
        docs_response,
        redoc_response,
        openapi_response,
    ) = asyncio.run(request_system_endpoints())

    assert response.status_code == 200
    assert "Каждый финиш" in response.text
    assert system_response.json()["name"] == "Скачки API"
    assert system_response.json()["database"]["engine"] == "PostgreSQL"
    assert system_response.json()["database"]["schema_version"] == "4"
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok", "database": "ok"}
    assert docs_response.status_code == 200
    assert "Как выполнить запрос" in docs_response.text
    assert '"defaultModelsExpandDepth": -1' in docs_response.text
    assert ".swagger-ui .models" in docs_response.text
    assert redoc_response.status_code == 404
    assert openapi_response.json()["info"]["version"] == "v0.1.0"
    assert "description" not in openapi_response.json()["info"]
    tables = {
        row["table_name"]
        for row in database.fetch_all(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = current_schema()
            """
        )
    }

    assert {
        "app_metadata",
        "owners",
        "horses",
        "jockeys",
        "competitions",
        "results",
        "users",
        "user_sessions",
    }.issubset(tables)
