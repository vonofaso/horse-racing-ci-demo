"""Обязательные ограничения служебных операций без запуска PostgreSQL."""

from unittest.mock import Mock

import pytest

from app.migrations import migrate
from scripts import db_tools


@pytest.mark.parametrize(
    "url", ["postgresql://u:p@localhost/data", "host=localhost dbname=data"]
)
def test_production_database_cannot_be_used_for_tests(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    with pytest.raises(ValueError):
        db_tools.check_test_database()


@pytest.mark.parametrize("database", ["different", "data", ""])
def test_test_database_requires_name_and_suffix(monkeypatch, database):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/data")
    monkeypatch.setenv("TEST_DATABASE_URL", f"postgresql://localhost/{database}")
    with pytest.raises(ValueError):
        db_tools.check_test_database()


def test_separate_test_database_is_allowed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/data")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://localhost/data_test")
    db_tools.check_test_database()


def test_pg_environment_keeps_password_out_of_command_arguments(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://tester:private-value@localhost/data"
    )
    environment, name = db_tools.pg_environment("DATABASE_URL")
    assert name == "data"
    assert environment["PGPASSWORD"] == "private-value"
    assert environment["PGUSER"] == "tester"


@pytest.mark.parametrize("url", ["", '""', "''", "not-a-connection-url"])
def test_backup_reports_invalid_database_url_without_traceback(
    monkeypatch, capsys, tmp_path, url
):
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(
        "sys.argv", ["db_tools", "backup", "--file", str(tmp_path / "backup.dump")]
    )

    assert db_tools.main() == 1
    output = capsys.readouterr()
    assert "DATABASE_URL" in output.err
    assert "Traceback" not in output.err
    assert not (tmp_path / "backup.dump").exists()


def test_unknown_connection_option_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "dbname=data application_name=unexpected")
    with pytest.raises(ValueError, match="Неподдерживаемые"):
        db_tools.pg_environment("DATABASE_URL")


def test_restore_without_confirmation_never_runs_process(monkeypatch, tmp_path):
    monkeypatch.setenv("RESTORE_DATABASE_URL", "postgresql://localhost/restored")
    monkeypatch.delenv("CONFIRM_RESTORE", raising=False)
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"data")
    run = Mock()
    monkeypatch.setattr(db_tools.subprocess, "run", run)
    with pytest.raises(ValueError, match="CONFIRM_RESTORE"):
        db_tools.restore(archive)
    run.assert_not_called()


def test_backup_never_overwrites_existing_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/data")
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"original")
    run = Mock()
    monkeypatch.setattr(db_tools.subprocess, "run", run)
    with pytest.raises(FileExistsError):
        db_tools.backup(archive)
    assert archive.read_bytes() == b"original"
    run.assert_not_called()


def test_unknown_migration_target_rejected_before_connection(monkeypatch):
    connect = Mock()
    monkeypatch.setattr("app.migrations.psycopg.connect", connect)
    with pytest.raises(ValueError, match="Неизвестная"):
        migrate("unused", target_version="999")
    connect.assert_not_called()
