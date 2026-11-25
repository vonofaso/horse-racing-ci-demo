"""Бизнес-правила сервиса с подменой только границы базы данных."""

from unittest.mock import Mock

import psycopg
import pytest

from app import database, schemas, services
from app.errors import ConflictError, NotFoundError


@pytest.fixture
def db(monkeypatch):
    mocks = {}
    for name in ("fetch_one", "fetch_all", "insert", "execute"):
        mocks[name] = Mock()
        monkeypatch.setattr(database, name, mocks[name])
    return mocks


@pytest.fixture
def result():
    return schemas.ResultInput(
        competition_id=10, horse_id=20, jockey_id=30, position=1, time_seconds=94.2
    )


@pytest.mark.parametrize("table,label", services.ENTITY_NAMES.items())
def test_missing_entity_has_domain_error(db, table, label):
    db["fetch_one"].return_value = None
    with pytest.raises(NotFoundError) as error:
        services.get_entity(table, 42)
    assert error.value.status_code == 404
    assert error.value.code == "not_found"
    assert label in error.value.message
    assert "42" in error.value.message


@pytest.mark.parametrize("operation", ["create", "update"])
def test_horse_with_missing_owner_is_not_written(db, operation):
    db["fetch_one"].return_value = None
    horse = schemas.HorseInput(
        name="Буран", birth_date="2020-01-01", breed="Орловская", owner_id=999
    )
    with pytest.raises(NotFoundError, match="Владелец"):
        if operation == "create":
            services.create_horse(horse)
        else:
            services.update_horse(1, horse)
    db["insert"].assert_not_called()
    db["execute"].assert_not_called()


@pytest.mark.parametrize(
    "missing,label", [(0, "Состязание"), (1, "Лошадь"), (2, "Жокей")]
)
def test_result_with_missing_reference_is_not_written(db, result, missing, label):
    db["fetch_one"].side_effect = [{"id": 1}] * missing + [None]
    with pytest.raises(NotFoundError, match=label):
        services.create_result(result)
    db["insert"].assert_not_called()


@pytest.mark.parametrize(
    "conflict_index,message", [(0, "Лошадь"), (1, "Жокей"), (2, "место")]
)
@pytest.mark.parametrize("updating", [False, True])
def test_duplicate_participant_or_position_rejects_write(
    db, result, conflict_index, message, updating
):
    references = [{"id": 1}] * (4 if updating else 3)
    db["fetch_one"].side_effect = references + [None] * conflict_index + [{"id": 99}]
    with pytest.raises(ConflictError, match=message):
        if updating:
            services.update_result(7, result)
        else:
            services.create_result(result)
    db["insert"].assert_not_called()
    db["execute"].assert_not_called()


def test_disqualified_participant_skips_position_conflict_check(db, result):
    data = schemas.ResultInput(
        **{
            **result.model_dump(),
            "disqualified": True,
            "disqualification_reason": "Нарушение",
        }
    )
    db["fetch_one"].side_effect = [{"id": 1}] * 3 + [None, None] + [{"id": 8}]
    db["insert"].return_value = 8
    assert services.create_result(data) == {"id": 8}
    queries = [call.args[0] for call in db["fetch_one"].call_args_list]
    assert not any("position = %s" in query for query in queries)
    db["insert"].assert_called_once()


def test_updating_result_excludes_itself_from_all_uniqueness_checks(db, result):
    db["fetch_one"].side_effect = [{"id": 7}] * 4 + [None] * 3 + [{"id": 7}] * 2
    assert services.update_result(7, result) == {"id": 7}
    conflict_calls = db["fetch_one"].call_args_list[4:7]
    assert len(conflict_calls) == 3
    for call in conflict_calls:
        assert "AND id != %s" in call.args[0]
        assert call.args[1][-1] == 7
    db["execute"].assert_called_once()


@pytest.mark.parametrize(
    "operation,message",
    [
        ("insert", "уже существует"),
        ("update", "ограничения"),
        ("delete", "используется"),
    ],
)
def test_database_integrity_errors_become_conflicts(db, operation, message):
    db["fetch_one"].return_value = {"id": 1}
    failure = psycopg.IntegrityError("constraint failed")
    db["insert" if operation == "insert" else "execute"].side_effect = failure
    with pytest.raises(ConflictError, match=message) as error:
        if operation == "insert":
            services.create_owner(schemas.OwnerInput(name="Клуб"))
        elif operation == "update":
            services.update_owner(1, schemas.OwnerInput(name="Клуб"))
        else:
            services.delete_entity("owners", 1)
    assert error.value.__cause__ is failure


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_missing_entity_cannot_be_changed(db, operation):
    db["fetch_one"].return_value = None
    with pytest.raises(NotFoundError):
        if operation == "update":
            services.update_owner(42, schemas.OwnerInput(name="Клуб"))
        else:
            services.delete_entity("owners", 42)
    db["execute"].assert_not_called()


def test_owner_values_are_passed_as_sql_parameters(db):
    name = "Клуб'); DROP TABLE owners; --"
    db["insert"].return_value = 3
    db["fetch_one"].return_value = {"id": 3, "name": name, "contact": None}
    assert services.create_owner(schemas.OwnerInput(name=name))["name"] == name
    query, parameters = db["insert"].call_args.args
    assert name not in query
    assert parameters == (name, None)


def test_competition_status_is_serialized_for_database(db):
    db["insert"].return_value = 1
    db["fetch_one"].return_value = {"id": 1}
    services.create_competition(
        schemas.CompetitionInput(
            name="Кубок",
            event_date="2026-01-01",
            location="Москва",
            distance_m=1000,
            status="completed",
        )
    )
    values = db["insert"].call_args.args[1]
    assert values[-2:] == ("completed", 0)


def test_horse_search_uses_parameterized_case_insensitive_query(db):
    search = "бур' OR 1=1 --"
    db["fetch_all"].return_value = []
    assert services.list_horses(search) == []
    query, parameters = db["fetch_all"].call_args.args
    assert "ILIKE %s" in query
    assert search not in query
    assert parameters == (f"%{search}%",)


@pytest.mark.parametrize("competition_id", [None, 10])
def test_results_listing_and_filter(db, competition_id):
    db["fetch_all"].return_value = [{"id": 5}]
    assert services.list_results(competition_id) == [{"id": 5}]
    query = db["fetch_all"].call_args.args[0]
    assert "ORDER BY" in query
    if competition_id is None:
        db["fetch_one"].assert_not_called()
    else:
        assert db["fetch_all"].call_args.args[1] == (10,)
        db["fetch_one"].assert_called_once()
