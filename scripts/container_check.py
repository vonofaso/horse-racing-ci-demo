"""Fail-closed container acceptance in disposable Compose projects only."""

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/container/compose.yaml"
DOCKER = shutil.which("docker") or "docker"
PIN = re.compile(r"[^\s]+:[^\s:@]+@sha256:[0-9a-f]{64}$")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pinned(image):
    return bool(PIN.fullmatch(image)) and ":latest@" not in image.lower()


def check_sources(root=ROOT):
    for name in (
        "Dockerfile",
        ".dockerignore",
        "requirements.lock",
        "app/__init__.py",
        "app/__main__.py",
        "scripts/__init__.py",
        "scripts/db_tools.py",
        "scripts/container_health.py",
    ):
        require(
            (root / name).is_file(),
            f"Missing project file: {name}; restore the full project",
        )
    dockerfile = (root / "Dockerfile").read_text()
    # Join Dockerfile continuations before evaluating instructions.
    lines = dockerfile.replace("\\\n", " ").splitlines()
    instructions = [
        line.strip() for line in lines if line.strip() and not line.startswith("#")
    ]
    bases = [line.split()[1] for line in instructions if line.startswith("FROM ")]
    require(
        bases and all(pinned(base) for base in bases),
        "FROM must use tag + SHA256; latest is forbidden",
    )
    require("USER 10001:10001" in instructions, "Application must use UID/GID 10001")
    require(
        instructions[-1] == 'CMD ["python", "-m", "app"]',
        "Use exec-form CMD; Python must receive SIGTERM",
    )
    require("STOPSIGNAL SIGTERM" in instructions, "SIGTERM is required")
    require(
        any(
            line.startswith("HEALTHCHECK ") and "NONE" not in line
            for line in instructions
        ),
        "Healthcheck is required",
    )
    require(
        "--require-hashes" in dockerfile and "--only-binary=:all:" in dockerfile,
        "Install only hash-locked wheels",
    )
    copies = [line for line in instructions if line.startswith(("COPY ", "ADD "))]
    require(
        copies
        == [
            "COPY requirements.lock ./",
            "COPY app ./app",
            "COPY scripts/__init__.py scripts/db_tools.py "
            "scripts/container_health.py ./scripts/",
        ],
        "Only explicit application files may enter the image",
    )
    require(
        not any(line.startswith("ARG ") for line in instructions),
        "Build arguments are forbidden; pass settings at runtime",
    )
    require(
        not re.search(
            r"(?i)(DATABASE_URL|PASSWORD|TOKEN|SECRET|PRIVATE_KEY)\s*=", dockerfile
        ),
        "Do not put secrets in the image",
    )
    ignore = (root / ".dockerignore").read_text()
    require(
        ignore.startswith("**\n"), "Build context must use a default-deny .dockerignore"
    )
    require(
        not any(
            line.startswith("!")
            and line
            not in {
                "!requirements.lock",
                "!app/",
                "!app/**",
                "!scripts/",
                "!scripts/__init__.py",
                "!scripts/db_tools.py",
                "!scripts/container_health.py",
            }
            for line in ignore.splitlines()
        ),
        "Unexpected build context allowlist entry",
    )
    for path in (root / "app").rglob("*"):
        require(
            not (
                path.is_symlink()
                or path.name.startswith(".env")
                or path.suffix.lower() in {".pem", ".key", ".dump", ".sql", ".p12"}
            ),
            "Secret or unexpected file in app build context",
        )
    lock = (root / "requirements.lock").read_text()
    require("--hash=sha256:" in lock, "requirements.lock must contain hashes")
    require(
        "timeout_graceful_shutdown=15" in (root / "app/__main__.py").read_text(),
        "Bounded graceful shutdown is required",
    )


def nonroot(user):
    return str(user).split(":")[0] not in {"", "0", "root"}


def check_compose(config, isolated=False):
    services = config.get("services", {})
    require({"app", "db"} <= services.keys(), "Compose must define app and db")
    for name, service in services.items():
        image = service.get("image", "")
        if image:
            if name == "app" and service.get("build"):
                # Locally built images get their digest from this build. Their
                # checked Dockerfile still pins the base image and dependencies.
                require(
                    pinned(image)
                    or (
                        re.fullmatch(r"[^\s@]+:[^\s:@]+", image)
                        and image.rsplit(":", 1)[-1].lower() != "latest"
                    ),
                    "app: local build requires an explicit non-latest tag",
                )
            else:
                require(
                    pinned(image),
                    f"{name}: pin image tag + digest; latest is forbidden",
                )
        require(not service.get("privileged"), f"{name}: privileged mode forbidden")
        require(
            service.get("network_mode") != "host", f"{name}: host networking forbidden"
        )
        require(service.get("pid") != "host", f"{name}: host PID namespace forbidden")
        health = service.get("healthcheck", {})
        if name == "app":
            build = service.get("build", {})
            require(
                Path(build.get("context", "")).resolve() == ROOT
                and build.get("dockerfile", "Dockerfile") == "Dockerfile",
                "app must build the checked Dockerfile",
            )
            require(
                not any(
                    build.get(k)
                    for k in ("args", "dockerfile_inline", "additional_contexts")
                ),
                "app build overrides forbidden",
            )
            grace = str(service.get("stop_grace_period", "10s"))
            require(
                grace.endswith("s") and float(grace[:-1]) >= 20,
                "app: stop_grace_period must be at least 20s (expressed in seconds)",
            )
            require(
                not health.get("disable") and health.get("test") != ["NONE"],
                "app: do not disable image healthcheck",
            )
            require(
                "user" not in service or nonroot(service["user"]),
                "app: root override forbidden",
            )
            require(
                service.get("command") is None and service.get("entrypoint") is None,
                "app: use image command/entrypoint",
            )
            require(
                service.get("environment", {}).get("APP_RELOAD", "false").lower()
                in {"false", "0"},
                "app: reload forbidden",
            )
            url = service.get("environment", {}).get("DATABASE_URL", "")
            require("@db:5432/" in url, "app: DATABASE_URL must address db:5432")
            require(
                service.get("depends_on", {}).get("db", {}).get("condition")
                == "service_healthy",
                "app must wait for healthy db",
            )
        else:
            require(
                nonroot(service.get("user", "")),
                f"{name}: explicit non-root user required",
            )
            require(
                health.get("test")
                and not health.get("disable")
                and health["test"] != ["NONE"],
                f"{name}: healthcheck required",
            )
        require(
            float(service.get("cpus", 0)) > 0 and int(service.get("mem_limit", 0)) > 0,
            f"{name}: CPU/memory limits required",
        )
        require(
            all(mount.startswith("/") for mount in service.get("tmpfs", [])),
            f"{name}: tmpfs paths must be absolute; quote options containing commas",
        )
        ports = service.get("ports", [])
        require(
            name in {"app", "nginx"} or not ports, f"{name}: published ports forbidden"
        )
        require(
            not (name == "app" and "nginx" in services and ports),
            "Publish only nginx when present",
        )
        for port in ports:
            allowed = {8000} if name == "app" else {80, 443}
            require(int(port["target"]) in allowed, f"{name}: unexpected port")
        if isolated:
            require(
                not service.get("configs") and not service.get("secrets"),
                "Fixture cannot mount external configuration",
            )
            require(
                not ports and not service.get("container_name"),
                "Fixture cannot publish ports or use container_name",
            )
            require(
                not (name == "app" and image), "Fixture app image must be project-local"
            )
            for mount in service.get("volumes", []):
                require(
                    mount["type"] == "volume"
                    and mount["source"] in config.get("volumes", {}),
                    "Fixture cannot mount host data",
                )
    db_mounts = services["db"].get("volumes", [])
    require(
        any(
            m["type"] == "volume" and m["target"] == "/var/lib/postgresql/data"
            for m in db_mounts
        ),
        "db: persistent named volume required",
    )
    networks = config.get("networks", {})
    shared = set(services["app"].get("networks", {})) & set(
        services["db"].get("networks", {})
    )
    require(
        any(networks[n].get("internal") for n in shared),
        "app/db must share an internal network",
    )
    if isolated:
        require(set(services) == {"app", "db"}, "Fixture only supports app/db")
        project = config["name"]
        for group in (config.get("volumes", {}), networks):
            for key, item in group.items():
                require(
                    not item.get("external") and item.get("name") == f"{project}_{key}",
                    "Fixture resources must be scoped to disposable project",
                )


def redact_output(value):
    """Mask runtime credentials before showing Docker failure diagnostics."""
    text = value.decode(errors="replace") if isinstance(value, bytes) else value
    for key, secret in os.environ.items():
        if (
            re.search(r"(?i)password|secret|token|database_url|credential", key)
            and secret
        ):
            for candidate in sorted(
                {secret, quote(secret, safe="")}, key=len, reverse=True
            ):
                text = text.replace(candidate, "[REDACTED]")
    text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+@", r"\1[REDACTED]@", text)
    text = re.sub(
        r"(?i)([\w]*(?:password|secret|token|database_url)[\w]*[\"']?\s*[:=]\s*)"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1[REDACTED]",
        text,
    )
    # Remove terminal control characters from diagnostic output.
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def run(args, *, data=None, timeout=600, label=None, include_stderr=False):
    name = label or f"{Path(args[0]).name} {args[1]}"
    try:
        result = subprocess.run(
            args,
            input=data,
            capture_output=True,
            timeout=timeout,
            check=False,
        )  # nosec B603
    except subprocess.TimeoutExpired as error:
        details = redact_output(error.stderr or b"")[-6000:]
        raise RuntimeError(f"{name}: timed out after {timeout}s\n{details}") from error
    if result.returncode:
        # Show stderr only: successful config/inspect stdout can contain secrets.
        details = redact_output(result.stderr or b"")[-6000:].strip()
        raise RuntimeError(
            f"{name}: exit {result.returncode}\n"
            + (details or "Docker returned no stderr diagnostics")
        )
    return result.stdout + (result.stderr if include_stderr else b"")


def inspect(container):
    return json.loads(run([DOCKER, "inspect", container]))[0]


def accept(compose_path=None, compose_env=None):
    check_sources()
    print("PASS source policy", flush=True)
    token = secrets.token_hex(6)
    projects = [f"hrcheck-{token}", f"hrrestore-{token}"]
    os.environ["CONTAINER_CHECK_PASSWORD"] = secrets.token_hex(24)
    # Ignore ambient Compose selection/profiles and project settings.
    for key in list(os.environ):
        if key.startswith("COMPOSE_"):
            del os.environ[key]

    def compose(project, *args, data=None):
        label = f"docker compose {args[0]} [{project}]"
        if args[0] in {"build", "up", "stop", "down"}:
            print(f"STEP {label}", flush=True)
        return run(
            [
                DOCKER,
                "compose",
                "--env-file",
                os.devnull,
                "-p",
                project,
                "-f",
                str(FIXTURE),
                *args,
            ],
            data=data,
            label=label,
        )

    for project in projects:
        check_compose(
            json.loads(compose(project, "config", "--format", "json")), isolated=True
        )
    if compose_path:
        # Read-only validation. Never run down/up/restore against production.
        config_args = [DOCKER, "compose"]
        if compose_env:
            require(compose_env.is_file(), f"Missing Compose env file: {compose_env}")
            config_args.extend(["--env-file", str(compose_env)])
        config_args.extend(["-f", str(compose_path), "config", "--format", "json"])
        config = run(config_args)
        check_compose(json.loads(config))
    print("PASS resolved Compose policy", flush=True)
    try:
        run([DOCKER, "info"], timeout=20)
    except RuntimeError as error:
        raise RuntimeError(
            "Docker engine unavailable; start a working Docker installation"
        ) from error
    project, restored = projects

    def sql(p, statement):
        return (
            compose(
                p,
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "horse",
                "-d",
                "horse_racing",
                "-v",
                "ON_ERROR_STOP=1",
                "-Atc",
                statement,
            )
            .decode()
            .strip()
        )

    def cid(p, service):
        return compose(p, "ps", "-aq", service).decode().strip()

    try:
        compose(project, "build", "--pull", "app")
        compose(project, "up", "-d", "--wait", "--wait-timeout", "120")
        app = cid(project, "app")
        state = inspect(app)
        require(nonroot(state["Config"]["User"]), "Runtime app user is root")
        uid = compose(
            project,
            "exec",
            "-T",
            "app",
            "python",
            "-c",
            "import os; print(os.getuid())",
        ).strip()
        require(uid == b"10001", "Unexpected process UID")
        image = json.loads(run([DOCKER, "image", "inspect", state["Image"]]))[0]
        require(nonroot(image["Config"]["User"]), "Image runs as root")
        require(
            image["Config"]["Cmd"] == ["python", "-m", "app"],
            "Unexpected image command",
        )
        require(
            not any(
                re.match(r"(?i)(DATABASE_URL|.*PASSWORD|.*SECRET|.*TOKEN)=", value)
                for value in image["Config"]["Env"]
            ),
            "Secret environment variable baked into image",
        )
        for service in ("app", "db"):
            runtime = inspect(cid(project, service))
            require(
                runtime["State"]["Health"]["Status"] == "healthy", "Container unhealthy"
            )
            require(
                runtime["HostConfig"]["Memory"] > 0
                and runtime["HostConfig"]["NanoCpus"] > 0,
                "Missing actual resource limits",
            )
        require(
            sql(project, "SELECT count(*) FROM schema_migrations") == "4",
            "Migrations missing",
        )
        compose(
            project, "exec", "-T", "app", "python", "-m", "scripts.db_tools", "migrate"
        )
        sql(
            project,
            "CREATE TABLE container_probe AS SELECT md5(random()::text) AS value",
        )
        probe = sql(project, "SELECT value FROM container_probe")
        print("PASS build, UID, resources, readiness, migrations", flush=True)
        # Real negative readiness scenario: DB outage must fail the probe.
        compose(project, "stop", "db")
        result = subprocess.run(
            [DOCKER, "exec", app, "python", "-m", "scripts.container_health"],
            capture_output=True,
            timeout=15,
            check=False,
        )  # nosec B603
        require(result.returncode != 0, "Readiness incorrectly succeeds without DB")
        compose(project, "up", "-d", "--wait", "--wait-timeout", "120")
        compose(project, "stop", "-t", "20", "app")
        stopped = inspect(app)
        require(
            stopped["State"]["ExitCode"] == 0 and not stopped["State"]["OOMKilled"],
            "Graceful SIGTERM failed",
        )
        logs = run([DOCKER, "logs", app], include_stderr=True).decode()
        require(
            "Application shutdown complete" in logs, "Lifespan shutdown did not finish"
        )
        print("PASS DB failure and graceful SIGTERM", flush=True)
        compose(project, "down", "--timeout", "30")  # Intentionally keep volume.
        compose(project, "up", "-d", "--wait", "--wait-timeout", "120")
        require(
            sql(project, "SELECT value FROM container_probe") == probe,
            "Data lost on recreation",
        )
        image_name = state["Config"]["Image"]
        # Derive a genuinely new image from the checked build, retaining its USER,
        # healthcheck and command. This exercises an actual image update.
        run(
            [DOCKER, "build", "-t", image_name, "-"],
            data=(
                f"FROM {image_name}\nENV APP_VERSION=container-check-{token}\n"
            ).encode(),
        )
        compose(
            project, "up", "-d", "--force-recreate", "--wait", "--wait-timeout", "120"
        )
        updated = inspect(cid(project, "app"))
        require(
            updated["Image"] != state["Image"], "Image update did not change image ID"
        )
        require(
            sql(project, "SELECT value FROM container_probe") == probe,
            "Data lost after image update",
        )
        dump = compose(
            project,
            "exec",
            "-T",
            "db",
            "pg_dump",
            "-U",
            "horse",
            "-d",
            "horse_racing",
            "-Fc",
            "--no-owner",
            "--no-privileges",
        )
        require(bool(dump), "Empty backup")
        compose(restored, "up", "-d", "--wait", "--wait-timeout", "120", "db")
        compose(
            restored,
            "exec",
            "-T",
            "db",
            "pg_restore",
            "-U",
            "horse",
            "-d",
            "horse_racing",
            "--no-owner",
            "--no-privileges",
            "--single-transaction",
            "--exit-on-error",
            data=dump,
        )
        require(
            sql(restored, "SELECT value FROM container_probe") == probe,
            "Restore probe mismatch",
        )
        require(
            sql(restored, "SELECT count(*) FROM schema_migrations") == "4",
            "Restored migrations missing",
        )
        run([DOCKER, "tag", image_name, f"{restored}-app"])
        compose(restored, "up", "-d", "--no-build", "--wait", "--wait-timeout", "120")
        print(
            "PASS persistence, image update, backup, restore and API readiness",
            flush=True,
        )
    finally:
        # Never enumerate or prune unrelated Docker resources.
        original_error = sys.exc_info()[0] is not None
        failures = []
        for name in projects:
            try:
                compose(
                    name,
                    "down",
                    "-v",
                    "--remove-orphans",
                    "--rmi",
                    "local",
                    "--timeout",
                    "30",
                )
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                failures.append(name)
                print(f"Cleanup failed: {error}", file=sys.stderr)
        if failures and not original_error:
            raise RuntimeError(
                "Could not clean disposable projects: " + ", ".join(failures)
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compose", type=Path, help="Also validate participant 2 Compose, read-only"
    )
    parser.add_argument(
        "--sources-only",
        action="store_true",
        help="Partial offline check; never an acceptance gate",
    )
    parser.add_argument("--compose-env", type=Path, help="Env file for working Compose")
    args = parser.parse_args()
    try:
        if args.sources_only:
            check_sources()
            print("PASS source policy only; runtime acceptance NOT performed")
        else:
            accept(args.compose, args.compose_env)
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"FAIL container-check: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
