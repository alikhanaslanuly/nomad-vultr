#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

[[ -f .env && -r .env ]] || fail 'A readable existing .env is required; configure it securely before deployment.'
command -v docker >/dev/null 2>&1 || fail 'Docker is required; install it before deployment.'
command -v python3 >/dev/null 2>&1 || fail 'Python 3 is required for deployment configuration validation.'
docker compose version >/dev/null 2>&1 || fail 'The Docker Compose plugin is required.'
docker info >/dev/null 2>&1 || fail 'The Docker daemon must be available to the deployment user.'

if ! docker compose -f infra/compose.vm1.yml config --format json 2>/dev/null \
    | python3 infra/vm1_deploy_check.py config; then
    fail 'Deployment configuration is invalid: secure Runner, receipt signing and database settings are required, and placeholder values are forbidden.'
fi

docker compose -f infra/compose.vm1.yml build
docker compose -f infra/compose.vm1.yml up -d

if ! docker compose -f infra/compose.vm1.yml exec -T backend python - health \
    < infra/vm1_deploy_check.py >/dev/null 2>&1; then
    fail 'Backend API verification failed: live mode, Runner availability and verified observation are required.'
fi

printf '%s\n' 'Backend API verified from the backend container: live mode, Runner up, observer verified.'

