#!/bin/sh
# Run inside an existing DinD: docker exec --workdir /workspace NAME sh .github/ci/secret-demo.sh
set -eu
image=zricethezav/gitleaks:v8.30.0@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
mkdir -p /workspace/reports
# Generate a nonfunctional token in a disposable repository, then delete it at HEAD.
# Only a redacted report is written to the project. No secret is committed to it.
docker run --rm --entrypoint sh --volume "$fixture:/fixture" "$image" -ec '
    cd /fixture
    git init -q
    git config user.name "Security demo"
    git config user.email "demo@example.invalid"
    token=$(head -c 27 /dev/urandom | base64 | tr "+/" "ab")
    printf "github_token = \"ghp_%s\"\n" "$token" > credential.txt
    git add credential.txt
    git commit -qm "Disposable synthetic credential"
    git rm -q credential.txt
    git commit -qm "Remove fixture from HEAD"
'
result=0
docker run --rm --volume "$fixture:/fixture:ro" --volume /workspace/reports:/reports \
    --env GIT_CONFIG_COUNT=1 --env GIT_CONFIG_KEY_0=safe.directory \
    --env GIT_CONFIG_VALUE_0=/fixture "$image" git --log-opts=HEAD \
    --redact=100 --no-banner --report-format=json \
    --report-path=/reports/demo-secrets.json /fixture || result=$?
test "$result" -eq 1
grep -q 'github-pat' /workspace/reports/demo-secrets.json
printf 'PASS: Gitleaks rejected a deleted synthetic token in history (exit 1).\n'
