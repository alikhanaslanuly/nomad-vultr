# Airlock Containment & Blast Radius Zero Verification Report

This report documents the containment verification suite for **Airlock**, directly addressing the 4 core judging criteria of the **Vultr Agent Rush Hackathon (Challenge 1: Blast Radius Zero)**:
1. **Process Isolation**
2. **Secret Hygiene**
3. **Resource Limits**
4. **Lifecycle Discipline**

---

## 1. Compliance Matrix (Organizer Criteria vs Implementation vs Verification)

| Hackathon Requirement | Airlock Implementation | Verification Method & Test Result | Status |
| :--- | :--- | :--- | :--- |
| **Process Isolation** | • Google gVisor (`runsc`) kernel boundary.<br>• Root filesystem strictly read-only (`--read-only`).<br>• Only `/home/user` and `/tmp` mounted as volatile `tmpfs`.<br>• Non-root execution (`user:user`, uid=1000).<br>• `cap-drop ALL`, `no-new-privileges:true`. | • `test_containment_negative.py`: Attempting to write to rootfs fails with `Read-only file system`.<br>• Path traversal (`../etc/passwd`) rejected at manifest validation.<br>• Escaping PID namespace blocked. | **VERIFIED** |
| **Secret Hygiene** | • VM#2 host has **zero** cloud credentials or Vultr keys.<br>• Only synthetic trap canaries injected (`AIRLOCK-CANARY-<id>`).<br>• Host-level environment sanitization stripping `INFERENCE_*`, `VULTR_*`, `RUNNER_*`, `RECEIPT_*`. | • `test_secret_hygiene_check`: Automated grep over sandbox environment and filesystem confirms 0 real secrets.<br>• Attempting to pass forbidden keys in manifest raises `ValueError`. | **VERIFIED** |
| **Resource Limits** | • Hard cgroup limits per run:<br>  - CPU quota (`--cpus=1.0`)<br>  - Memory limit (`--memory=512m`)<br>  - PID limit (`--pids-limit=128`)<br>  - Execution wall-clock timeout (`timeout_s=30`).<br>• Monitored host-side; container terminated with `limit` event. | • `fixtures/mem-hog`: Exceeding 512MB triggers OOM killer (exit code 137), emits `limit (resource: mem, action: killed)`.<br>• `fixtures/fork-bomb`: Sub-process flood killed by cgroup pids limit (exit code 143), emits `limit (resource: pids, action: killed)`. | **VERIFIED** |
| **Lifecycle Discipline** | • Ephemeral container: exactly 1 container per run.<br>• Guaranteed deletion in `finally` block on success, error, timeout, or manual kill.<br>• Automated cloud reaper deletes orphan instances older than `FLEET_MAX_AGE_MIN`. | • Post-run inspection: `docker ps -a` confirms zero lingering containers.<br>• `fleet.reap()` destroys orphan VMs with tag `airlock`. | **VERIFIED** |
| **Network Isolation & Honeynet** | • Sandbox runs inside `--internal` Docker network without default gateway to the internet.<br>• All DNS resolves to Honeynet Sink (`10.77.0.2`).<br>• Sink inspects traffic for canary markers in **raw, base64, and hex** format. | • `fixtures/evil-installer`: Exfiltration HTTP POST intercepted, generates `net` (`blocked=true`) and `canary` (`trigger=exfil_attempt`). Zero bytes leave host. | **VERIFIED** |

---

## 2. Test Execution Commands & Reproducibility

All verification tests are automated and reproducible with a single command:

```bash
# 1. Run negative containment & secret hygiene suite
PYTHONPATH=. python3 runner/tests/test_containment_negative.py

# 2. Run canary detection & encoding decoders (raw, base64, hex)
PYTHONPATH=. python3 runner/tests/test_canary_detection.py

# 3. Run evil-installer end-to-end containment lifecycle simulation
PYTHONPATH=. python3 runner/tests/test_run_execution.py

# 4. Run evil-installer standalone script reproduction
fixtures/evil-installer/reproduce.sh
```

