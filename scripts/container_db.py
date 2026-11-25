"""Backup and restore the selected Compose database with its own PostgreSQL tools."""

import argparse
import os
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path


def run(compose, *args, stdin=None, stdout=None):
    # Arguments are a list; any sh -c statements below are fixed source strings.
    subprocess.run(  # nosec B603
        [*compose, *args],
        stdin=stdin,
        stdout=stdout,
        check=True,
        shell=False,
        timeout=120,
    )


def validate_archive(compose, path):
    with path.open("rb") as archive:
        run(
            compose,
            "exec",
            "-T",
            "db",
            "pg_restore",
            "--list",
            stdin=archive,
            stdout=subprocess.DEVNULL,
        )


def backup(compose, path):
    if path.exists():
        raise FileExistsError(f"Файл уже существует: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".container-backup-", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            run(
                compose,
                "exec",
                "-T",
                "db",
                "sh",
                "-c",
                'exec pg_dump -U "$APP_DB_USER" -d "$POSTGRES_DB" '
                "--format=custom --no-owner --no-privileges",
                stdout=temporary,
            )
        if temporary_path.stat().st_size == 0:
            raise ValueError("PostgreSQL создала пустую резервную копию")
        validate_archive(compose, temporary_path)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    print(f"Контейнерная резервная копия создана: {path}")


def restore(compose, path):
    if os.environ.get("CONFIRM_RESTORE") != "YES":
        raise ValueError("Для восстановления задайте CONFIRM_RESTORE=YES")
    if not path.is_file():
        raise FileNotFoundError(f"Файл копии не найден: {path}")
    run(compose, "up", "-d", "--wait", "--wait-timeout", "120", "db")
    validate_archive(compose, path)
    run(compose, "stop", "app")
    with path.open("rb") as archive:
        run(
            compose,
            "exec",
            "-T",
            "db",
            "sh",
            "-c",
            'exec pg_restore -U "$APP_DB_USER" -d "$POSTGRES_DB" '
            "--clean --if-exists --no-owner --no-privileges "
            "--single-transaction --exit-on-error",
            stdin=archive,
        )
    run(compose, "up", "-d", "--no-build", "--wait", "--wait-timeout", "120", "app")
    print(f"БД выбранного Compose-проекта восстановлена из {path}; приложение готово")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", default="compose.yaml")
    parser.add_argument("--env-file", default=".env.compose")
    parser.add_argument("--project", default="horse-racing")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("backup", "restore"):
        commands.add_parser(command).add_argument("--file", required=True, type=Path)
    args = parser.parse_args()
    compose = [
        "docker",
        "compose",
        "--env-file",
        args.env_file,
        "-p",
        args.project,
        "-f",
        args.compose,
    ]
    try:
        if args.command == "backup":
            backup(compose, args.file)
        else:
            restore(compose, args.file)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Ошибка контейнерной операции: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
