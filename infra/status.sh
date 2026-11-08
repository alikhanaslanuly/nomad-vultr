#!/usr/bin/env bash
set -euo pipefail
date -u
if command -v free >/dev/null; then
    free -h
fi
uptime
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
else
    echo 'Docker daemon is unavailable'
fi
if curl --fail --silent --show-error --connect-timeout 3 --max-time 20 "http://127.0.0.1:${RUNNER_PORT:-9000}/healthz"; then
    echo
else
    echo 'Runner verification failed'
fi
python3 - <<'STATUS'
from fleet import get_manager
from fleet.manager import FleetError
manager = get_manager()
print('Standard Runner configured:', bool(manager.runner_url and manager.runner_token))
if manager.vultr_api_key:
    try:
        for instance in manager._instances():
            print('Owned Burn VM:', instance['id'], instance.get('status', 'unknown'))
    except FleetError as error:
        print('Fleet status unavailable:', type(error).__name__)
else:
    print('Vultr credentials are not configured')
STATUS
