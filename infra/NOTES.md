# Airlock Sandbox Host — Spike & Isolation Decision Notes

**Date:** 2026-11-08  
**Engineer:** Bakhtiyar (Infrastructure & Sandbox Execution Lead)  
**Host Architecture:** Vultr Cloud Compute (x86_64, Linux 6.x)  

---

## 1. Spike Goal & Constraints
Evaluate container isolation engines on Vultr Cloud Compute instances to determine runtime capabilities and host-side telemetry collection.

Organizer focus criteria:
- **Process Isolation** (non-root, cap-drop, read-only rootfs, tmpfs)
- **Secret Hygiene** (zero host secrets in sandbox, only canaries)
- **Resource Limits** (CPU, RAM cgroups, PID limits, execution timeouts)
- **Lifecycle Discipline** (disposable ephemeral container per run, guaranteed teardown)

---

## 2. Tested Options & Evaluation

### Option A (Preferred): gVisor (`runsc`) + Host-Side Telemetry
- **Runtime:** `runsc` (Google gVisor application kernel).
- **Setup:** Registered `/usr/local/bin/runsc` in `/etc/docker/daemon.json` under `runtimes.runsc`.
- **Verified flags:**
  ```bash
  docker run --rm \
    --runtime=runsc \
    --read-only \
    --tmpfs /home/user:rw,nosuid,size=128m,mode=0700,uid=1000,gid=1000 \
    --tmpfs /tmp:rw,nosuid,size=64m,mode=1777 \
    --cap-drop=ALL \
    --security-opt=no-new-privileges:true \
    --user=1000:1000 \
    --cpus=1.0 \
    --memory=512m \
    --pids-limit=128 \
    --network=airlock-honeynet \
    airlock-sandbox:node-py
  ```
- **Syscall / Host-side observation:**
  `runsc` flags `--debug --debug-log-dir=/var/log/runsc --strace` enable kernel-intercept logging on the host without relying on in-guest cooperation.
- **Verdict for Vultr Cloud Compute:** Works without nested virtualization on regular KVM cloud compute. When runsc is installed, `/healthz` reports `runtime: "runsc"`, `observer: "gvisor"`.

### Option B (Fallback): Docker `runc` + Strict Seccomp Profile & Strace Observer
- If `runsc` is not pre-installed or disabled in dev environments, runner falls back to `runc` with `--security-opt seccomp=/etc/docker/airlock-seccomp.json`.
- In-guest ptrace restricted strictly to container's isolated PID namespace.
- Honest reporting: `/healthz` transparently reports `runtime: "runc"`, `observer: "strace"`.

---

## 3. Final Decision
- **Production VM#2:** Option A (`runsc` + host honeynet sink).
- **Graceful Fallback:** Option B transparently activated if `runsc` binary is absent.
- **/healthz contract:** Compliant with §4 of Shared Contract v1.0.

