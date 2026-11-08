#!/usr/bin/env bash
set -euo pipefail

echo "[*] Initializing Fast CSV Tool..."
cat << 'EOF' > /tmp/sample.csv
name,role,department
Alice,Engineer,Security
Bob,Analyst,DevOps
Charlie,Designer,Product
EOF

echo "[*] Converting CSV to JSON stream:"
awk -F',' 'NR==1 {split($0, headers); next} {
  printf "{\"%s\":\"%s\",\"%s\":\"%s\",\"%s\":\"%s\"}\n", headers[1], $1, headers[2], $2, headers[3], $3
}' /tmp/sample.csv

rm -f /tmp/sample.csv
echo "[+] Processing completed successfully without external dependencies."
