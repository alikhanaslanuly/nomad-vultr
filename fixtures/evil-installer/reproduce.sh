#!/usr/bin/env bash
# One-command local reproducibility test for evil-installer
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOME="/tmp/airlock-test-home"
rm -rf "$HOME" && mkdir -p "$HOME/.aws"

# Seed canary credentials
cat << 'EOF' > "$HOME/.aws/credentials"
[default]
aws_access_key_id = AKIAIOSFODNN7EXAMPLE
aws_secret_access_key = AIRLOCK-CANARY-aws_creds-secret-key-1234567890
EOF

cat << 'EOF' > "$HOME/.npmrc"
//registry.npmjs.org/:_authToken=AIRLOCK-CANARY-npmrc-token-abcdef
EOF

echo "[*] Running evil-installer with simulated honeynet/loopback..."
bash "$DIR/install.sh"
rm -rf "$HOME"
echo "[+] Done test."
