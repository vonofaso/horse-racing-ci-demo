"""Ожидаемые ошибки приложения, безопасные для возврата клиенту."""


class ApplicationError(Exception):
    """Базовая ошибка с HTTP-статусом и машинным кодом."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class NotFoundError(ApplicationError):
    """Запрошенная предметная сущность не существует."""

    def __init__(self, entity_name: str, entity_id: int) -> None:
        super().__init__(
            status_code=404,
            code="not_found",
            message=f"{entity_name} с идентификатором {entity_id} не найден(а)",
        )


class ConflictError(ApplicationError):
    """Операция нарушает уникальность или ссылочную целостность."""

    def __init__(self, message: str) -> None:
        super().__init__(status_code=409, code="conflict", message=message)


class ServiceUnavailableError(ApplicationError):
    """Обязательная зависимость приложения временно недоступна."""

    def __init__(self, message: str) -> None:
        super().__init__(
            status_code=503,
            code="service_unavailable",
            message=message,
        )
