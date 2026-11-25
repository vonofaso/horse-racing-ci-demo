"""Регистрация, вход и проверка пользовательских сессий."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import psycopg
from fastapi import APIRouter, Cookie, Depends, Response, status
from typing_extensions import Annotated

from app import database, schemas
from app.errors import ApplicationError, ConflictError

SESSION_COOKIE = "horse_session"
SESSION_DAYS = 7
PBKDF2_ITERATIONS = 310_000

router = APIRouter(prefix="/auth", tags=["Пользователи"])


class AuthenticationError(ApplicationError):
    def __init__(self, message: str = "Требуется вход в систему") -> None:
        super().__init__(
            status.HTTP_401_UNAUTHORIZED,
            "authentication_required",
            message,
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    if not isinstance(encoded, str):
        return False
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(candidate, bytes.fromhex(digest_hex))
    except (TypeError, ValueError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {key: user[key] for key in ("id", "username", "email", "created_at")}


def _create_session(user_id: int, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(days=SESSION_DAYS)
    database.execute(
        "DELETE FROM user_sessions WHERE expires_at <= %s",
        (now,),
    )
    database.insert(
        """
        INSERT INTO user_sessions (user_id, token_hash, created_at, expires_at)
        VALUES (%s, %s, %s, %s)
        """,
        (user_id, _token_hash(token), now, expires),
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def require_user(
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
) -> Dict[str, Any]:
    if not session_token:
        raise AuthenticationError()
    user = database.fetch_one(
        """
        SELECT users.id, users.username, users.email, users.created_at
        FROM user_sessions
        JOIN users ON users.id = user_sessions.user_id
        WHERE user_sessions.token_hash = %s AND user_sessions.expires_at > %s
        """,
        (_token_hash(session_token), _now()),
    )
    if user is None:
        raise AuthenticationError("Сессия истекла. Войдите снова")
    return user


@router.post("/register", response_model=schemas.User, status_code=201)
def register(data: schemas.RegisterInput, response: Response) -> Dict[str, Any]:
    now = _now()
    try:
        user_id = database.insert(
            """
            INSERT INTO users (username, email, password_hash, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (data.username, data.email, _hash_password(data.password), now),
        )
    except psycopg.IntegrityError as error:
        raise ConflictError(
            "Пользователь с таким логином или email уже существует"
        ) from error
    user = database.fetch_one("SELECT * FROM users WHERE id = %s", (user_id,))
    if user is None:
        raise RuntimeError("Созданный пользователь не найден")
    _create_session(user_id, response)
    return _public_user(user)


@router.post("/login", response_model=schemas.User)
def login(data: schemas.LoginInput, response: Response) -> Dict[str, Any]:
    user = database.fetch_one(
        "SELECT * FROM users WHERE lower(username) = lower(%s)", (data.username,)
    )
    if user is None or not _verify_password(data.password, user["password_hash"]):
        raise AuthenticationError("Неверный логин или пароль")
    _create_session(user["id"], response)
    return _public_user(user)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
) -> Response:
    if session_token:
        database.execute(
            "DELETE FROM user_sessions WHERE token_hash = %s",
            (_token_hash(session_token),),
        )
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=schemas.User)
def current_user(
    user: Annotated[Dict[str, Any], Depends(require_user)],
) -> Dict[str, Any]:
    return user
