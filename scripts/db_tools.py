"""Локальные команды подготовки, копирования и восстановления PostgreSQL."""

import argparse
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from app.migrations import migrate

PG_ENV_KEYS = {
    "host": "PGHOST",
    "hostaddr": "PGHOSTADDR",
    "port": "PGPORT",
    "dbname": "PGDATABASE",
    "user": "PGUSER",
    "password": "PGPASSWORD",
    "sslmode": "PGSSLMODE",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "sslrootcert": "PGSSLROOTCERT",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "options": "PGOPTIONS",
}


def _pg_executable(program: str) -> str:
    """Найти разрешённую клиентскую утилиту PostgreSQL по абсолютному пути."""
    if program not in {"pg_dump", "pg_restore"}:
        raise ValueError(f"Недопустимая утилита: {program}")
    executable = shutil.which(program)
    if executable is None:
        raise FileNotFoundError(f"Установите клиентскую утилиту PostgreSQL: {program}")
    return str(Path(executable).resolve())


def pg_environment(variable: str) -> tuple[dict[str, str], str]:
    """Передать параметры подключения утилитам без пароля в аргументах."""
    url = os.environ.get(variable)
    if url is not None:
        url = url.strip()
        if len(url) >= 2 and url[0] == url[-1] and url[0] in {'"', "'"}:
            url = url[1:-1].strip()
    if not url:
        raise ValueError(f"Задайте {variable}")
    try:
        parameters = conninfo_to_dict(url)
    except psycopg.ProgrammingError as error:
        raise ValueError(f"Некорректная строка подключения в {variable}") from error
    unsupported = parameters.keys() - PG_ENV_KEYS.keys()
    if unsupported:
        raise ValueError(
            "Неподдерживаемые параметры подключения: " + ", ".join(sorted(unsupported))
        )
    database_name = parameters.get("dbname")
    if not database_name:
        raise ValueError(f"В {variable} должно быть указано имя базы данных")
    environment = os.environ.copy()
    for key, environment_key in PG_ENV_KEYS.items():
        if key in parameters:
            environment[environment_key] = parameters[key]
    return environment, database_name


def check_test_database() -> None:
    """Не позволить тестам очистить базу с именем рабочей базы."""
    production_url = os.environ.get("DATABASE_URL")
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not production_url or not test_url:
        raise ValueError("Задайте DATABASE_URL и TEST_DATABASE_URL")
    production_name = conninfo_to_dict(production_url).get("dbname")
    test_name = conninfo_to_dict(test_url).get("dbname")
    if (
        not production_name
        or not test_name
        or production_name == test_name
        or not test_name.endswith("_test")
    ):
        raise ValueError("Тестовая БД должна иметь другое имя и суффикс _test")


def backup(path: Path) -> None:
    """Создать дамп в формате PostgreSQL custom, не заменяя старый файл."""
    environment, _ = pg_environment("DATABASE_URL")
    if path.exists():
        raise FileExistsError(f"Файл уже существует: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".horse-racing-", suffix=".dump.tmp", dir=path.parent, delete=False
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
    try:
        subprocess.run(  # nosec B603
            [
                _pg_executable("pg_dump"),
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(temporary_path),
            ],
            env=environment,
            check=True,
            shell=False,
        )
        if temporary_path.stat().st_size == 0:
            raise ValueError("pg_dump создал пустой файл")
        try:
            subprocess.run(  # nosec B603
                [_pg_executable("pg_restore"), "--list", str(temporary_path)],
                check=True,
                capture_output=True,
                shell=False,
            )
        except subprocess.CalledProcessError as error:
            raise ValueError("pg_dump создал повреждённый архив") from error
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    print(f"Резервная копия создана: {path}")


def restore(path: Path) -> None:
    """Восстановить существующую БД из дампа в одной транзакции."""
    environment, database_name = pg_environment("RESTORE_DATABASE_URL")
    if not path.is_file():
        raise FileNotFoundError(f"Файл копии не найден: {path}")
    if os.environ.get("CONFIRM_RESTORE") != "YES":
        raise ValueError("Для восстановления задайте CONFIRM_RESTORE=YES")
    try:
        subprocess.run(  # nosec B603
            [_pg_executable("pg_restore"), "--list", str(path)],
            check=True,
            capture_output=True,
            shell=False,
        )
    except subprocess.CalledProcessError as error:
        raise ValueError("Файл не является корректным архивом PostgreSQL") from error
    subprocess.run(  # nosec B603
        [
            _pg_executable("pg_restore"),
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--single-transaction",
            "--exit-on-error",
            f"--dbname={database_name}",
            str(path),
        ],
        env=environment,
        check=True,
        shell=False,
    )
    print(f"База {database_name} восстановлена из {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate", help="применить ожидающие миграции БД")
    subparsers.add_parser("check-test-database", help="проверить отдельную тестовую БД")
    for command in ("backup", "restore"):
        subparsers.add_parser(command).add_argument("--file", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "migrate":
            database_url = os.environ.get("DATABASE_URL")
            if not database_url:
                raise ValueError("Задайте DATABASE_URL")
            versions = migrate(database_url)
            print("Применены миграции: " + ", ".join(versions))
        elif arguments.command == "check-test-database":
            check_test_database()
        elif arguments.command == "backup":
            backup(arguments.file)
        else:
            restore(arguments.file)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
