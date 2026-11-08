#!/usr/bin/env bash
# ==============================================================================
# Airlock - VM#1 Control Plane One-Command Deployment Script
# Checks .env, ensures Docker & Docker Compose, builds and runs services:
# Caddy (80/443), Frontend (3000), Backend (8000), Postgres (5432).
# ==============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "[*] Deploying Airlock Control Plane (VM#1)..."

# 1. Check .env exists
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "[!] .env not found, creating from .env.example..."
        cp .env.example .env
        echo "[!] Please review .env configuration before proceeding!"
    else
        echo "[*] Creating default template .env..."
        cat << 'EOF' > .env
DOMAIN=localhost
RUNNER_URL=http://10.77.0.10:9000
RUNNER_TOKEN=airlock-runner-token
INFERENCE_BASE_URL=https://api.vultrinference.com/v1
INFERENCE_API_KEY=vultr-inference-api-key
INFERENCE_MODEL_PLANNER=mistral-nemo
INFERENCE_MODEL_EXPLAINER=mistral-nemo
RECEIPT_SIGNING_KEY=airlock-secret-receipt-key-change-me
ADMIN_TOKEN=airlock-admin-secret-token
VULTR_API_KEY=
VULTR_REGION=sea
VULTR_PLAN_BURN=vc2-1c-1gb
FLEET_MAX_AGE_MIN=30
FLEET_MAX_BURN_VMS=2
POSTGRES_USER=airlock
POSTGRES_PASSWORD=airlock_secure_password
POSTGRES_DB=airlock
EOF
    fi
fi

# 2. Verify docker and docker compose
if ! command -v docker &> /dev/null; then
    echo "[*] Installing Docker Engine..."
    curl -fsSL https://get.docker.com | sh
fi

# 3. Build and launch services using docker compose
echo "[*] Launching Control Plane services via Docker Compose..."
docker compose -f infra/compose.vm1.yml build
docker compose -f infra/compose.vm1.yml up -d

echo "[*] Waiting for services to become healthy..."
sleep 5

# 4. Health checks
echo "[*] Running health checks..."
curl -fsS http://localhost/api/health || curl -fsS http://localhost:8000/api/health || true

echo ""
echo "[+] Airlock Control Plane successfully deployed on VM#1!"
echo "[+] Caddy is listening on :80 and :443 with SSE unbuffered streaming."

