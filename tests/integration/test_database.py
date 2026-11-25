"""Настоящая PostgreSQL: CRUD, ограничения, транзакции и сохранность."""

from datetime import date

import psycopg
import pytest

from app import database, schemas, services
from app.errors import ConflictError, NotFoundError


@pytest.mark.parametrize(
    "table", ["owners", "horses", "jockeys", "competitions", "results"]
)
def test_entity_crud_persists_between_connections(race, result_data, table):
    inputs = {
        "owners": (
            schemas.OwnerInput,
            {"name": "Новый клуб", "contact": "Контакт"},
            {"contact": "Обновлённый контакт"},
        ),
        "horses": (
            schemas.HorseInput,
            {
                "name": "Ветер",
                "birth_date": "2021-01-01",
                "breed": "Орловская",
                "owner_id": race["owner"]["id"],
            },
            {"breed": "Арабская"},
        ),
        "jockeys": (
            schemas.JockeyInput,
            {"full_name": "Новый жокей", "birth_date": "1995-01-01", "weight_kg": 60},
            {"weight_kg": 59.5},
        ),
        "competitions": (
            schemas.CompetitionInput,
            {
                "name": "Новый кубок",
                "event_date": "2026-10-07",
                "location": "Тула",
                "distance_m": 2000,
            },
            {"status": "completed"},
        ),
        "results": (schemas.ResultInput, result_data, {"time_seconds": 93.9}),
    }
    model, values, changes = inputs[table]
    singular = {
        "owners": "owner",
        "horses": "horse",
        "jockeys": "jockey",
        "competitions": "competition",
        "results": "result",
    }[table]
    created = getattr(services, f"create_{singular}")(model(**values))
    entity_id = created["id"]
    # Каждый вызов помощника открывает новое соединение: виден именно commit.
    assert services.get_entity(table, entity_id) == created
    assert entity_id in [row["id"] for row in services.list_entities(table)]
    updated = getattr(services, f"update_{singular}")(
        entity_id, model(**{**values, **changes})
    )
    for field, expected in changes.items():
        assert updated[field] == expected
    assert services.get_entity(table, entity_id) == updated
    if table == "horses":
        assert updated["birth_date"] == date(2021, 1, 1)
    services.delete_entity(table, entity_id)
    assert entity_id not in [row["id"] for row in services.list_entities(table)]
    with pytest.raises(NotFoundError):
        services.get_entity(table, entity_id)


def test_initialization_is_repeatable_and_does_not_erase_data(race, result_data):
    result = services.create_result(schemas.ResultInput(**result_data))
    before = {table: services.list_entities(table) for table in services.ENTITY_NAMES}
    database.initialize_database()
    database.initialize_database()
    assert {
        table: services.list_entities(table) for table in services.ENTITY_NAMES
    } == before
    assert services.get_entity("results", result["id"]) == result
    info = database.get_database_info()
    assert info["engine"] == "PostgreSQL"
    assert info["schema_version"] == database.SCHEMA_VERSION
    assert database.check_database() is True


@pytest.mark.parametrize(
    "table,field",
    [
        ("horses", "owner_id"),
        ("results", "competition_id"),
        ("results", "horse_id"),
        ("results", "jockey_id"),
    ],
)
def test_foreign_keys_are_enforced_without_service_validation(
    race, result_data, table, field
):
    if table == "horses":
        values = {
            "name": "Ветер",
            "birth_date": "2020-01-01",
            "breed": "Орловская",
            "owner_id": race["owner"]["id"],
        }
    else:
        values = result_data.copy()
    values[field] = 999999
    columns = ", ".join(values)
    placeholders = ", ".join("%s" for _ in values)
    query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    count_before = len(services.list_entities(table))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        database.insert(query, tuple(values.values()))
    assert len(services.list_entities(table)) == count_before
    assert database.check_database() is True


@pytest.mark.parametrize("field", ["horse_id", "jockey_id", "position"])
def test_database_unique_constraints_reject_duplicate_results(race, result_data, field):
    services.create_result(schemas.ResultInput(**result_data))
    candidate = {
        **result_data,
        "horse_id": race["horses"][1]["id"],
        "jockey_id": race["jockeys"][1]["id"],
        "position": 2,
    }
    candidate[field] = result_data[field]
    with pytest.raises(psycopg.errors.UniqueViolation):
        database.insert(
            "INSERT INTO results "
            "(competition_id, horse_id, jockey_id, position, time_seconds) "
            "VALUES (%s, %s, %s, %s, %s)",
            tuple(candidate.values()),
        )
    assert len(services.list_entities("results")) == 1


@pytest.mark.parametrize(
    "table,field,value",
    [
        ("owners", "name", " "),
        ("horses", "name", " "),
        ("horses", "breed", " "),
        ("jockeys", "full_name", " "),
        ("jockeys", "weight_kg", 0),
        ("competitions", "distance_m", -1),
        ("competitions", "status", "unknown"),
        ("results", "position", 0),
        ("results", "time_seconds", -1),
        ("results", "disqualification_reason", "Нарушение"),
    ],
)
def test_database_checks_reject_invalid_updates(race, result_data, table, field, value):
    result = services.create_result(schemas.ResultInput(**result_data))
    rows = {
        "owners": race["owner"],
        "horses": race["horses"][0],
        "jockeys": race["jockeys"][0],
        "competitions": race["competition"],
        "results": result,
    }
    row = rows[table]
    with pytest.raises(psycopg.errors.CheckViolation):
        database.execute(
            f"UPDATE {table} SET {field} = %s WHERE id = %s", (value, row["id"])
        )
    assert services.get_entity(table, row["id"]) == row


@pytest.mark.parametrize("table", ["owners", "horses", "jockeys", "competitions"])
def test_referenced_entity_cannot_be_deleted(race, result_data, table):
    result = services.create_result(schemas.ResultInput(**result_data))
    ids = {
        "owners": race["owner"]["id"],
        "horses": race["horses"][0]["id"],
        "jockeys": race["jockeys"][0]["id"],
        "competitions": race["competition"]["id"],
    }
    with pytest.raises(ConflictError, match="используется"):
        services.delete_entity(table, ids[table])
    assert services.get_entity(table, ids[table])["id"] == ids[table]
    services.delete_entity("results", result["id"])
    if table == "owners":
        for horse in race["horses"]:
            services.delete_entity("horses", horse["id"])
    services.delete_entity(table, ids[table])
    with pytest.raises(NotFoundError):
        services.get_entity(table, ids[table])


@pytest.mark.parametrize("field", ["horse_id", "jockey_id", "position"])
def test_result_update_conflict_leaves_original_data_unchanged(
    race, result_data, field
):
    first = services.create_result(schemas.ResultInput(**result_data))
    values = {
        **result_data,
        "horse_id": race["horses"][1]["id"],
        "jockey_id": race["jockeys"][1]["id"],
        "position": 2,
    }
    second = services.create_result(schemas.ResultInput(**values))
    with pytest.raises(ConflictError):
        services.update_result(
            second["id"], schemas.ResultInput(**{**values, field: first[field]})
        )
    assert services.get_entity("results", second["id"]) == second


def test_disqualification_frees_position_and_requires_reason(race, result_data):
    first = services.create_result(schemas.ResultInput(**result_data))
    disqualified = {
        **result_data,
        "disqualified": True,
        "disqualification_reason": "Нарушение",
    }
    services.update_result(first["id"], schemas.ResultInput(**disqualified))
    second_values = {
        **result_data,
        "horse_id": race["horses"][1]["id"],
        "jockey_id": race["jockeys"][1]["id"],
    }
    second = services.create_result(schemas.ResultInput(**second_values))
    assert second["position"] == first["position"]
    with pytest.raises(ConflictError):
        services.update_result(first["id"], schemas.ResultInput(**result_data))
    assert services.get_entity("results", first["id"])["disqualified"] is True


def test_results_are_filtered_and_sorted_and_participants_can_race_again(
    race, result_data
):
    other = services.create_competition(
        schemas.CompetitionInput(
            name="Другой кубок",
            event_date="2026-02-01",
            location="Тула",
            distance_m=1000,
        )
    )
    services.create_result(
        schemas.ResultInput(**{**result_data, "competition_id": other["id"]})
    )
    second = services.create_result(
        schemas.ResultInput(
            **{
                **result_data,
                "horse_id": race["horses"][1]["id"],
                "jockey_id": race["jockeys"][1]["id"],
                "position": 2,
            }
        )
    )
    first = services.create_result(schemas.ResultInput(**result_data))
    assert [row["id"] for row in services.list_results(race["competition"]["id"])] == [
        first["id"],
        second["id"],
    ]
    assert len(services.list_results()) == 3
    with pytest.raises(NotFoundError):
        services.list_results(999999)


def test_horse_search_matches_cyrillic_case_insensitively(race):
    assert [horse["name"] for horse in services.list_horses("бУР")] == ["Буран"]
    assert services.list_horses("Несуществующая") == []
    assert len(services.list_horses()) == 2


def test_user_supplied_sql_is_stored_as_text(race):
    name = "Клуб'); DROP TABLE owners; --"
    owner = services.create_owner(schemas.OwnerInput(name=name))
    assert services.get_entity("owners", owner["id"])["name"] == name
    assert services.list_horses("' OR 1=1 --") == []
    assert len(services.list_entities("owners")) == 2


def test_transaction_rolls_back_all_writes_on_error(postgres_database):
    with pytest.raises(
        psycopg.errors.CheckViolation
    ), database.connect_database() as connection:
        connection.execute(
            "INSERT INTO owners (name) VALUES (%s)", ("Не должен сохраниться",)
        )
        connection.execute("INSERT INTO owners (name) VALUES (%s)", (" ",))
    assert services.list_entities("owners") == []
    assert (
        services.create_owner(schemas.OwnerInput(name="Сохранится"))["name"]
        == "Сохранится"
    )


def test_database_helpers_handle_empty_reads_and_row_counts(postgres_database):
    assert database.fetch_one("SELECT * FROM owners WHERE id = %s", (999,)) is None
    assert database.fetch_all("SELECT * FROM owners") == []
    entity_id = database.insert("INSERT INTO owners (name) VALUES (%s);", ("Клуб",))
    assert (
        database.execute(
            "UPDATE owners SET contact = %s WHERE id = %s", ("Телефон", entity_id)
        )
        == 1
    )
    assert database.execute("DELETE FROM owners WHERE id = %s", (999,)) == 0
    assert database.execute("DELETE FROM owners WHERE id = %s", (entity_id,)) == 1
