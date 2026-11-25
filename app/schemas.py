"""Pydantic-схемы входных и выходных данных HTTP API."""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from typing_extensions import Annotated

Name = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
OptionalText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=40,
        pattern=r"^[A-Za-zА-Яа-яЁё0-9_.-]+$",
    ),
]


def _not_in_future(value: date) -> date:
    if value > date.today():
        raise ValueError("дата не может находиться в будущем")
    return value


class OwnerInput(BaseModel):
    name: Name
    contact: Optional[OptionalText] = None


class Owner(OwnerInput):
    id: int


class HorseInput(BaseModel):
    name: Name
    birth_date: date
    breed: Name
    owner_id: int = Field(gt=0)

    _validate_birth_date = field_validator("birth_date")(_not_in_future)


class Horse(HorseInput):
    id: int


class JockeyInput(BaseModel):
    full_name: Name
    birth_date: date
    weight_kg: float = Field(gt=0, le=200, allow_inf_nan=False)

    _validate_birth_date = field_validator("birth_date")(_not_in_future)


class Jockey(JockeyInput):
    id: int


class CompetitionStatus(str, Enum):
    PLANNED = "planned"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CompetitionInput(BaseModel):
    name: Name
    event_date: date
    location: Name
    distance_m: int = Field(gt=0)
    status: CompetitionStatus = CompetitionStatus.PLANNED
    prize_fund_rub: int = Field(default=0, ge=0)


class Competition(CompetitionInput):
    id: int


class ResultInput(BaseModel):
    competition_id: int = Field(gt=0)
    horse_id: int = Field(gt=0)
    jockey_id: int = Field(gt=0)
    position: int = Field(gt=0)
    time_seconds: float = Field(gt=0, allow_inf_nan=False)
    disqualified: bool = False
    disqualification_reason: Optional[OptionalText] = None

    @model_validator(mode="after")
    def validate_disqualification(self) -> "ResultInput":
        if self.disqualified and self.disqualification_reason is None:
            raise ValueError("для дисквалификации необходимо указать причину")
        if not self.disqualified and self.disqualification_reason is not None:
            raise ValueError("причина допустима только для дисквалификации")
        return self


class Result(ResultInput):
    id: int


class RegisterInput(BaseModel):
    username: Username
    email: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=5, max_length=254),
    ]
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.lower()
        local, separator, domain = normalized.partition("@")
        labels = domain.split(".")
        if (
            not separator
            or not local
            or "@" in domain
            or len(labels) < 2
            or not all(labels)
            or any(char.isspace() for char in normalized)
        ):
            raise ValueError("укажите корректный адрес электронной почты")
        return normalized


class LoginInput(BaseModel):
    username: Username
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class User(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime
