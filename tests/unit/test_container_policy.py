"""Policy regressions: dangerous settings must reject acceptance."""

from copy import deepcopy

import pytest

from scripts.container_check import ROOT, check_compose, pinned


@pytest.fixture
def config():
    return {
        "name": "hrcheck-test",
        "services": {
            "app": {
                "build": {"context": str(ROOT)},
                "stop_grace_period": "20s",
                "environment": {
                    "DATABASE_URL": "postgresql://horse:test@db:5432/horse_racing"
                },
                "depends_on": {"db": {"condition": "service_healthy"}},
                "cpus": 0.5,
                "mem_limit": 268435456,
                "networks": {"backend": None},
            },
            "db": {
                "image": "postgres:16.10-bookworm@sha256:" + "a" * 64,
                "user": "999:999",
                "healthcheck": {"test": ["CMD", "pg_isready"]},
                "cpus": 1,
                "mem_limit": 536870912,
                "networks": {"backend": None},
                "volumes": [
                    {
                        "type": "volume",
                        "source": "data",
                        "target": "/var/lib/postgresql/data",
                    }
                ],
            },
        },
        "networks": {"backend": {"name": "hrcheck-test_backend", "internal": True}},
        "volumes": {"data": {"name": "hrcheck-test_data"}},
    }


def test_valid_isolated_config(config):
    check_compose(config, isolated=True)


def test_local_app_image_with_versioned_tag_is_allowed(config):
    config["services"]["app"]["image"] = "horse-racing:lab4"
    check_compose(config)


@pytest.mark.parametrize("image", ["horse-racing", "horse-racing:latest"])
def test_local_app_image_requires_non_latest_tag(config, image):
    config["services"]["app"]["image"] = image
    with pytest.raises(ValueError):
        check_compose(config)


@pytest.mark.parametrize(
    "service, key, value",
    [
        ("db", "image", "postgres:latest"),
        ("db", "image", "postgres:latest@sha256:" + "a" * 64),
        ("db", "user", "root"),
        ("app", "user", "0:0"),
        ("app", "command", ["sh", "-c", "python -m app"]),
        ("app", "healthcheck", {"disable": True}),
        ("db", "healthcheck", {"test": ["NONE"]}),
        ("db", "ports", [{"target": 5432, "published": "5432"}]),
        ("app", "ports", [{"target": 9999}]),
        ("app", "privileged", True),
        ("app", "tmpfs", ["/tmp:size=16m", "mode=1777"]),
        ("db", "network_mode", "host"),
        ("app", "cpus", 0),
        ("app", "stop_grace_period", "10s"),
        ("db", "mem_limit", 0),
        (
            "app",
            "environment",
            {"DATABASE_URL": "postgresql://horse:test@127.0.0.1:55432/horse_racing"},
        ),
        (
            "app",
            "environment",
            {
                "DATABASE_URL": "postgresql://horse:test@db:5432/horse_racing",
                "APP_RELOAD": "true",
            },
        ),
        ("app", "depends_on", {"db": {"condition": "service_started"}}),
    ],
)
def test_reject_operational_violation(config, service, key, value):
    config["services"][service][key] = value
    with pytest.raises(ValueError):
        check_compose(config)


@pytest.mark.parametrize(
    "mutation", ["external-volume", "fixed-volume", "bind-mount", "external-network"]
)
def test_disposable_check_cannot_use_working_data(config, mutation):
    unsafe = deepcopy(config)
    if mutation == "external-volume":
        unsafe["volumes"]["data"]["external"] = True
    elif mutation == "fixed-volume":
        unsafe["volumes"]["data"]["name"] = "production_data"
    elif mutation == "bind-mount":
        unsafe["services"]["db"]["volumes"][0]["type"] = "bind"
    else:
        unsafe["networks"]["backend"]["external"] = True
    with pytest.raises(ValueError):
        check_compose(unsafe, isolated=True)


@pytest.mark.parametrize(
    "image", ["python", "python:latest", "python:3.12", "python@sha256:" + "a" * 64]
)
def test_reject_unpinned_base(image):
    assert not pinned(image)


def test_diagnostics_redact_runtime_secrets(monkeypatch):
    from scripts.container_check import redact_output

    monkeypatch.setenv("CONTAINER_CHECK_PASSWORD", "private-acceptance-value")
    output = redact_output(
        b"failed private-acceptance-value postgresql://user:other-password@db/test "
        b'POSTGRES_PASSWORD="third-password"'
    )
    assert "private-acceptance-value" not in output
    assert "other-password" not in output
    assert "third-password" not in output
    assert "failed" in output


def test_failure_names_stage_and_shows_stderr(monkeypatch):
    import subprocess

    from scripts import container_check

    monkeypatch.setattr(
        container_check.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout=b"sensitive config", stderr=b"registry unavailable"
        ),
    )
    with pytest.raises(RuntimeError, match="(?s)build.*registry unavailable") as error:
        container_check.run(["docker", "compose"], label="build")
    assert "sensitive config" not in str(error.value)


def test_container_logs_include_successful_stderr(monkeypatch):
    import subprocess

    from scripts import container_check

    monkeypatch.setattr(
        container_check.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=b"", stderr=b"Application shutdown complete"
        ),
    )
    assert b"Application shutdown complete" in container_check.run(
        ["docker", "logs", "app"], include_stderr=True
    )


def test_missing_runtime_file_rejected_before_docker(tmp_path):
    from scripts.container_check import check_sources

    for name in (
        "Dockerfile",
        ".dockerignore",
        "requirements.lock",
        "app/__init__.py",
        "app/__main__.py",
        "scripts/__init__.py",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    with pytest.raises(ValueError, match="Missing project file: scripts/db_tools.py"):
        check_sources(tmp_path)
