#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd -P)
name=${CI_DIND_NAME:-horse-racing-dind}
image=docker:29.10.0-dind@sha256:4bbc7223f81db790097c6dea42fb93e05b8fead4f0431fbe6ccaba6e8473201c

run_inside() {
    docker exec --workdir /workspace "$name" "$@"
}

case "${1:-}" in
    start|start-registry)
        mkdir -p "$root/.ci-cache/pip" "$root/.ci-state" "$root/reports"
        docker_options=(
            --detach --privileged --name "$name"
            --mount "type=bind,source=$root,target=/workspace"
        )
        if [[ "$1" == start-registry ]]; then
            ca_file="${HORSE_REGISTRY_CONFIG:-$HOME/.config/horse-racing-registry}/ca.crt"
            if [[ ! -f "$ca_file" || ! -r "$ca_file" ]]; then
                echo "Registry CA is missing or unreadable: $ca_file" >&2
                exit 1
            fi
            docker_options+=(
                --network horse-racing-registry
                --mount "type=bind,source=$ca_file,target=/etc/docker/certs.d/horse-registry:5000/ca.crt,readonly"
            )
        fi
        docker run "${docker_options[@]}" "$image" dockerd --host=unix:///var/run/docker.sock \
            --storage-driver=overlay2
        for ((attempt = 0; attempt < 60; attempt++)); do
            if run_inside docker info --format 'DinD daemon: {{.ServerVersion}} ({{.Driver}})'; then
                exit 0
            fi
            sleep 2
        done
        docker logs "$name" >&2
        exit 1
        ;;
    check)
        stage=${2:?check name required}
        case "$stage" in style|tests|migrations|backup|security|container) ;; *) exit 2 ;; esac
        run_inside sh .github/ci/checks.sh "$stage" 2>&1 | tee "$root/reports/$stage-stage.log"
        case "$stage" in
            style) required_reports=(style.log) ;;
            tests) required_reports=(tests.xml coverage.xml) ;;
            migrations) required_reports=(migrations.txt) ;;
            backup) required_reports=(backup.txt) ;;
            security) required_reports=(sast.json secrets.json dependencies.json) ;;
            container) required_reports=(container-stage.log) ;;
        esac
        for report in "${required_reports[@]}"; do
            test -s "$root/reports/$report"
        done
        ;;
    build)
        sha=${2:?commit SHA required}
        # Keep the archive owned by the runner, which uploads it after scanning.
        temporary_archive=$(mktemp "$root/.ci-state/image.XXXXXX")
        trap 'rm -f "$temporary_archive"' EXIT
        run_inside sh .github/ci/checks.sh build "$sha" > "$temporary_archive"
        mv -f "$temporary_archive" "$root/.ci-state/image-$sha.tar"
        ;;
    scan)
        run_inside sh .github/ci/checks.sh scan "${2:?commit SHA required}"
        ;;
    publish)
        docker exec --workdir /workspace \
            --env CI_REGISTRY_USERNAME --env CI_REGISTRY_TOKEN \
            "$name" sh .github/ci/checks.sh publish \
            "${2:?commit SHA required}" "${3:?repository required}"
        ;;
    stop)
        if docker container inspect "$name" >/dev/null 2>&1; then
            # Restore host ownership before actions/cache saves the pip directory.
            status=0
            run_inside chown -R "$(id -u):$(id -g)" /workspace/.ci-cache /workspace/reports /workspace/.ci-state || status=$?
            docker rm -f -v "$name"
            exit "$status"
        fi
        ;;
    *)
        echo "Usage: $0 {start|start-registry|check NAME|build SHA|scan SHA|publish SHA OWNER/REPO|stop}" >&2
        exit 2
        ;;
esac
