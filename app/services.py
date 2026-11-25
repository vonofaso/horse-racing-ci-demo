"""Операции с сущностями и правила предметной области."""

from enum import Enum
from typing import Any, Dict, List, Optional

import psycopg
from psycopg import sql

from app import database, schemas
from app.errors import ConflictError, NotFoundError

ENTITY_NAMES = {
    "owners": "Владелец",
    "horses": "Лошадь",
    "jockeys": "Жокей",
    "competitions": "Состязание",
    "results": "Результат",
}


def _database_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _values(model: Any) -> Dict[str, Any]:
    return {key: _database_value(value) for key, value in model.model_dump().items()}


def get_entity(table: str, entity_id: int) -> Dict[str, Any]:
    row = database.fetch_one(
        sql.SQL("SELECT * FROM {} WHERE id = %s")
        .format(sql.Identifier(table))
        .as_string(),
        (entity_id,),
    )
    if row is None:
        raise NotFoundError(ENTITY_NAMES[table], entity_id)
    return row


def list_entities(table: str) -> List[Dict[str, Any]]:
    return database.fetch_all(
        sql.SQL("SELECT * FROM {} ORDER BY id")
        .format(sql.Identifier(table))
        .as_string()
    )


def _insert_entity(table: str, values: Dict[str, Any]) -> Dict[str, Any]:
    columns = sql.SQL(", ").join(map(sql.Identifier, values))
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in values)
    try:
        entity_id = database.insert(
            sql.SQL("INSERT INTO {} ({}) VALUES ({})")
            .format(sql.Identifier(table), columns, placeholders)
            .as_string(),
            tuple(values.values()),
        )
    except psycopg.IntegrityError as error:
        raise ConflictError("Запись с такими данными уже существует") from error
    return get_entity(table, entity_id)


def _update_entity(
    table: str,
    entity_id: int,
    values: Dict[str, Any],
) -> Dict[str, Any]:
    get_entity(table, entity_id)
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(column)) for column in values
    )
    try:
        database.execute(
            sql.SQL("UPDATE {} SET {} WHERE id = %s")
            .format(sql.Identifier(table), assignments)
            .as_string(),
            (*values.values(), entity_id),
        )
    except psycopg.IntegrityError as error:
        raise ConflictError("Изменение нарушает ограничения данных") from error
    return get_entity(table, entity_id)


def delete_entity(table: str, entity_id: int) -> None:
    get_entity(table, entity_id)
    try:
        database.execute(
            sql.SQL("DELETE FROM {} WHERE id = %s")
            .format(sql.Identifier(table))
            .as_string(),
            (entity_id,),
        )
    except psycopg.IntegrityError as error:
        raise ConflictError(
            "Удаление запрещено: запись используется другими сущностями"
        ) from error


def create_owner(data: schemas.OwnerInput) -> Dict[str, Any]:
    return _insert_entity("owners", _values(data))


def update_owner(entity_id: int, data: schemas.OwnerInput) -> Dict[str, Any]:
    return _update_entity("owners", entity_id, _values(data))


def create_horse(data: schemas.HorseInput) -> Dict[str, Any]:
    get_entity("owners", data.owner_id)
    return _insert_entity("horses", _values(data))


def update_horse(entity_id: int, data: schemas.HorseInput) -> Dict[str, Any]:
    get_entity("owners", data.owner_id)
    return _update_entity("horses", entity_id, _values(data))


def create_jockey(data: schemas.JockeyInput) -> Dict[str, Any]:
    return _insert_entity("jockeys", _values(data))


def update_jockey(entity_id: int, data: schemas.JockeyInput) -> Dict[str, Any]:
    return _update_entity("jockeys", entity_id, _values(data))


def create_competition(data: schemas.CompetitionInput) -> Dict[str, Any]:
    return _insert_entity("competitions", _values(data))


def update_competition(
    entity_id: int,
    data: schemas.CompetitionInput,
) -> Dict[str, Any]:
    return _update_entity("competitions", entity_id, _values(data))


def _check_result_rules(
    data: schemas.ResultInput,
    excluded_result_id: Optional[int] = None,
) -> None:
    get_entity("competitions", data.competition_id)
    get_entity("horses", data.horse_id)
    get_entity("jockeys", data.jockey_id)

    exclusion = " AND id != %s" if excluded_result_id is not None else ""
    extra_parameters = (excluded_result_id,) if excluded_result_id is not None else ()

    horse_result = database.fetch_one(
        sql.SQL("SELECT id FROM results WHERE competition_id = %s AND horse_id = %s {}")
        .format(sql.SQL(exclusion))
        .as_string(),
        (data.competition_id, data.horse_id, *extra_parameters),
    )
    if horse_result is not None:
        raise ConflictError("Лошадь уже имеет результат в этом состязании")

    jockey_result = database.fetch_one(
        sql.SQL(
            "SELECT id FROM results WHERE competition_id = %s AND jockey_id = %s {}"
        )
        .format(sql.SQL(exclusion))
        .as_string(),
        (data.competition_id, data.jockey_id, *extra_parameters),
    )
    if jockey_result is not None:
        raise ConflictError("Жокей уже имеет результат в этом состязании")

    if not data.disqualified:
        position_result = database.fetch_one(
            sql.SQL(
                "SELECT id FROM results WHERE competition_id = %s "
                "AND position = %s AND NOT disqualified {}"
            )
            .format(sql.SQL(exclusion))
            .as_string(),
            (data.competition_id, data.position, *extra_parameters),
        )
        if position_result is not None:
            raise ConflictError("Это место уже занято в данном состязании")


def create_result(data: schemas.ResultInput) -> Dict[str, Any]:
    _check_result_rules(data)
    return _insert_entity("results", _values(data))


def update_result(entity_id: int, data: schemas.ResultInput) -> Dict[str, Any]:
    get_entity("results", entity_id)
    _check_result_rules(data, excluded_result_id=entity_id)
    return _update_entity("results", entity_id, _values(data))


def list_results(competition_id: Optional[int] = None) -> List[Dict[str, Any]]:
    if competition_id is None:
        return database.fetch_all(
            "SELECT * FROM results ORDER BY competition_id, position, id"
        )

    get_entity("competitions", competition_id)
    return database.fetch_all(
        """
        SELECT * FROM results
        WHERE competition_id = %s
        ORDER BY position, id
        """,
        (competition_id,),
    )


def list_horses(name: Optional[str] = None) -> List[Dict[str, Any]]:
    if name is None:
        return list_entities("horses")

    return database.fetch_all(
        "SELECT * FROM horses WHERE name ILIKE %s ORDER BY id",
        (f"%{name}%",),
    )
