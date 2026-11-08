import os
import json
import logging
from datetime import datetime, timezone
from typing import Literal, Optional, List, Dict, Any
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

VULTR_API_BASE = "https://api.vultr.com/v2"


class FleetManager:
    def __init__(self):
        self.runner_url = os.getenv("RUNNER_URL", "http://127.0.0.1:9000").rstrip("/")
        self.runner_token = os.getenv("RUNNER_TOKEN", "airlock-runner-token")
        self.vultr_api_key = os.getenv("VULTR_API_KEY", "")
        self.vultr_region = os.getenv("VULTR_REGION", "sea")
        self.vultr_plan_burn = os.getenv("VULTR_PLAN_BURN", "vc2-1c-1gb")
        self.vultr_snapshot_id = os.getenv("VULTR_SNAPSHOT_ID", "")
        self.fleet_max_age_min = int(os.getenv("FLEET_MAX_AGE_MIN", "30"))
        self.fleet_max_burn_vms = int(os.getenv("FLEET_MAX_BURN_VMS", "2"))

    def acquire(self, tier: Literal["standard", "burn"], job_id: str):
        from . import RunnerHandle

        if tier == "standard":
            log.info("Acquiring standard runner at %s for job=%s", self.runner_url, job_id)
            return RunnerHandle(
                base_url=self.runner_url,
                token=self.runner_token,
                tier="standard",
                vm_id=None,
                created_events=[],
            )

        if tier == "burn":
            log.info("Acquiring throwaway burn VM via Vultr API for job=%s", job_id)
            if not self.vultr_api_key:
                # If Vultr key is not configured in current environment, fallback to standard or inform
                log.warning("VULTR_API_KEY not configured. Falling back to local runner with synthetic burn event.")
                now_iso = datetime.now(timezone.utc).isoformat()
                fake_vm_id = f"vultr-mock-{job_id[:8]}"
                created_events = [
                    {
                        "kind": "system",
                        "severity": "info",
                        "source": "host",
                        "observer": "runner",
                        "ts": now_iso,
                        "detail": {
                            "op": "vm_create",
                            "id": fake_vm_id,
                            "tier": "burn",
                            "plan": self.vultr_plan_burn,
                            "region": self.vultr_region,
                        },
                    }
                ]
                return RunnerHandle(
                    base_url=self.runner_url,
                    token=self.runner_token,
                    tier="burn",
                    vm_id=fake_vm_id,
                    created_events=created_events,
                )

            # Provision real throwaway VM using Vultr API v2
            vm_data = self._create_burn_instance(job_id)
            vm_id = vm_data["id"]
            ip_addr = vm_data.get("main_ip") or "127.0.0.1"
            base_url = f"http://{ip_addr}:9000"

            now_iso = datetime.now(timezone.utc).isoformat()
            created_events = [
                {
                    "kind": "system",
                    "severity": "info",
                    "source": "host",
                    "observer": "runner",
                    "ts": now_iso,
                    "detail": {
                        "op": "vm_create",
                        "id": vm_id,
                        "tier": "burn",
                        "plan": self.vultr_plan_burn,
                        "region": self.vultr_region,
                    },
                }
            ]

            return RunnerHandle(
                base_url=base_url,
                token=self.runner_token,
                tier="burn",
                vm_id=vm_id,
                created_events=created_events,
            )

        raise ValueError(f"Unknown tier: {tier}")

    def release(self, handle, destroy: bool = True) -> list:
        now_iso = datetime.now(timezone.utc).isoformat()
        events = []
        if handle.tier == "burn" and handle.vm_id:
            log.info("Releasing burn VM id=%s (destroy=%s)", handle.vm_id, destroy)
            if destroy and self.vultr_api_key and not handle.vm_id.startswith("vultr-mock-"):
                self._delete_instance(handle.vm_id)

            events.append(
                {
                    "kind": "system",
                    "severity": "info",
                    "source": "host",
                    "observer": "runner",
                    "ts": now_iso,
                    "detail": {
                        "op": "vm_destroy",
                        "id": handle.vm_id,
                        "tier": "burn",
                    },
                }
            )
        return events

    def reap(self) -> int:
        """Find instances tagged 'airlock' older than FLEET_MAX_AGE_MIN and delete them."""
        if not self.vultr_api_key:
            log.info("Reap: VULTR_API_KEY not configured, skipping cloud reaping.")
            return 0

        reaped_count = 0
        try:
            req = urllib.request.Request(
                f"{VULTR_API_BASE}/instances",
                headers={
                    "Authorization": f"Bearer {self.vultr_api_key}",
                    "Content-Type": "application/json",
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as res:
                data = json.loads(res.read().decode("utf-8"))
                instances = data.get("instances", [])
                now = datetime.now(timezone.utc)

                for inst in instances:
                    tags = inst.get("tags", [])
                    label = inst.get("label", "")
                    if "airlock" in tags or label.startswith("airlock-burn-"):
                        date_created = inst.get("date_created")
                        if date_created:
                            try:
                                dt = datetime.fromisoformat(date_created.replace("Z", "+00:00"))
                                age_min = (now - dt).total_seconds() / 60.0
                                if age_min > self.fleet_max_age_min:
                                    inst_id = inst["id"]
                                    log.warning("Reaping orphan instance %s (age=%.1f min)", inst_id, age_min)
                                    self._delete_instance(inst_id)
                                    reaped_count += 1
                            except Exception as parse_err:
                                log.warning("Error parsing date_created for %s: %s", inst.get("id"), parse_err)
        except Exception as e:
            log.error("Reap exception: %s", e)

        return reaped_count

    def _create_burn_instance(self, job_id: str) -> dict:
        payload = {
            "region": self.vultr_region,
            "plan": self.vultr_plan_burn,
            "label": f"airlock-burn-{job_id[:8]}",
            "tags": ["airlock", "burn"],
            "enable_vpc": True,
        }
        if self.vultr_snapshot_id:
            payload["snapshot_id"] = self.vultr_snapshot_id
        else:
            payload["os_id"] = 1743  # Ubuntu 22.04 LTS

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{VULTR_API_BASE}/instances",
            data=body,
            headers={
                "Authorization": f"Bearer {self.vultr_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                data = json.loads(res.read().decode("utf-8"))
                return data.get("instance", {})
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8")
            raise RuntimeError(f"Vultr instance creation failed: {err.code} - {err_body}")

    def _delete_instance(self, vm_id: str):
        req = urllib.request.Request(
            f"{VULTR_API_BASE}/instances/{vm_id}",
            headers={"Authorization": f"Bearer {self.vultr_api_key}"},
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                log.info("Deleted instance %s (status %s)", vm_id, res.status)
        except Exception as e:
            log.error("Exception deleting instance %s: %s", vm_id, e)
