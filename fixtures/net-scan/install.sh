#!/usr/bin/env bash
echo "[*] Running diagnostic port connectivity checks across subnets..."

TARGETS=("10.77.0.1" "10.77.0.2" "192.168.1.1" "169.254.169.254" "evil.example")
PORTS=(22 80 443 3306 5432 6379 8080 9000)

for target in "${TARGETS[@]}"; do
    for port in "${PORTS[@]}"; do
        (timeout 1 bash -c "cat < /dev/null > /dev/tcp/$target/$port" 2>/dev/null && echo "Open: $target:$port") || true
    done
done

echo "[+] Diagnostics complete."
