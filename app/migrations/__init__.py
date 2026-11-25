"""Последовательные транзакционные миграции схемы PostgreSQL."""

import hashlib
import importlib
from pathlib import Path
from typing import Optional

import psycopg

MIGRATIONS = (
    ("001", "app.migrations.versions.v001_catalog"),
    ("002", "app.migrations.versions.v002_results"),
    ("003", "app.migrations.versions.v003_auth"),
    ("004", "app.migrations.versions.v004_prize_fund"),
)

LEGACY_COLUMNS = {
    "app_metadata": {"key", "value"},
    "owners": {"id", "name", "contact"},
    "horses": {"id", "name", "birth_date", "breed", "owner_id"},
    "jockeys": {"id", "full_name", "birth_date", "weight_kg"},
    "competitions": {"id", "name", "event_date", "location", "distance_m", "status"},
    "results": {
        "id",
        "competition_id",
        "horse_id",
        "jockey_id",
        "position",
        "time_seconds",
        "disqualified",
        "disqualification_reason",
    },
    "users": {"id", "username", "email", "password_hash", "created_at"},
    "user_sessions": {"id", "user_id", "token_hash", "created_at", "expires_at"},
}

LEGACY_INDEXES = {
    "uq_results_competition_position",
    "uq_users_username_lower",
    "uq_users_email_lower",
    "ix_user_sessions_user_id",
    "ix_user_sessions_expires_at",
}


def _migration(version: str, module_name: str):
    module = importlib.import_module(module_name)
    checksum = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return version, module, checksum


def _table_names(connection: psycopg.Connection) -> set[str]:
    rows = connection.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'
        """
    ).fetchall()
    return {row[0] for row in rows}


def _validate_legacy_schema(connection: psycopg.Connection) -> None:
    """Принять только полную схему v4, созданную прежним приложением."""
    tables = _table_names(connection)
    if not LEGACY_COLUMNS.keys() <= tables:
        raise RuntimeError("Существующая схема неполная; миграция остановлена")
    for table, expected in LEGACY_COLUMNS.items():
        rows = connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = %s
            """,
            (table,),
        ).fetchall()
        if not expected <= {row[0] for row in rows}:
            raise RuntimeError(f"Структура таблицы {table} отличается от схемы v4")
    rows = connection.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
    ).fetchall()
    if not {row[0] for row in rows} >= LEGACY_INDEXES:
        raise RuntimeError("Индексы схемы v4 неполные; миграция остановлена")
    row = connection.execute(
        "SELECT value FROM app_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None or row[0] != "4":
        raise RuntimeError("Неизвестная версия существующей схемы")


def migrate(database_url: str, target_version: Optional[str] = None) -> list[str]:
    """Применить миграции до цели; старую полную схему v4 учесть без потери данных."""
    versions = [version for version, _ in MIGRATIONS]
    if target_version is not None and target_version not in versions:
        raise ValueError(f"Неизвестная версия миграции: {target_version}")
    selected = [
        item
        for item in MIGRATIONS
        if target_version is None or item[0] <= target_version
    ]
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(734628319)")
        tables_before = _table_names(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        applied_rows = connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        applied = {row[0]: row[1] for row in applied_rows}
        if not applied and tables_before - {"schema_migrations"}:
            _validate_legacy_schema(connection)
            for version, module_name in MIGRATIONS[:3]:
                _, _, checksum = _migration(version, module_name)
                connection.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                    (version, checksum),
                )
            applied_rows = connection.execute(
                "SELECT version, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = {row[0]: row[1] for row in applied_rows}

        if list(applied) != versions[: len(applied)]:
            raise RuntimeError(
                "История миграций содержит пропуск или неизвестную версию"
            )
        for version, module_name in MIGRATIONS:
            _, _, checksum = _migration(version, module_name)
            if version in applied and applied[version] != checksum:
                raise RuntimeError(f"Файл уже применённой миграции {version} изменён")
        for version, module_name in selected:
            if version in applied:
                continue
            _, module, checksum = _migration(version, module_name)
            module.upgrade(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (version, checksum),
            )
        rows = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        return [row[0] for row in rows]
