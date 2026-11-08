#!/usr/bin/env bash
set -euo pipefail
[[ "${EUID}" -eq 0 ]]
: "${RUNNER_TOKEN:?Provide RUNNER_TOKEN through a secure environment}"
: "${CONTROL_PLANE_IP:?Set the control plane IPv4 address}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends docker.io python3 curl ca-certificates iptables
systemctl enable --now docker
if [[ ! -x /usr/local/bin/runsc || ! -d /usr/local/bin/gvisor-bin ]]; then
    architecture="$(uname -m)"
    download_dir="$(mktemp -d)"
    release_url="https://storage.googleapis.com/gvisor/releases/release/latest/${architecture}"
    curl --fail --silent --show-error "${release_url}/gvisor.tar.bz2" --output "${download_dir}/gvisor.tar.bz2"
    curl --fail --silent --show-error "${release_url}/gvisor.tar.bz2.sha512" --output "${download_dir}/gvisor.tar.bz2.sha512"
    (cd "${download_dir}" && sha512sum --check gvisor.tar.bz2.sha512)
    tar --extract --bzip2 --file "${download_dir}/gvisor.tar.bz2" --directory /usr/local/bin
    chmod a+rx /usr/local/bin/runsc /usr/local/bin/gvisor-bin /usr/local/bin/gvisor-bin/*
    rm -rf "${download_dir}"
fi
install --directory --mode=0700 /var/log/airlock-runsc
install --directory --mode=0755 /tmp/airlock-runs /etc/docker
python3 - <<'CONFIG'
import json
from pathlib import Path
path = Path('/etc/docker/daemon.json')
config = json.loads(path.read_text()) if path.exists() else {}
config.setdefault('runtimes', {})['runsc-observed'] = {
    'path': '/usr/local/bin/runsc',
    'runtimeArgs': ['--debug-log=/var/log/airlock-runsc/%ID%.%COMMAND%.json',
                    '--debug-log-format=json', '--debug', '--strace', '--strace-log-size=128',
                    '--strace-syscalls=read,pread64,readv,preadv,write,pwrite64,writev,pwritev,execve,execveat,connect,clone,clone3,fork,vfork,exit,exit_group']
}
temporary = path.with_suffix('.airlock.tmp')
temporary.write_text(json.dumps(config, indent=2))
temporary.replace(path)
CONFIG
install --mode=0755 "${repo_root}/infra/network_guard.sh" /usr/local/sbin/airlock-network-guard
install --directory --mode=0755 /etc/airlock /etc/systemd/system/docker.service.d
printf 'CONTROL_PLANE_IP=%s\nALLOW_PUBLIC_CONTROL_PLANE=%s\n' "${CONTROL_PLANE_IP}" "${ALLOW_PUBLIC_CONTROL_PLANE:-0}" > /etc/airlock/network-guard.conf
CONTROL_PLANE_IP="${CONTROL_PLANE_IP}" ALLOW_PUBLIC_CONTROL_PLANE="${ALLOW_PUBLIC_CONTROL_PLANE:-0}" /usr/local/sbin/airlock-network-guard
cat > /etc/systemd/system/airlock-network-guard.service <<'SERVICE'
[Unit]
Description=Airlock sandbox and Runner network isolation
Before=docker.service
[Service]
Type=oneshot
EnvironmentFile=/etc/airlock/network-guard.conf
ExecStart=/usr/local/sbin/airlock-network-guard
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
SERVICE
cat > /etc/systemd/system/docker.service.d/airlock-guard.conf <<'SERVICE'
[Unit]
Requires=airlock-network-guard.service
After=airlock-network-guard.service
SERVICE
printf 'd /var/log/airlock-runsc 0700 root root 1d -\n' > /etc/tmpfiles.d/airlock-runsc.conf
systemctl daemon-reload
systemctl enable --now airlock-network-guard.service
systemctl restart docker
docker build -t airlock-sandbox:node-py -f "${repo_root}/runner/docker/Dockerfile.sandbox" "${repo_root}"
docker build -t airlock-sink:latest -f "${repo_root}/runner/docker/Dockerfile.sink" "${repo_root}"
docker build -t airlock-runner:latest -f "${repo_root}/runner/Dockerfile" "${repo_root}"
if docker container inspect airlock-runner >/dev/null 2>&1; then
    docker stop airlock-runner
    docker rm airlock-runner
fi
docker run -d --name airlock-runner --restart unless-stopped --network host --cap-add=NET_ADMIN \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v /tmp/airlock-runs:/tmp/airlock-runs \
    -v /var/log/airlock-runsc:/var/log/airlock-runsc:ro \
    -v /sys/fs/cgroup:/host-cgroup:ro \
    -e RUNNER_TOKEN -e RUNNER_RUNTIME=runsc-observed -e CGROUP_ROOT=/host-cgroup airlock-runner:latest
curl --fail --silent --show-error http://127.0.0.1:9000/healthz
