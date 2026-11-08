#!/usr/bin/env bash
# ==============================================================================
# Airlock - Status & Resource Monitoring Utility
# Reports running containers, memory usage, burn VM status, and runner health.
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "          AIRLOCK SANDBOX HOST & FLEET STATUS             "
echo "=========================================================="
echo "Date / Time (UTC): $(date -u)"
echo ""

# 1. System Memory & CPU Load
echo "[1] Host Resources:"
free -h 2>/dev/null || true
echo "Load Average: $(uptime | awk -F'load average:' '{ print $2 }')"
echo ""

# 2. Docker Containers Status
echo "[2] Running Docker Containers:"
if command -v docker &> /dev/null && docker info &> /dev/null; then
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"
    echo ""
    echo "Total active containers: $(docker ps -q | wc -l)"
else
    echo "Docker daemon not reachable locally."
fi
echo ""

# 3. Runner Health Check
echo "[3] Runner API Health Check:"
RUNNER_PORT="${RUNNER_PORT:-9000}"
RUNNER_TOKEN="${RUNNER_TOKEN:-airlock-runner-token}"
if curl -s -f -H "Authorization: Bearer ${RUNNER_TOKEN}" "http://localhost:${RUNNER_PORT}/healthz" 2>/dev/null; then
    echo " -> Runner API is HEALTHY on port ${RUNNER_PORT}"
else
    echo " -> Runner API on port ${RUNNER_PORT} is not responding."
fi
echo ""

# 4. Fleet Burn Instances & Reaper Status
echo "[4] Fleet Status (Vultr Burn Instances):"
python3 -c "
import fleet
print('Standard runner:', fleet.acquire('standard', 'probe'))
print('Reaper query (expired burn VMs): reaped', fleet.reap())
" 2>/dev/null || echo "Fleet module query skipped."

echo "=========================================================="

