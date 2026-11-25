"""Отдельная PostgreSQL и временные схемы для интеграционных тестов."""

import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app import database, schemas, services
from app.main import app
from scripts.db_tools import check_test_database


def pytest_collection_modifyitems(items):
    """Разделить тесты для быстрых локальных и полных прогонов."""
    for item in items:
        uses_database = {"postgres_database", "migration_database"} & set(
            item.fixturenames
        )
        marker = "integration" if uses_database else "unit"
        item.add_marker(getattr(pytest.mark, marker))


@pytest.fixture
def migration_database():
    """Пустая схема в отдельной тестовой БД для проверки миграций."""
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("Для миграционных тестов задайте TEST_DATABASE_URL", pytrace=False)
    check_test_database()
    schema_name = f"migration_{uuid4().hex}"
    with psycopg.connect(database_url) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    try:
        yield make_conninfo(database_url, options=f"-csearch_path={schema_name}")
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


@pytest.fixture
def postgres_database(monkeypatch):
    """Каждый тест получает свою схему, удаляемую даже при ошибке теста."""
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail(
            "Для интеграционных тестов задайте TEST_DATABASE_URL", pytrace=False
        )

    check_test_database()
    schema_name = f"test_{uuid4().hex}"
    with psycopg.connect(database_url) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    try:
        isolated_url = make_conninfo(
            database_url, options=f"-csearch_path={schema_name}"
        )
        monkeypatch.setattr(database, "DATABASE_URL", isolated_url)
        database.initialize_database()
        yield isolated_url
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


@pytest.fixture
def client(postgres_database):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def race(postgres_database):
    """Минимальный заезд с двумя независимыми участниками."""
    owner = services.create_owner(
        schemas.OwnerInput(name="Конный клуб", contact="Телефон")
    )
    horses = [
        services.create_horse(
            schemas.HorseInput(
                name=name,
                birth_date="2020-01-01",
                breed="Орловская",
                owner_id=owner["id"],
            )
        )
        for name in ("Буран", "Стрела")
    ]
    jockeys = [
        services.create_jockey(
            schemas.JockeyInput(
                full_name=name,
                birth_date="1990-01-01",
                weight_kg=58.5,
            )
        )
        for name in ("Иван Петров", "Пётр Иванов")
    ]
    competition = services.create_competition(
        schemas.CompetitionInput(
            name="Кубок",
            event_date="2026-01-01",
            location="Москва",
            distance_m=1600,
        )
    )
    return {
        "owner": owner,
        "horses": horses,
        "jockeys": jockeys,
        "competition": competition,
    }


@pytest.fixture
def result_data(race):
    return {
        "competition_id": race["competition"]["id"],
        "horse_id": race["horses"][0]["id"],
        "jockey_id": race["jockeys"][0]["id"],
        "position": 1,
        "time_seconds": 94.2,
    }
