"""Чтение настроек приложения из переменных окружения."""

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} должен содержать true или false")


def _read_port(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} должен быть целым числом") from error

    if not 1 <= value <= 65535:
        raise ValueError(f"{name} должен находиться в диапазоне 1..65535")
    return value


@dataclass(frozen=True)
class Settings:
    """Настройки, которые задаются окружением при запуске процесса."""

    app_name: str
    app_version: str
    database_url: str
    host: str
    port: int
    reload: bool
    log_level: str
    project_root: Path = PROJECT_ROOT

    @classmethod
    def from_environment(cls) -> "Settings":
        """Создать настройки из окружения с безопасными значениями по умолчанию."""
        return cls(
            app_name=os.getenv("APP_NAME", "Скачки API"),
            app_version=os.getenv("APP_VERSION", "v0.1.0"),
            database_url=os.getenv("DATABASE_URL", ""),
            host=os.getenv("APP_HOST", "127.0.0.1"),
            port=_read_port("APP_PORT", 8000),
            reload=_read_bool("APP_RELOAD", False),
            log_level=os.getenv("LOG_LEVEL", "info").lower(),
        )


settings = Settings.from_environment()
