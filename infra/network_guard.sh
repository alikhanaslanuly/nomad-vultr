#!/usr/bin/env bash
set -euo pipefail
[[ "${EUID}" -eq 0 ]]
: "${CONTROL_PLANE_IP:?Set the control plane private IPv4 address}"
python3 - "${CONTROL_PLANE_IP}" <<'VALIDATE'
import ipaddress
import sys
address = ipaddress.IPv4Address(sys.argv[1])
if not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
    raise SystemExit("CONTROL_PLANE_IP must be a private unicast IPv4 address")
VALIDATE
if ! iptables -nL DOCKER-USER >/dev/null 2>&1; then
    iptables -N DOCKER-USER
fi
if ! iptables -C INPUT -i alock+ -j DROP 2>/dev/null; then
    iptables -I INPUT -i alock+ -j DROP
fi
if ! iptables -C DOCKER-USER -i alock+ ! -o alock+ -j DROP 2>/dev/null; then
    iptables -I DOCKER-USER -i alock+ ! -o alock+ -j DROP
fi
if ! iptables -nL AIRLOCK-RUNNER >/dev/null 2>&1; then
    iptables -N AIRLOCK-RUNNER
fi
iptables -F AIRLOCK-RUNNER
iptables -A AIRLOCK-RUNNER -i lo -j ACCEPT
iptables -A AIRLOCK-RUNNER -s "${CONTROL_PLANE_IP}" -j ACCEPT
iptables -A AIRLOCK-RUNNER -j DROP
if ! iptables -C INPUT -p tcp --dport 9000 -j AIRLOCK-RUNNER 2>/dev/null; then
    iptables -I INPUT -p tcp --dport 9000 -j AIRLOCK-RUNNER
fi
