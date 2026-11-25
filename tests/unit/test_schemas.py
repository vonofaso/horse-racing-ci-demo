"""Граничные значения и правила валидации из раздела 4.3 ТЗ."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app import schemas

OWNER = {"name": "Клуб", "contact": "+7 900"}
HORSE = {
    "name": "Буран",
    "birth_date": "2020-01-01",
    "breed": "Орловская",
    "owner_id": 1,
}
JOCKEY = {"full_name": "Иван Петров", "birth_date": "1990-01-01", "weight_kg": 58.5}
COMPETITION = {
    "name": "Кубок",
    "event_date": "2026-01-01",
    "location": "Москва",
    "distance_m": 1600,
}
RESULT = {
    "competition_id": 1,
    "horse_id": 2,
    "jockey_id": 3,
    "position": 1,
    "time_seconds": 94.2,
}
REGISTER = {
    "username": "rider",
    "email": "rider@example.test",
    "password": "Password-2026",
}


@pytest.mark.parametrize(
    "model,payload,field",
    [
        (schemas.OwnerInput, OWNER, "name"),
        (schemas.HorseInput, HORSE, "name"),
        (schemas.HorseInput, HORSE, "breed"),
        (schemas.JockeyInput, JOCKEY, "full_name"),
        (schemas.CompetitionInput, COMPETITION, "name"),
        (schemas.CompetitionInput, COMPETITION, "location"),
    ],
)
@pytest.mark.parametrize("invalid", ["   ", "x" * 201])
def test_names_reject_blank_and_overlong_values(model, payload, field, invalid):
    with pytest.raises(ValidationError) as error:
        model(**{**payload, field: invalid})
    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    "model,payload,field",
    [
        (schemas.HorseInput, HORSE, "owner_id"),
        (schemas.JockeyInput, JOCKEY, "weight_kg"),
        (schemas.CompetitionInput, COMPETITION, "distance_m"),
        *[(schemas.ResultInput, RESULT, field) for field in RESULT],
    ],
)
@pytest.mark.parametrize("invalid", [0, -1])
def test_numeric_fields_must_be_positive(model, payload, field, invalid):
    with pytest.raises(ValidationError) as error:
        model(**{**payload, field: invalid})
    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    "model,payload", [(schemas.HorseInput, HORSE), (schemas.JockeyInput, JOCKEY)]
)
def test_birth_date_accepts_today_but_rejects_tomorrow(model, payload):
    today = date.today()
    assert model(**{**payload, "birth_date": today}).birth_date == today
    with pytest.raises(ValidationError, match="будущем"):
        model(**{**payload, "birth_date": today + timedelta(days=1)})


def test_jockey_weight_upper_boundary():
    assert schemas.JockeyInput(**{**JOCKEY, "weight_kg": 200}).weight_kg == 200
    with pytest.raises(ValidationError):
        schemas.JockeyInput(**{**JOCKEY, "weight_kg": 200.01})


@pytest.mark.parametrize("status", list(schemas.CompetitionStatus))
def test_all_competition_statuses_are_accepted(status):
    assert schemas.CompetitionInput(**COMPETITION, status=status.value).status == status


def test_unknown_status_is_rejected_and_default_is_planned():
    assert (
        schemas.CompetitionInput(**COMPETITION).status
        == schemas.CompetitionStatus.PLANNED
    )
    with pytest.raises(ValidationError):
        schemas.CompetitionInput(**COMPETITION, status="unknown")


@pytest.mark.parametrize(
    "disqualified,reason", [(True, None), (True, " "), (False, "Нарушение")]
)
def test_inconsistent_disqualification_is_rejected(disqualified, reason):
    with pytest.raises(ValidationError):
        schemas.ResultInput(
            **RESULT, disqualified=disqualified, disqualification_reason=reason
        )


def test_valid_disqualification_and_text_normalization():
    result = schemas.ResultInput(
        **RESULT, disqualified=True, disqualification_reason="  Нарушение  "
    )
    assert result.disqualification_reason == "Нарушение"
    assert schemas.ResultInput(**RESULT).disqualification_reason is None
    owner = schemas.OwnerInput(name="  Клуб  ", contact="  +7 900  ")
    assert owner.model_dump() == OWNER
    assert schemas.OwnerInput(name="Клуб").contact is None


@pytest.mark.parametrize(
    "email", ["invalid", "@example.test", "rider@example", "rider@.test"]
)
def test_registration_rejects_invalid_email(email):
    with pytest.raises(ValidationError):
        schemas.RegisterInput(**{**REGISTER, "email": email})


@pytest.mark.parametrize(
    "field,value",
    [
        ("username", "ab"),
        ("username", "bad user"),
        ("password", "short"),
        ("password", "x" * 129),
    ],
)
def test_registration_rejects_invalid_credentials(field, value):
    with pytest.raises(ValidationError):
        schemas.RegisterInput(**{**REGISTER, field: value})


def test_registration_normalizes_email_and_username():
    user = schemas.RegisterInput(
        **{**REGISTER, "username": "  Всадник_1  ", "email": " RIDER@EXAMPLE.TEST "}
    )
    assert user.username == "Всадник_1"
    assert user.email == "rider@example.test"
