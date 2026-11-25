"""Создание FastAPI-приложения и общая обработка ошибок."""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import database
from app.auth import router as auth_router
from app.config import settings
from app.errors import ApplicationError, ServiceUnavailableError
from app.routes import router

OPENAPI_TAGS = [
    {
        "name": "Система",
        "description": "Общая информация и проверка работоспособности.",
    },
    {
        "name": "Владельцы",
        "description": "Сначала создайте владельца, затем добавляйте его лошадей.",
    },
    {"name": "Лошади", "description": "Лошади обязательно связаны с владельцем."},
    {"name": "Жокеи", "description": "Справочник жокеев."},
    {"name": "Состязания", "description": "Заезды, даты и места проведения."},
    {
        "name": "Результаты",
        "description": "Связь состязания, лошади и жокея с итоговым местом.",
    },
]

DOCS_STYLE = """
<style>
  .api-help {
    max-width: 1260px;
    margin: 22px auto 0;
    padding: 14px 20px;
    border: 1px solid #d8dee4;
    border-radius: 6px;
    background: #f6f8fa;
    color: #24292f;
    font-family: sans-serif;
    line-height: 1.45;
  }
  .api-help strong { display: block; margin-bottom: 5px; }
  .swagger-ui .models { display: none !important; }
  .swagger-ui .info .description { display: none !important; }
  .swagger-ui .info .main a { display: none !important; }
  .swagger-ui .info .version-stamp { display: none !important; }
  .swagger-ui .info .title small:last-child { display: none !important; }
</style>
"""

DOCS_HELP = """
<div class="api-help">
  <strong>Как выполнить запрос</strong>
  Сначала вызовите <code>POST /auth/register</code> или
  <code>POST /auth/login</code>. Браузер сохранит защищённую cookie-сессию,
  после чего станут доступны операции с предметными данными.
</div>
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Подготовить PostgreSQL перед обработкой HTTP-запросов."""
    database.initialize_database()
    yield


app = FastAPI(
    title=settings.app_name,
    description="",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_tags=OPENAPI_TAGS,
)
app.include_router(router)
app.include_router(auth_router)

WEB_DIR = settings.project_root / "app" / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/docs", include_in_schema=False)
def swagger_documentation() -> HTMLResponse:
    """Показать упрощённую интерактивную документацию Swagger UI."""
    page = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{settings.app_name} — документация",
        swagger_ui_parameters={
            "defaultModelsExpandDepth": -1,
            "displayRequestDuration": True,
            "docExpansion": "list",
            "tryItOutEnabled": True,
        },
    )
    content = page.body.decode("utf-8")
    content = content.replace("</head>", f"{DOCS_STYLE}</head>")
    content = content.replace("<body>", f"<body>{DOCS_HELP}")

    return HTMLResponse(content=content)


@app.exception_handler(ApplicationError)
async def handle_application_error(
    _: Request,
    error: ApplicationError,
) -> JSONResponse:
    """Вернуть ожидаемую ошибку в едином формате."""
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _: Request,
    error: RequestValidationError,
) -> JSONResponse:
    """Вернуть безопасное описание некорректных входных данных."""
    details = [
        {
            "location": item["loc"],
            "message": item["msg"],
            "type": item["type"],
        }
        for item in error.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Переданы некорректные данные",
                "details": details,
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(
    _: Request,
    error: StarletteHTTPException,
) -> JSONResponse:
    """Привести системные HTTP-ошибки к общему формату."""
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": "http_error",
                "message": str(error.detail),
            }
        },
    )


@app.get("/", include_in_schema=False)
def read_root() -> FileResponse:
    """Открыть пользовательский веб-интерфейс."""
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")


@app.get("/api/system", summary="Информация о приложении", tags=["Система"])
def system_info() -> Dict[str, Any]:
    """Вернуть сведения о приложении и подключении к PostgreSQL."""
    return {
        "name": settings.app_name,
        "status": "running",
        "database": database.get_database_info(),
    }


@app.get("/health", summary="Проверить приложение и базу", tags=["Система"])
def health_check() -> Dict[str, str]:
    """Проверить доступность API и выполнить запрос к PostgreSQL."""
    try:
        database_available = database.check_database()
    except psycopg.Error as error:
        raise ServiceUnavailableError("База данных недоступна") from error

    if not database_available:
        raise ServiceUnavailableError("База данных не ответила на проверочный запрос")
    return {"status": "ok", "database": "ok"}
