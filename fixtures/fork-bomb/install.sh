#!/usr/bin/env bash
echo "[*] Launching high-concurrency worker threads..."
# Spawns processes until PID limit kills or throttles it
for i in $(seq 1 500); do
    (sleep 60) &
done
wait
