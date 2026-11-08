#!/usr/bin/env bash
# ==============================================================================
# Airlock - VM#2 Sandbox Host Idempotent Setup Script
# Installs Docker, gVisor (runsc), builds sandbox & sink images,
# sets up isolated honeynet docker network, and launches the Runner API.
# ==============================================================================
set -euo pipefail

echo "[*] Starting Airlock Sandbox Host (VM#2) setup..."

export DEBIAN_FRONTEND=noninteractive

# 1. System packages
echo "[*] Updating apt packages..."
apt-get update && apt-get install -y --no-install-recommends \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    iptables \
    ufw \
    jq

# 2. Install Docker
if ! command -v docker &> /dev/null; then
    echo "[*] Installing Docker Engine..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# 3. Install gVisor (runsc)
if ! command -v runsc &> /dev/null; then
    echo "[*] Installing Google gVisor (runsc)..."
    ARCH=$(uname -m)
    URL="https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}"
    curl -fsSL "${URL}/runsc" -o /usr/local/bin/runsc
    chmod +x /usr/local/bin/runsc
fi

# 4. Register runsc in Docker daemon configuration
echo "[*] Configuring Docker runtime with runsc..."
mkdir -p /etc/docker
cat << 'EOF' > /etc/docker/daemon.json
{
  "runtimes": {
    "runsc": {
      "path": "/usr/local/bin/runsc",
      "runtimeArgs": [
        "--debug",
        "--debug-log-dir=/var/log/runsc",
        "--strace"
      ]
    }
  }
}
EOF
systemctl daemon-reload
systemctl restart docker

# 5. Create Honeynet Docker Network (Internal, isolated)
echo "[*] Setting up isolated internal honeynet network..."
if ! docker network inspect airlock-honeynet &> /dev/null; then
    docker network create \
      --driver bridge \
      --internal \
      --subnet=10.77.0.0/24 \
      --gateway=10.77.0.1 \
      airlock-honeynet
fi

# 6. Build Sandbox Image (airlock-sandbox:node-py)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "[*] Building airlock-sandbox:node-py image from ${REPO_ROOT}/runner/docker/Dockerfile.sandbox..."
docker build -t airlock-sandbox:node-py -f "${REPO_ROOT}/runner/docker/Dockerfile.sandbox" "${REPO_ROOT}/runner/docker"

# 7. Build and Run Honeynet Sink Container
echo "[*] Building and starting Honeynet Sink container..."
docker build -t airlock-sink:latest -f "${REPO_ROOT}/runner/docker/Dockerfile.sink" "${REPO_ROOT}/runner/docker"
docker rm -f airlock-sink 2>/dev/null || true
docker run -d \
  --name airlock-sink \
  --restart unless-stopped \
  --network airlock-honeynet \
  --ip 10.77.0.2 \
  airlock-sink:latest

# 8. Firewall Configuration (UFW / iptables)
echo "[*] Hardening firewall for VM#2..."
# Allow SSH and VPC internal subnet, drop public access to port 9000
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH management"
# Allow traffic from VM#1 private IP or VPC
if [ -n "${CONTROL_PLANE_IP:-}" ]; then
    ufw allow from "${CONTROL_PLANE_IP}" to any port 9000 proto tcp comment "Airlock Control Plane"
else
    # Default allow RFC1918 private subnets
    ufw allow from 10.0.0.0/8 to any port 9000 proto tcp
    ufw allow from 172.16.0.0/12 to any port 9000 proto tcp
    ufw allow from 192.168.0.0/16 to any port 9000 proto tcp
fi
ufw --force enable

# 9. Launch Runner API Service via Docker or Systemd
echo "[*] Building and starting Airlock Runner Service..."
docker build -t airlock-runner:latest -f "${REPO_ROOT}/runner/Dockerfile" "${REPO_ROOT}"
docker rm -f airlock-runner 2>/dev/null || true
docker run -d \
  --name airlock-runner \
  --restart unless-stopped \
  -p 9000:9000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp/airlock-runs:/tmp/airlock-runs \
  -e RUNNER_TOKEN="${RUNNER_TOKEN:-airlock-runner-token}" \
  -e RUNNER_RUNTIME=runsc \
  -e RUNNER_OBSERVER=gvisor \
  airlock-runner:latest

echo "[+] Airlock Sandbox Host VM#2 setup completed successfully!"
echo "[+] Health check: curl -H \"Authorization: Bearer ${RUNNER_TOKEN:-airlock-runner-token}\" http://localhost:9000/healthz"

