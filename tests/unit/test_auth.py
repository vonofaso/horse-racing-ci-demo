"""Хеширование пароля, создание и проверка сессий без PostgreSQL."""

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi import Response

from app import auth, database, schemas


@pytest.fixture
def user():
    return {
        "id": 4,
        "username": "rider",
        "email": "rider@example.test",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "password_hash": auth._hash_password("Password-2026"),
    }


def test_password_hash_uses_required_algorithm_salt_and_iterations():
    password = "Сложный-пароль-2026"
    first, second = auth._hash_password(password), auth._hash_password(password)
    algorithm, iterations, salt, digest = first.split("$")
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) >= 310_000
    assert len(bytes.fromhex(salt)) == 16
    assert len(bytes.fromhex(digest)) == 32
    assert first != second
    assert password not in first
    assert auth._verify_password(password, first)
    assert not auth._verify_password("неверный", first)


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "broken",
        "sha1$310000$00$00",
        "pbkdf2_sha256$bad$00$00",
        "pbkdf2_sha256$0$00$00",
        "pbkdf2_sha256$1$zz$00",
        "pbkdf2_sha256$1$00$zz",
    ],
)
def test_malformed_password_hash_returns_false(encoded):
    assert auth._verify_password("password", encoded) is False


def test_session_stores_hash_and_sets_lifetime_and_cookie_flags(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(auth, "_now", lambda: now)
    token_generator = Mock(return_value="random-session-token")
    monkeypatch.setattr(auth.secrets, "token_urlsafe", token_generator)
    insert, execute = Mock(), Mock()
    monkeypatch.setattr(database, "insert", insert)
    monkeypatch.setattr(database, "execute", execute)
    response = Response()
    auth._create_session(4, response)
    token_generator.assert_called_once_with(32)
    parameters = insert.call_args.args[1]
    assert parameters == (
        4,
        hashlib.sha256(b"random-session-token").hexdigest(),
        now,
        now + timedelta(days=7),
    )
    assert "random-session-token" not in parameters
    execute.assert_called_once()
    assert execute.call_args.args[1] == (now,)
    cookie = response.headers["set-cookie"]
    for flag in ("HttpOnly", "SameSite=lax", "Max-Age=604800", "Path=/"):
        assert flag in cookie


@pytest.mark.parametrize("token", [None, ""])
def test_missing_session_rejects_access_without_database_query(monkeypatch, token):
    fetch = Mock()
    monkeypatch.setattr(database, "fetch_one", fetch)
    with pytest.raises(auth.AuthenticationError):
        auth.require_user(token)
    fetch.assert_not_called()


def test_invalid_or_expired_session_rejects_access(monkeypatch):
    fetch = Mock(return_value=None)
    monkeypatch.setattr(database, "fetch_one", fetch)
    with pytest.raises(auth.AuthenticationError, match="истекла"):
        auth.require_user("unknown")
    query, parameters = fetch.call_args.args
    assert "expires_at > %s" in query
    assert parameters[0] == hashlib.sha256(b"unknown").hexdigest()


def test_valid_session_returns_current_user(monkeypatch, user):
    public = auth._public_user(user)
    monkeypatch.setattr(database, "fetch_one", Mock(return_value=public))
    assert auth.require_user("token") == public
    assert "password_hash" not in public


@pytest.mark.parametrize("known_user", [False, True])
def test_login_uses_same_error_for_unknown_user_and_wrong_password(
    monkeypatch, user, known_user
):
    monkeypatch.setattr(
        database, "fetch_one", Mock(return_value=user if known_user else None)
    )
    create_session = Mock()
    monkeypatch.setattr(auth, "_create_session", create_session)
    with pytest.raises(auth.AuthenticationError) as error:
        auth.login(schemas.LoginInput(username="rider", password="wrong"), Response())
    assert error.value.message == "Неверный логин или пароль"
    assert error.value.status_code == 401
    create_session.assert_not_called()


def test_successful_login_returns_no_secrets_and_creates_session(monkeypatch, user):
    monkeypatch.setattr(database, "fetch_one", Mock(return_value=user))
    create_session = Mock()
    monkeypatch.setattr(auth, "_create_session", create_session)
    response = Response()
    public = auth.login(
        schemas.LoginInput(username="rider", password="Password-2026"), response
    )
    assert public == auth._public_user(user)
    create_session.assert_called_once_with(user["id"], response)
