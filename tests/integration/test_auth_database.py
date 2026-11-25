"""HTTP, настоящая PostgreSQL и жизненный цикл cookie-сессии."""

import hashlib
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from app import auth, database

CREDENTIALS = {
    "username": "rider",
    "email": "rider@example.test",
    "password": "Password-2026",
}


@pytest.mark.parametrize(
    "resource", ["owners", "horses", "jockeys", "competitions", "results"]
)
@pytest.mark.parametrize(
    "method,suffix",
    [("GET", ""), ("GET", "/1"), ("POST", ""), ("PUT", "/1"), ("DELETE", "/1")],
)
def test_all_domain_routes_require_session(client, resource, method, suffix):
    response = client.request(method, f"/{resource}{suffix}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_register_persists_hashes_and_session_cookie(client):
    response = client.post("/auth/register", json=CREDENTIALS)
    assert response.status_code == 201
    assert set(response.json()) == {"id", "username", "email", "created_at"}
    user = database.fetch_one("SELECT * FROM users")
    assert user["password_hash"] != CREDENTIALS["password"]
    assert auth._verify_password(CREDENTIALS["password"], user["password_hash"])
    token = client.cookies[auth.SESSION_COOKIE]
    session = database.fetch_one("SELECT * FROM user_sessions")
    assert session["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert session["token_hash"] != token
    assert session["user_id"] == user["id"]
    assert session["expires_at"] - session["created_at"] == timedelta(days=7)
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert "Max-Age=604800" in response.headers["set-cookie"]
    assert client.get("/auth/me").json() == response.json()


@pytest.mark.parametrize("field", ["username", "email"])
def test_duplicate_registration_is_case_insensitive(client, field):
    assert client.post("/auth/register", json=CREDENTIALS).status_code == 201
    candidate = {
        **CREDENTIALS,
        "username": "different",
        "email": "different@example.test",
        field: CREDENTIALS[field].upper(),
    }
    response = client.post("/auth/register", json=candidate)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert len(database.fetch_all("SELECT * FROM users")) == 1
    assert len(database.fetch_all("SELECT * FROM user_sessions")) == 1


def test_login_failure_does_not_reveal_whether_user_exists(client):
    client.post("/auth/register", json=CREDENTIALS)
    client.post("/auth/logout")
    unknown = client.post(
        "/auth/login", json={"username": "unknown", "password": "wrong"}
    )
    wrong = client.post(
        "/auth/login", json={"username": CREDENTIALS["username"], "password": "wrong"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert database.fetch_all("SELECT * FROM user_sessions") == []
    assert auth.SESSION_COOKIE not in client.cookies
    logged_in = client.post(
        "/auth/login", json={"username": "RIDER", "password": CREDENTIALS["password"]}
    )
    assert logged_in.status_code == 200
    assert client.get("/owners").status_code == 200


def test_logout_revokes_only_current_session_and_replay_is_rejected(client):
    client.post("/auth/register", json=CREDENTIALS)
    first_token = client.cookies[auth.SESSION_COOKIE]
    client.post(
        "/auth/login", json={"username": "rider", "password": CREDENTIALS["password"]}
    )
    second_token = client.cookies[auth.SESSION_COOKIE]
    assert first_token != second_token
    response = client.post("/auth/logout")
    assert response.status_code == 204
    assert auth.SESSION_COOKIE not in client.cookies
    assert client.get("/owners").status_code == 401
    assert len(database.fetch_all("SELECT * FROM user_sessions")) == 1
    client.cookies.set(auth.SESSION_COOKIE, second_token)
    assert client.get("/auth/me").status_code == 401
    client.cookies.set(auth.SESSION_COOKIE, first_token)
    assert client.get("/auth/me").status_code == 200


def test_expired_session_rejected_and_cleaned_at_next_login(client):
    client.post("/auth/register", json=CREDENTIALS)
    token = client.cookies[auth.SESSION_COOKIE]
    database.execute(
        "UPDATE user_sessions SET expires_at = %s",
        (datetime.now(timezone.utc) - timedelta(seconds=1),),
    )
    assert client.get("/auth/me").status_code == 401
    assert client.get("/horses").status_code == 401
    assert (
        client.post(
            "/auth/login",
            json={"username": "rider", "password": CREDENTIALS["password"]},
        ).status_code
        == 200
    )
    sessions = database.fetch_all("SELECT * FROM user_sessions")
    assert len(sessions) == 1
    assert sessions[0]["token_hash"] != hashlib.sha256(token.encode()).hexdigest()


def test_session_foreign_key_and_cascade(client):
    response = client.post("/auth/register", json=CREDENTIALS)
    session = database.fetch_one("SELECT * FROM user_sessions")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        database.execute("UPDATE user_sessions SET user_id = %s", (999999,))
    assert database.fetch_one("SELECT * FROM user_sessions") == session
    database.execute("DELETE FROM users WHERE id = %s", (response.json()["id"],))
    assert database.fetch_all("SELECT * FROM user_sessions") == []
    assert client.get("/auth/me").status_code == 401
