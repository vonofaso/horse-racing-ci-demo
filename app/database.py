"""Схема данных и базовые операции с PostgreSQL."""

from typing import Any, Dict, List, Optional, Sequence

import psycopg
from psycopg.rows import dict_row

from app.config import settings

DATABASE_URL = settings.database_url
SCHEMA_VERSION = "4"


def connect_database() -> psycopg.Connection[Dict[str, Any]]:
    """Открыть соединение PostgreSQL с результатами в виде словарей."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def initialize_database() -> None:
    """Применить ожидающие миграции к указанной PostgreSQL."""
    from app.migrations import migrate

    if not DATABASE_URL.strip():
        raise ValueError("Задайте DATABASE_URL")
    migrate(DATABASE_URL)


def fetch_one(
    query: str,
    parameters: Sequence[Any] = (),
) -> Optional[Dict[str, Any]]:
    """Выполнить запрос на чтение одной строки."""
    with connect_database() as connection:
        row = connection.execute(query, parameters).fetchone()
    return dict(row) if row is not None else None


def fetch_all(
    query: str,
    parameters: Sequence[Any] = (),
) -> List[Dict[str, Any]]:
    """Выполнить запрос на чтение нескольких строк."""
    with connect_database() as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [dict(row) for row in rows]


def insert(query: str, parameters: Sequence[Any]) -> int:
    """Добавить строку в транзакции и вернуть её идентификатор."""
    statement = f"{query.rstrip().rstrip(';')} RETURNING id"
    with connect_database() as connection:
        row = connection.execute(statement, parameters).fetchone()
    if row is None:
        raise RuntimeError("PostgreSQL не вернул идентификатор новой записи")
    return int(row["id"])


def execute(query: str, parameters: Sequence[Any] = ()) -> int:
    """Изменить или удалить строки в транзакции."""
    with connect_database() as connection:
        cursor = connection.execute(query, parameters)
        return cursor.rowcount


def get_database_info() -> Dict[str, Any]:
    """Вернуть данные о фактическом подключении PostgreSQL и схеме."""
    with connect_database() as connection:
        row = connection.execute(
            """
            SELECT
                current_database() AS database_name,
                current_setting('server_version') AS server_version,
                (
                    SELECT value FROM app_metadata
                    WHERE key = 'schema_version'
                ) AS schema_version
            """
        ).fetchone()
    if row is None:
        raise RuntimeError("Не удалось получить сведения о PostgreSQL")
    return {
        "engine": "PostgreSQL",
        "database_name": row["database_name"],
        "server_version": row["server_version"],
        "schema_version": row["schema_version"],
    }


def check_database() -> bool:
    """Выполнить минимальный запрос для проверки доступности PostgreSQL."""
    with connect_database() as connection:
        row = connection.execute("SELECT 1 AS ok").fetchone()
    return row is not None and row["ok"] == 1
