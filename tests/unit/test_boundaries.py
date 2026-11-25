"""Точные границы и обязательные отказы, чувствительные к мутациям."""

import math
from datetime import date
from unittest.mock import Mock

import pytest
from fastapi import Response
from pydantic import ValidationError

from app import auth, database, schemas
from app.config import _read_bool, _read_port


@pytest.mark.parametrize("size", [1, 200])
def test_name_accepts_inclusive_boundaries(size):
    assert schemas.OwnerInput(name="x" * size).name == "x" * size


@pytest.mark.parametrize("size", [1, 500])
def test_contact_accepts_inclusive_boundaries(size):
    assert schemas.OwnerInput(name="Клуб", contact="x" * size).contact == "x" * size


@pytest.mark.parametrize("contact", ["", " ", "x" * 501])
def test_contact_rejects_outside_boundaries(contact):
    with pytest.raises(ValidationError):
        schemas.OwnerInput(name="Клуб", contact=contact)


@pytest.mark.parametrize("size", [3, 40])
def test_username_accepts_inclusive_boundaries(size):
    assert schemas.LoginInput(username="x" * size, password="x").username == "x" * size


@pytest.mark.parametrize("username", ["", "x" * 2, "x" * 41, "a@b", "a b"])
def test_username_rejects_outside_boundaries(username):
    with pytest.raises(ValidationError):
        schemas.LoginInput(username=username, password="x")


@pytest.mark.parametrize("size", [8, 128])
def test_password_accepts_inclusive_boundaries(size):
    assert (
        len(
            schemas.RegisterInput(
                username="user", email="a@b.c", password="x" * size
            ).password
        )
        == size
    )


@pytest.mark.parametrize("size", [0, 7, 129])
def test_password_rejects_outside_boundaries(size):
    with pytest.raises(ValidationError):
        schemas.RegisterInput(username="user", email="a@b.c", password="x" * size)


@pytest.mark.parametrize("email", ["a@b.", "a@b..c", "a@@b.c", "a b@c.d", "a@b.c@d"])
def test_malformed_email_is_rejected(email):
    with pytest.raises(ValidationError):
        schemas.RegisterInput(username="user", email=email, password="password")


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("field", ["weight_kg", "time_seconds"])
def test_non_finite_numbers_are_rejected(field, value):
    with pytest.raises(ValidationError):
        if field == "weight_kg":
            schemas.JockeyInput(
                full_name="Жокей", birth_date=date.today(), weight_kg=value
            )
        else:
            schemas.ResultInput(
                competition_id=1,
                horse_id=1,
                jockey_id=1,
                position=1,
                time_seconds=value,
            )


def test_small_positive_values_are_valid():
    assert (
        schemas.JockeyInput(
            full_name="Жокей", birth_date=date.today(), weight_kg=0.001
        ).weight_kg
        == 0.001
    )
    assert (
        schemas.ResultInput(
            competition_id=1, horse_id=1, jockey_id=1, position=1, time_seconds=0.001
        ).time_seconds
        == 0.001
    )


@pytest.mark.parametrize("value", [1, 65535])
def test_port_accepts_inclusive_boundaries(monkeypatch, value):
    monkeypatch.setenv("TEST_PORT", str(value))
    assert _read_port("TEST_PORT", 8000) == value


@pytest.mark.parametrize("value", ["0", "65536", "-1", "abc", "1.5", ""])
def test_port_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("TEST_PORT", value)
    with pytest.raises(ValueError):
        _read_port("TEST_PORT", 8000)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        (" YES ", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("OFF", False),
    ],
)
def test_boolean_config_accepts_only_documented_values(monkeypatch, value, expected):
    monkeypatch.setenv("TEST_BOOL", value)
    assert _read_bool("TEST_BOOL", False) is expected


def test_invalid_boolean_config_rejected(monkeypatch):
    monkeypatch.setenv("TEST_BOOL", "sometimes")
    with pytest.raises(ValueError):
        _read_bool("TEST_BOOL", False)


@pytest.mark.parametrize("encoded", [None, 123, b"hash"])
def test_wrong_password_hash_type_is_rejected(encoded):
    assert auth._verify_password("password", encoded) is False


def test_session_expiry_check_uses_same_frozen_instant(monkeypatch):
    now = auth._now()
    monkeypatch.setattr(auth, "_now", lambda: now)
    fetch = Mock(return_value=None)
    monkeypatch.setattr(database, "fetch_one", fetch)
    with pytest.raises(auth.AuthenticationError):
        auth.require_user("token")
    query, parameters = fetch.call_args.args
    assert "expires_at > %s" in query
    assert parameters[1] == now


def test_register_missing_inserted_user_never_creates_session(monkeypatch):
    monkeypatch.setattr(database, "insert", Mock(return_value=1))
    monkeypatch.setattr(database, "fetch_one", Mock(return_value=None))
    create = Mock()
    monkeypatch.setattr(auth, "_create_session", create)
    with pytest.raises(RuntimeError, match="не найден"):
        auth.register(
            schemas.RegisterInput(username="user", email="a@b.c", password="password"),
            Response(),
        )
    create.assert_not_called()
