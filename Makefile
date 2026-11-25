PYTHON ?= python3.12
VENV_PYTHON := .venv/bin/python
BACKUP_FILE ?= backups/horse-racing-$(shell date +%Y%m%d-%H%M%S).dump

-include .env
export DATABASE_URL TEST_DATABASE_URL

.PHONY: setup install run test test-unit test-integration mutation lint sast quality verify migrate backup restore

$(VENV_PYTHON):
	$(PYTHON) -m venv .venv

setup: $(VENV_PYTHON)
	$(VENV_PYTHON) -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 'Нужно пересоздать .venv на Python 3.12')"
	$(VENV_PYTHON) -m pip install -r requirements-dev.txt
	$(VENV_PYTHON) -m pip check

install: setup

run: $(VENV_PYTHON)
	@test -n "$$DATABASE_URL" || (echo "Задайте DATABASE_URL" >&2; exit 1)
	$(VENV_PYTHON) -m app

test-unit: $(VENV_PYTHON)
	$(VENV_PYTHON) -m pytest -m unit

test-integration: $(VENV_PYTHON)
	@test -n "$$DATABASE_URL" || (echo "Задайте DATABASE_URL" >&2; exit 1)
	@test -n "$$TEST_DATABASE_URL" || (echo "Задайте TEST_DATABASE_URL" >&2; exit 1)
	$(VENV_PYTHON) -m scripts.db_tools check-test-database
	$(VENV_PYTHON) -m pytest -m integration

test: $(VENV_PYTHON)
	@test -n "$$DATABASE_URL" || (echo "Задайте DATABASE_URL" >&2; exit 1)
	@test -n "$$TEST_DATABASE_URL" || (echo "Задайте TEST_DATABASE_URL" >&2; exit 1)
	$(VENV_PYTHON) -m scripts.db_tools check-test-database
	@mkdir -p reports
	$(VENV_PYTHON) -m pytest --cov=app --cov=scripts --cov-report=term-missing --cov-report=xml:reports/coverage.xml --junitxml=reports/tests.xml
	$(VENV_PYTHON) -m scripts.mutation_checks

mutation: $(VENV_PYTHON)
	$(VENV_PYTHON) -m scripts.mutation_checks

lint: $(VENV_PYTHON)
	$(VENV_PYTHON) -m ruff check .
	$(VENV_PYTHON) -m ruff format --check .

sast: $(VENV_PYTHON)
	@mkdir -p reports
	$(VENV_PYTHON) -m bandit -q -r app scripts -f json -o reports/sast.json

quality: lint
	$(MAKE) sast

verify: quality test

migrate: $(VENV_PYTHON)
	@test -n "$$DATABASE_URL" || (echo "Задайте DATABASE_URL" >&2; exit 1)
	$(VENV_PYTHON) -m scripts.db_tools migrate

backup: $(VENV_PYTHON)
	@test -n "$$DATABASE_URL" || (echo "Задайте DATABASE_URL" >&2; exit 1)
	$(VENV_PYTHON) -m scripts.db_tools backup --file "$(BACKUP_FILE)"

restore: $(VENV_PYTHON)
	@test -n "$$RESTORE_DATABASE_URL" || (echo "Задайте RESTORE_DATABASE_URL" >&2; exit 1)
	@test -n "$$BACKUP_FILE" || (echo "Задайте BACKUP_FILE" >&2; exit 1)
	@test "$$CONFIRM_RESTORE" = YES || (echo "Для восстановления задайте CONFIRM_RESTORE=YES" >&2; exit 1)
	$(VENV_PYTHON) -m scripts.db_tools restore --file "$(BACKUP_FILE)"

# ЛР4: the working environment and disposable acceptance use the same image.
CONTAINER_PYTHON ?= python3
CONTAINER_COMPOSE ?= compose.yaml
CONTAINER_ENV_FILE ?= .env.compose
CONTAINER_PROJECT ?= horse-racing
COMPOSE_COMMAND = docker compose --env-file "$(CONTAINER_ENV_FILE)" -p "$(CONTAINER_PROJECT)" -f "$(CONTAINER_COMPOSE)"

.PHONY: container-check container-policy container-up up down container-migrate container-backup container-restore
container-policy:
	$(CONTAINER_PYTHON) -m scripts.container_check --sources-only

container-check:
	$(CONTAINER_PYTHON) -m scripts.container_check $(if $(wildcard $(CONTAINER_COMPOSE)),--compose "$(CONTAINER_COMPOSE)" --compose-env "$(CONTAINER_ENV_FILE)",)

# Never mutate the working environment after a failed acceptance check.
container-up: container-check
	test -f "$(CONTAINER_COMPOSE)"
	$(COMPOSE_COMMAND) up -d --build --wait --wait-timeout 120

up: container-up

down:
	$(COMPOSE_COMMAND) down

container-migrate:
	$(COMPOSE_COMMAND) exec -T app python -m scripts.db_tools migrate

container-backup:
	$(CONTAINER_PYTHON) -m scripts.container_db --compose "$(CONTAINER_COMPOSE)" --env-file "$(CONTAINER_ENV_FILE)" --project "$(CONTAINER_PROJECT)" backup --file "$(BACKUP_FILE)"

container-restore:
	$(CONTAINER_PYTHON) -m scripts.container_db --compose "$(CONTAINER_COMPOSE)" --env-file "$(CONTAINER_ENV_FILE)" --project "$(CONTAINER_PROJECT)" restore --file "$(BACKUP_FILE)"
