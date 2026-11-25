"""Проверка чтения конфигурации из окружения."""

from app.config import Settings


def test_settings_are_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "Тестовые скачки")
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://tester:secret@db.example.test:5432/races",
    )
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_PORT", "9000")
    monkeypatch.setenv("APP_RELOAD", "true")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings.from_environment()

    assert settings.app_name == "Тестовые скачки"
    assert settings.app_version == "9.9.9"
    assert settings.database_url == (
        "postgresql://tester:secret@db.example.test:5432/races"
    )
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.reload is True
    assert settings.log_level == "debug"


def test_no_database_password_fallback(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert Settings.from_environment().database_url == ""
