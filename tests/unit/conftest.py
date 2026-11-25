"""Unit-тесты не должны открывать реальные соединения."""

from unittest.mock import Mock

import pytest

from app import database


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    monkeypatch.setattr(
        database,
        "connect_database",
        Mock(
            side_effect=AssertionError("Unit-тест попытался подключиться к БД"),
        ),
    )
