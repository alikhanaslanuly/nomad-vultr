# Airlock Sandbox Host (VM#2) — 15-Minute Disaster Recovery Guide

In the event of VM#2 failure, compromise, or corruption, follow this runbook to restore the Sandbox Host from scratch in under 15 minutes.

---

## Prerequisites
- Vultr Cloud Console access or `VULTR_API_KEY`.
- Assigned Control Plane IP (VM#1).
- Target Vultr region (e.g. `sea` or `ewr`).

---

## Step 1: Provision Fresh VM#2 on Vultr (Time: ~2 minutes)
Using Vultr Web Console or Vultr CLI:
- **Server Type:** Cloud Compute - Regular Performance
- **Plan:** 4 vCPU / 8 GB RAM (approx. $0.06/hr)
- **OS:** Ubuntu 22.04 LTS x64
- **VPC / Private Network:** Enabled (attach to Airlock VPC)
- **Label / Tags:** `airlock-sandbox-host`, tags: `airlock`, `host`

Or via CLI:
```bash
vultr-cli instance create \
  --region sea \
  --plan vc2-4c-8gb \
  --os 1743 \
  --label airlock-sandbox-host \
  --tag airlock
```

---

## Step 2: Clone Airlock Repository (Time: ~1 minute)
SSH into the newly created VM#2:
```bash
ssh root@<NEW_VM2_IP>
git clone https://github.com/<your-org>/airlock.git /opt/airlock
cd /opt/airlock
```

---

## Step 3: Run Idempotent Setup Script (Time: ~5 minutes)
Execute `infra/vm2_setup.sh`:
```bash
export RUNNER_TOKEN="<YOUR_SECRET_RUNNER_TOKEN>"
export CONTROL_PLANE_IP="<VM1_PRIVATE_IP>"

bash infra/vm2_setup.sh
```

This single command automatically:
1. Installs Docker and gVisor (`runsc`).
2. Configures Docker runtime with `--strace` and debug logging.
3. Creates the `--internal` isolated `airlock-honeynet` bridge network.
4. Builds and launches the Honeynet Sink container on `10.77.0.2`.
5. Builds the `airlock-sandbox:node-py` base image.
6. Hardens UFW firewall: blocks public access to port 9000; only allows VM#1 Control Plane IP.
7. Builds and launches `airlock-runner` container on port 9000.

---

## Step 4: Verification (Time: ~1 minute)
Verify host status:
```bash
bash infra/status.sh
```

Verify Runner API health endpoint:
```bash
curl -i -H "Authorization: Bearer <YOUR_SECRET_RUNNER_TOKEN>" http://localhost:9000/healthz
```
Expected response:
```json
{"ok":true,"image_digest":"sha256:airlock-node-py-v1","runtime":"runsc","observer":"gvisor"}
```

---

## Step 5: Update Control Plane (Time: ~1 minute)
If the private IP of VM#2 changed, update `RUNNER_URL` in `/opt/airlock/.env` on VM#1:
```bash
RUNNER_URL=http://<NEW_VM2_PRIVATE_IP>:9000
```
Then restart backend on VM#1:
```bash
docker compose -f infra/compose.vm1.yml restart backend
```

**Total Recovery Time:** ≤ 10 minutes.

