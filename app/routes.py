"""HTTP-маршруты для пяти предметных сущностей."""

from typing import List, Optional

from fastapi import APIRouter, Depends, Path, Query, Response, status
from typing_extensions import Annotated

from app import schemas, services
from app.auth import require_user

router = APIRouter(dependencies=[Depends(require_user)])
EntityId = Annotated[int, Path(gt=0)]


@router.post(
    "/owners",
    response_model=schemas.Owner,
    status_code=status.HTTP_201_CREATED,
    tags=["Владельцы"],
    summary="Добавить владельца",
)
def create_owner(data: schemas.OwnerInput):
    return services.create_owner(data)


@router.get(
    "/owners",
    response_model=List[schemas.Owner],
    tags=["Владельцы"],
    summary="Показать всех владельцев",
)
def list_owners():
    return services.list_entities("owners")


@router.get(
    "/owners/{entity_id}",
    response_model=schemas.Owner,
    tags=["Владельцы"],
    summary="Показать владельца",
)
def get_owner(entity_id: EntityId):
    return services.get_entity("owners", entity_id)


@router.put(
    "/owners/{entity_id}",
    response_model=schemas.Owner,
    tags=["Владельцы"],
    summary="Изменить владельца",
)
def update_owner(entity_id: EntityId, data: schemas.OwnerInput):
    return services.update_owner(entity_id, data)


@router.delete(
    "/owners/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Владельцы"],
    summary="Удалить владельца",
)
def delete_owner(entity_id: EntityId) -> Response:
    services.delete_entity("owners", entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/horses",
    response_model=schemas.Horse,
    status_code=status.HTTP_201_CREATED,
    tags=["Лошади"],
    summary="Добавить лошадь",
)
def create_horse(data: schemas.HorseInput):
    return services.create_horse(data)


@router.get(
    "/horses",
    response_model=List[schemas.Horse],
    tags=["Лошади"],
    summary="Показать всех лошадей",
)
def list_horses(
    name: Annotated[Optional[str], Query(min_length=1)] = None,
):
    return services.list_horses(name)


@router.get(
    "/horses/{entity_id}",
    response_model=schemas.Horse,
    tags=["Лошади"],
    summary="Показать лошадь",
)
def get_horse(entity_id: EntityId):
    return services.get_entity("horses", entity_id)


@router.put(
    "/horses/{entity_id}",
    response_model=schemas.Horse,
    tags=["Лошади"],
    summary="Изменить лошадь",
)
def update_horse(entity_id: EntityId, data: schemas.HorseInput):
    return services.update_horse(entity_id, data)


@router.delete(
    "/horses/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Лошади"],
    summary="Удалить лошадь",
)
def delete_horse(entity_id: EntityId) -> Response:
    services.delete_entity("horses", entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/jockeys",
    response_model=schemas.Jockey,
    status_code=status.HTTP_201_CREATED,
    tags=["Жокеи"],
    summary="Добавить жокея",
)
def create_jockey(data: schemas.JockeyInput):
    return services.create_jockey(data)


@router.get(
    "/jockeys",
    response_model=List[schemas.Jockey],
    tags=["Жокеи"],
    summary="Показать всех жокеев",
)
def list_jockeys():
    return services.list_entities("jockeys")


@router.get(
    "/jockeys/{entity_id}",
    response_model=schemas.Jockey,
    tags=["Жокеи"],
    summary="Показать жокея",
)
def get_jockey(entity_id: EntityId):
    return services.get_entity("jockeys", entity_id)


@router.put(
    "/jockeys/{entity_id}",
    response_model=schemas.Jockey,
    tags=["Жокеи"],
    summary="Изменить жокея",
)
def update_jockey(entity_id: EntityId, data: schemas.JockeyInput):
    return services.update_jockey(entity_id, data)


@router.delete(
    "/jockeys/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Жокеи"],
    summary="Удалить жокея",
)
def delete_jockey(entity_id: EntityId) -> Response:
    services.delete_entity("jockeys", entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/competitions",
    response_model=schemas.Competition,
    status_code=status.HTTP_201_CREATED,
    tags=["Состязания"],
    summary="Добавить состязание",
)
def create_competition(data: schemas.CompetitionInput):
    return services.create_competition(data)


@router.get(
    "/competitions",
    response_model=List[schemas.Competition],
    tags=["Состязания"],
    summary="Показать все состязания",
)
def list_competitions():
    return services.list_entities("competitions")


@router.get(
    "/competitions/{entity_id}",
    response_model=schemas.Competition,
    tags=["Состязания"],
    summary="Показать состязание",
)
def get_competition(entity_id: EntityId):
    return services.get_entity("competitions", entity_id)


@router.put(
    "/competitions/{entity_id}",
    response_model=schemas.Competition,
    tags=["Состязания"],
    summary="Изменить состязание",
)
def update_competition(entity_id: EntityId, data: schemas.CompetitionInput):
    return services.update_competition(entity_id, data)


@router.delete(
    "/competitions/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Состязания"],
    summary="Удалить состязание",
)
def delete_competition(entity_id: EntityId) -> Response:
    services.delete_entity("competitions", entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/results",
    response_model=schemas.Result,
    status_code=status.HTTP_201_CREATED,
    tags=["Результаты"],
    summary="Добавить результат",
)
def create_result(data: schemas.ResultInput):
    return services.create_result(data)


@router.get(
    "/results",
    response_model=List[schemas.Result],
    tags=["Результаты"],
    summary="Показать результаты",
)
def list_results(
    competition_id: Annotated[Optional[int], Query(gt=0)] = None,
):
    return services.list_results(competition_id)


@router.get(
    "/results/{entity_id}",
    response_model=schemas.Result,
    tags=["Результаты"],
    summary="Показать результат",
)
def get_result(entity_id: EntityId):
    return services.get_entity("results", entity_id)


@router.put(
    "/results/{entity_id}",
    response_model=schemas.Result,
    tags=["Результаты"],
    summary="Изменить результат",
)
def update_result(entity_id: EntityId, data: schemas.ResultInput):
    return services.update_result(entity_id, data)


@router.delete(
    "/results/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Результаты"],
    summary="Удалить результат",
)
def delete_result(entity_id: EntityId) -> Response:
    services.delete_entity("results", entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
