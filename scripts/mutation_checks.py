"""Обязательные мутации бизнес-правил; исходный проект не изменяется."""

import json
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

from defusedxml import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

# Каждое изменение моделирует конкретный дефект, а не случайный синтаксический сбой.
MUTATIONS = [
    (
        "birth-date-inclusive",
        "app/schemas.py",
        "value > date.today()",
        "value >= date.today()",
    ),
    ("birth-date-unchecked", "app/schemas.py", "if value > date.today():", "if False:"),
    (
        "owner-zero-id",
        "app/schemas.py",
        "owner_id: int = Field(gt=0)",
        "owner_id: int = Field(ge=0)",
    ),
    (
        "competition-zero-id",
        "app/schemas.py",
        "competition_id: int = Field(gt=0)",
        "competition_id: int = Field(ge=0)",
    ),
    (
        "horse-zero-id",
        "app/schemas.py",
        "horse_id: int = Field(gt=0)",
        "horse_id: int = Field(ge=0)",
    ),
    (
        "jockey-zero-id",
        "app/schemas.py",
        "jockey_id: int = Field(gt=0)",
        "jockey_id: int = Field(ge=0)",
    ),
    (
        "zero-position",
        "app/schemas.py",
        "position: int = Field(gt=0)",
        "position: int = Field(ge=0)",
    ),
    (
        "zero-distance",
        "app/schemas.py",
        "distance_m: int = Field(gt=0)",
        "distance_m: int = Field(ge=0)",
    ),
    (
        "zero-weight",
        "app/schemas.py",
        "Field(gt=0, le=200, allow_inf_nan=False)",
        "Field(ge=0, le=200, allow_inf_nan=False)",
    ),
    ("weight-upper-boundary", "app/schemas.py", "le=200", "lt=200"),
    (
        "zero-time",
        "app/schemas.py",
        "time_seconds: float = Field(gt=0, allow_inf_nan=False)",
        "time_seconds: float = Field(ge=0, allow_inf_nan=False)",
    ),
    (
        "infinite-time",
        "app/schemas.py",
        "time_seconds: float = Field(gt=0, allow_inf_nan=False)",
        "time_seconds: float = Field(gt=0, allow_inf_nan=True)",
    ),
    (
        "name-too-long",
        "app/schemas.py",
        "min_length=1, max_length=200",
        "min_length=1, max_length=201",
    ),
    (
        "empty-name",
        "app/schemas.py",
        "min_length=1, max_length=200",
        "min_length=0, max_length=200",
    ),
    ("contact-too-long", "app/schemas.py", "max_length=500", "max_length=501"),
    ("short-username", "app/schemas.py", "min_length=3,", "min_length=2,"),
    ("long-username", "app/schemas.py", "max_length=40,", "max_length=41,"),
    (
        "short-password",
        "app/schemas.py",
        "min_length=8, max_length=128",
        "min_length=7, max_length=128",
    ),
    (
        "long-password",
        "app/schemas.py",
        "min_length=8, max_length=128",
        "min_length=8, max_length=129",
    ),
    (
        "missing-disqualification-reason",
        "app/schemas.py",
        "if self.disqualified and self.disqualification_reason is None:",
        "if False:",
    ),
    (
        "unexpected-disqualification-reason",
        "app/schemas.py",
        "if not self.disqualified and self.disqualification_reason is not None:",
        "if False:",
    ),
    (
        "missing-owner",
        "app/services.py",
        "def create_horse(data: schemas.HorseInput) -> Dict[str, Any]:\n"
        '    get_entity("owners", data.owner_id)',
        "def create_horse(data: schemas.HorseInput) -> Dict[str, Any]:\n    pass",
    ),
    ("duplicate-horse", "app/services.py", "if horse_result is not None:", "if False:"),
    (
        "duplicate-jockey",
        "app/services.py",
        "if jockey_result is not None:",
        "if False:",
    ),
    (
        "duplicate-position",
        "app/services.py",
        "if position_result is not None:",
        "if False:",
    ),
    (
        "disqualified-position",
        "app/services.py",
        "if not data.disqualified:",
        "if data.disqualified:",
    ),
    (
        "update-self-conflict",
        "app/services.py",
        "excluded_result_id=entity_id",
        "excluded_result_id=None",
    ),
    (
        "weak-password-hash",
        "app/auth.py",
        "PBKDF2_ITERATIONS = 310_000",
        "PBKDF2_ITERATIONS = 1",
    ),
    (
        "short-password-salt",
        "app/auth.py",
        "secrets.token_bytes(16)",
        "secrets.token_bytes(8)",
    ),
    ("long-session", "app/auth.py", "SESSION_DAYS = 7", "SESSION_DAYS = 8"),
    ("cookie-without-httponly", "app/auth.py", "httponly=True", "httponly=False"),
    ("cookie-without-samesite", "app/auth.py", 'samesite="lax"', 'samesite="none"'),
    (
        "wrong-token-hash",
        "app/auth.py",
        'hashlib.sha256(token.encode("utf-8"))',
        'hashlib.sha1(token.encode("utf-8"))',
    ),
    (
        "expired-session-boundary",
        "app/auth.py",
        "user_sessions.expires_at > %s",
        "user_sessions.expires_at >= %s",
    ),
    (
        "login-permits-wrong-password",
        "app/auth.py",
        'user is None or not _verify_password(data.password, user["password_hash"])',
        'user is None and not _verify_password(data.password, user["password_hash"])',
    ),
    (
        "restore-without-confirmation",
        "scripts/db_tools.py",
        'if os.environ.get("CONFIRM_RESTORE") != "YES":',
        "if False:",
    ),
]


def execute_tests(project: Path, junit: Path) -> tuple[int, int, int, str]:
    """Различить падение assertion и ошибки импорта/фикстуры/инструмента."""
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "pytest", "-m", "unit", "-q", f"--junitxml={junit}"],
        cwd=project,
        text=True,
        capture_output=True,
        shell=False,
        timeout=120,
    )
    if not junit.exists():
        return result.returncode, 0, 1, result.stdout + result.stderr
    xml = ET.parse(junit).getroot()
    failures = len(xml.findall(".//failure"))
    errors = len(xml.findall(".//error")) + len(xml.findall(".//skipped"))
    return result.returncode, failures, errors, result.stdout + result.stderr


def main() -> int:
    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    if len(MUTATIONS) != 36 or len({item[0] for item in MUTATIONS}) != 36:
        print("Обязательный набор должен содержать 36 разных мутаций")
        return 1
    records = []
    with tempfile.TemporaryDirectory(prefix="mutation-") as temporary:
        results = Path(temporary) / "results"
        results.mkdir()
        project = Path(temporary) / "project"
        project.mkdir()
        for directory in ("app", "tests", "scripts"):
            shutil.copytree(
                ROOT / directory,
                project / directory,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        for file in ("pyproject.toml",):
            shutil.copy2(ROOT / file, project / file)
        status, failures, errors, output = execute_tests(
            project, results / "baseline.xml"
        )
        if status or failures or errors:
            print("Мутации нельзя оценить: исходные unit-тесты не проходят")
            (reports / "mutations.json").write_text(
                json.dumps(
                    {
                        "status": "baseline_failed",
                        "exit_code": status,
                        "failures": failures,
                        "errors": errors,
                        "diagnostics": output,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        for name, filename, before, after in MUTATIONS:
            path = project / filename
            original = path.read_text()
            if original.count(before) != 1:
                records.append(
                    {
                        "id": name,
                        "file": filename,
                        "status": "invalid",
                        "reason": "Правило изменилось; обновите мутацию",
                    }
                )
                continue
            path.write_text(original.replace(before, after))
            try:
                # Исключить устаревший байткод при одинаковой длине замены.
                for cache in project.rglob("__pycache__"):
                    shutil.rmtree(cache)
                status, failures, errors, output = execute_tests(
                    project, results / f"{name}.xml"
                )
                outcome = (
                    "killed"
                    if status == 1 and failures > 0 and errors == 0
                    else "survived"
                    if status == 0
                    else "invalid"
                )
                records.append(
                    {
                        "id": name,
                        "file": filename,
                        "status": outcome,
                        "test_failures": failures,
                        "test_errors": errors,
                        "before": before,
                        "after": after,
                    }
                )
                if outcome != "killed":
                    records[-1]["diagnostics"] = output
            except subprocess.TimeoutExpired:
                records.append({"id": name, "file": filename, "status": "timeout"})
            finally:
                path.write_text(original)
            print(f"{name}: {records[-1]['status']}")
    killed = sum(item["status"] == "killed" for item in records)
    score = 100 * killed / len(MUTATIONS)
    threshold = 100
    report = {
        "scope": "Обязательные мутации бизнес-правил; не исчерпывающий анализ",
        "total": len(MUTATIONS),
        "killed": killed,
        "score": score,
        "threshold": threshold,
        "mutants": records,
    }
    (ROOT / "reports" / "mutations.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(f"Обнаружено {killed}/{len(MUTATIONS)} мутаций ({score:.2f}%)")
    return int(score < threshold or any(item["status"] != "killed" for item in records))


if __name__ == "__main__":
    raise SystemExit(main())
