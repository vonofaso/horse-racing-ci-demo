"""Запуск сервера с настройками из переменных окружения."""

import uvicorn

from app.config import settings


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level,
        timeout_graceful_shutdown=15,
    )


if __name__ == "__main__":
    main()
