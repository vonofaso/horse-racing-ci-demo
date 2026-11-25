#!/bin/sh
set -eu

postgres=postgres:16.10-bookworm@sha256:38471f330eb885e04de130b768d6db4e10469e2311879c7e5c699f6d2d8a1c74
trivy=aquasec/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb
gitleaks=zricethezav/gitleaks:v8.30.0@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9

prepare_tools() {
    docker build --tag horse-racing-ci:tools .github/ci
}

run_tools() {
    docker run --rm --workdir /workspace --volume /workspace:/workspace \
        --tmpfs /workspace/.venv:exec \
        --env PIP_CACHE_DIR=/workspace/.ci-cache/pip \
        "$@"
}

run_python_checks() {
    run_tools horse-racing-ci:tools sh -ec "$1"
}

start_db() {
    password=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
    docker network create horse-ci-db-net >/dev/null
    trap 'docker rm -f -v horse-ci-db >/dev/null 2>&1 || true; docker network rm horse-ci-db-net >/dev/null' EXIT
    docker run -d --name horse-ci-db --network horse-ci-db-net \
        --env "POSTGRES_PASSWORD=$password" --env POSTGRES_USER=horse \
        "$postgres" >/dev/null
    for _ in $(seq 1 60); do
        if docker exec horse-ci-db pg_isready -h 127.0.0.1 -U horse -d postgres; then
            for database in horse_ci horse_ci_test horse_ci_restore; do
                docker exec horse-ci-db createdb -U horse "$database"
            done
            return 0
        fi
        sleep 1
    done
    docker logs horse-ci-db >&2
    return 1
}

run_database_checks() {
    start_db
    db_url="postgresql://horse:$password@horse-ci-db:5432"
    run_tools --network horse-ci-db-net \
        --env "DATABASE_URL=$db_url/horse_ci" \
        --env "TEST_DATABASE_URL=$db_url/horse_ci_test" \
        --env "RESTORE_DATABASE_URL=$db_url/horse_ci_restore" \
        horse-racing-ci:tools sh -ec "$1"
}

run_trivy() {
    docker run --rm --workdir /workspace --volume /workspace:/workspace \
        "$trivy" --cache-dir /workspace/.ci-cache/trivy "$@" --no-progress
}

check_security() {
    result=0
    mkdir -p .ci-state/dependencies/development .ci-state/dependencies/runtime
    # Scan actual installed development and hash-locked runtime environments.
    run_python_checks 'make setup
        .venv/bin/python -m pip freeze > .ci-state/dependencies/development/requirements.txt
        test -s .ci-state/dependencies/development/requirements.txt
        .venv/bin/python -m venv /tmp/horse-runtime
        /tmp/horse-runtime/bin/python -m pip install --only-binary=:all: --require-hashes -r requirements.lock
        /tmp/horse-runtime/bin/python -m pip check
        /tmp/horse-runtime/bin/python -m pip freeze > .ci-state/dependencies/runtime/requirements.txt
        test -s .ci-state/dependencies/runtime/requirements.txt
        make sast' || result=1
    docker run --rm --volume /workspace:/workspace \
        --env GIT_CONFIG_COUNT=1 --env GIT_CONFIG_KEY_0=safe.directory \
        --env GIT_CONFIG_VALUE_0=/workspace "$gitleaks" git --log-opts=HEAD \
        --redact=100 --no-banner --report-format=json \
        --report-path=/workspace/reports/secrets.json /workspace || result=1
    run_trivy fs --scanners vuln --severity HIGH,CRITICAL --exit-code 1 \
        --format json --output reports/dependencies.json .ci-state/dependencies || result=1
    return "$result"
}

set_image_ref() {
    sha=${1:?commit SHA required}
    if [ "${#sha}" -ne 40 ] || [ -n "$(printf '%s' "$sha" | tr -d 'a-f0-9')" ]; then
        echo 'Expected a full lowercase Git commit SHA' >&2
        exit 2
    fi
    image="horse-racing:sha-$sha"
    archive=".ci-state/image-$sha.tar"
}

load_image() {
    docker load --input "$archive"
    test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" = "$sha"
}

publish() {
    repository=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
    host=horse-registry:5000
    user=${CI_REGISTRY_USERNAME:?CI_REGISTRY_USERNAME secret required}
    token=${CI_REGISTRY_TOKEN:?CI_REGISTRY_TOKEN secret required}
    target="$host/$repository:sha-$sha"
    export DOCKER_CONFIG
    DOCKER_CONFIG=$(mktemp -d)
    trap 'rm -rf "$DOCKER_CONFIG"' EXIT
    printf '%s' "$token" | docker login --username "$user" --password-stdin "$host"
    image_id=$(docker image inspect --format '{{.Id}}' "$image")
    platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")
    docker tag "$image" "$target"
    docker push "$target"
    docker image rm "$target" "$image"
    docker pull --platform "$platform" "$target"
    test "$(docker image inspect --format '{{.Id}}' "$target")" = "$image_id"
    echo "Verified local registry push and pull: $target"
    echo "Published $target"
}

case "${1:-}" in
    style)
        prepare_tools
        result=0
        run_python_checks 'make setup; make lint' > reports/style.log 2>&1 || result=$?
        cat reports/style.log
        exit "$result"
        ;;
    tests)
        prepare_tools
        run_database_checks 'make setup; make test'
        ;;
    migrations)
        prepare_tools
        # shellcheck disable=SC2016  # Expand variables in the tools container.
        run_database_checks 'make setup
            make migrate
            query="SELECT version, checksum, applied_at FROM schema_migrations ORDER BY version"
            before=$(psql "$DATABASE_URL" -XAt -v ON_ERROR_STOP=1 -c "$query")
            test -n "$before"
            make migrate
            after=$(psql "$DATABASE_URL" -XAt -v ON_ERROR_STOP=1 -c "$query")
            test "$before" = "$after"
            printf "%s\n" "$after" > reports/migrations.txt'
        ;;
    backup)
        prepare_tools
        # shellcheck disable=SC2016  # Expand variables in the tools container.
        run_database_checks 'make setup
            make migrate
            psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -c "CREATE TABLE ci_backup_probe AS SELECT 7214 AS value"
            dump=$(mktemp -d)/horse-ci.dump
            make backup BACKUP_FILE="$dump"
            CONFIRM_RESTORE=YES make restore BACKUP_FILE="$dump"
            value=$(psql "$RESTORE_DATABASE_URL" -XAt -v ON_ERROR_STOP=1 -c "SELECT value FROM ci_backup_probe")
            test "$value" = 7214
            printf "Verified restored value: %s\n" "$value" > reports/backup.txt'
        ;;
    security)
        prepare_tools
        check_security
        ;;
    container)
        prepare_tools
        : > .ci-state/compose.env
        POSTGRES_PASSWORD=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
        APP_DB_PASSWORD=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
        export POSTGRES_PASSWORD APP_DB_PASSWORD
        run_tools --volume /var/run/docker.sock:/var/run/docker.sock \
            --volume /usr/local/bin/docker:/usr/local/bin/docker:ro \
            --volume /usr/local/libexec/docker/cli-plugins:/usr/local/libexec/docker/cli-plugins:ro \
            --env POSTGRES_PASSWORD --env APP_DB_PASSWORD \
            horse-racing-ci:tools make container-check CONTAINER_ENV_FILE=.ci-state/compose.env
        ;;
    build)
        set_image_ref "$2"
        docker build --pull --label "org.opencontainers.image.revision=$sha" --tag "$image" . >&2
        docker save "$image"
        ;;
    scan)
        set_image_ref "$2"
        run_trivy image --input "$archive" --scanners vuln,secret \
            --severity HIGH,CRITICAL --exit-code 1 --format json --output reports/image.json
        ;;
    publish)
        set_image_ref "$2"
        load_image
        publish "${3:?repository required}"
        ;;
    *)
        echo 'Unknown CI stage' >&2
        exit 2
        ;;
esac
