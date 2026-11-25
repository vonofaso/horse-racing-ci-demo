"""Проверка миграций на чистой и заполненной PostgreSQL-схеме."""

import psycopg

from app.migrations import migrate


def test_clean_database_gets_four_migrations(migration_database):
    assert migrate(migration_database) == ["001", "002", "003", "004"]
    with psycopg.connect(migration_database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            )
        }
    assert {"owners", "horses", "results", "users", "schema_migrations"} <= tables
    assert migrate(migration_database) == ["001", "002", "003", "004"]


def test_upgrade_preserves_existing_data(migration_database):
    assert migrate(migration_database, target_version="001") == ["001"]
    with psycopg.connect(migration_database) as connection:
        owner_id = connection.execute(
            "INSERT INTO owners (name) VALUES ('Клуб') RETURNING id"
        ).fetchone()[0]
        horse_id = connection.execute(
            "INSERT INTO horses (name, birth_date, breed, owner_id) "
            "VALUES ('Буран', '2020-01-01', 'Орловская', %s) RETURNING id",
            (owner_id,),
        ).fetchone()[0]

    assert migrate(migration_database) == ["001", "002", "003", "004"]
    with psycopg.connect(migration_database) as connection:
        assert connection.execute(
            "SELECT name FROM owners WHERE id = %s", (owner_id,)
        ).fetchone() == ("Клуб",)
        assert connection.execute(
            "SELECT name, owner_id FROM horses WHERE id = %s", (horse_id,)
        ).fetchone() == ("Буран", owner_id)


def test_prize_fund_migration_keeps_existing_competition(migration_database):
    assert migrate(migration_database, target_version="003") == ["001", "002", "003"]
    with psycopg.connect(migration_database) as connection:
        competition_id = connection.execute(
            "INSERT INTO competitions (name, event_date, location, distance_m) "
            "VALUES ('Кубок', '2026-01-01', 'Москва', 1600) RETURNING id"
        ).fetchone()[0]

    assert migrate(migration_database) == ["001", "002", "003", "004"]
    with psycopg.connect(migration_database) as connection:
        assert connection.execute(
            "SELECT name, prize_fund_rub FROM competitions WHERE id = %s",
            (competition_id,),
        ).fetchone() == ("Кубок", 0)


def test_existing_v4_schema_is_adopted_without_data_loss(migration_database):
    migrate(migration_database, target_version="003")
    with psycopg.connect(migration_database) as connection:
        owner_id = connection.execute(
            "INSERT INTO owners (name) VALUES ('Старый клуб') RETURNING id"
        ).fetchone()[0]
        competition_id = connection.execute(
            "INSERT INTO competitions (name, event_date, location, distance_m) "
            "VALUES ('Старый кубок', '2026-01-01', 'Москва', 1600) RETURNING id"
        ).fetchone()[0]
        connection.execute("DROP TABLE schema_migrations")

    assert migrate(migration_database) == ["001", "002", "003", "004"]
    with psycopg.connect(migration_database) as connection:
        assert connection.execute(
            "SELECT name FROM owners WHERE id = %s", (owner_id,)
        ).fetchone() == ("Старый клуб",)
        assert connection.execute(
            "SELECT name, prize_fund_rub FROM competitions WHERE id = %s",
            (competition_id,),
        ).fetchone() == ("Старый кубок", 0)
