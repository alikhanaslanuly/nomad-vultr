import ipaddress
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone


VULTR_API_BASE = "https://api.vultr.com/v2"


class FleetError(RuntimeError):
    pass


class FleetManager:
    def __init__(self):
        self.runner_url = os.getenv("RUNNER_URL", "").rstrip("/")
        self.runner_token = os.getenv("RUNNER_TOKEN", "")
        self.vultr_api_key = os.getenv("VULTR_API_KEY", "")
        self.vultr_region = os.getenv("VULTR_REGION", "")
        self.vultr_plan_burn = os.getenv("VULTR_PLAN_BURN", "")
        self.vultr_snapshot_id = os.getenv("VULTR_SNAPSHOT_ID", "")
        self.firewall_group = os.getenv("VULTR_FIREWALL_GROUP_ID", "")
        self.vpc_id = os.getenv("VULTR_VPC_ID", "")
        self.owner_tag = os.getenv("FLEET_OWNER_TAG", "")
        self.fleet_max_age_min = int(os.getenv("FLEET_MAX_AGE_MIN", "30"))
        self.fleet_max_burn_vms = int(os.getenv("FLEET_MAX_BURN_VMS", "2"))
        self.timeout = float(os.getenv("FLEET_READY_TIMEOUT_S", "300"))
        self.poll_interval = float(os.getenv("FLEET_POLL_INTERVAL_S", "2"))
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return all(
            (
                self.vultr_api_key,
                self.vultr_region,
                self.vultr_plan_burn,
                self.vultr_snapshot_id,
                self.firewall_group,
                self.vpc_id,
                self.runner_token,
                self.owner_tag,
            )
        )

    def _request(
        self, method: str, path: str, payload: dict | None = None
    ) -> dict | None:
        request = urllib.request.Request(
            f"{VULTR_API_BASE}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "Authorization": f"Bearer {self.vultr_api_key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                content = response.read(2 * 1024 * 1024)
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as error:
            if error.code == 404 and method in {"GET", "DELETE"}:
                return None
            raise FleetError(
                f"Vultr {method} request failed (HTTP {error.code}); response redacted"
            ) from None
        except (OSError, ValueError):
            raise FleetError(
                f"Vultr {method} request failed; response redacted"
            ) from None

    def _instances(self) -> list[dict]:
        instances = []
        cursor = ""
        for _ in range(20):
            from urllib.parse import urlencode

            page = (
                self._request(
                    "GET",
                    "/instances?"
                    + urlencode(
                        {"per_page": 100, **({"cursor": cursor} if cursor else {})}
                    ),
                )
                or {}
            )
            instances.extend(
                instance
                for instance in page.get("instances", [])
                if self.owner_tag in instance.get("tags", [])
                and "airlock-burn" in instance.get("tags", [])
            )
            cursor = page.get("meta", {}).get("links", {}).get("next") or ""
            if not cursor:
                return instances
        raise FleetError("Vultr instance pagination limit reached")

    @staticmethod
    def event(op: str, vm_id: str, **extra) -> dict:
        return {
            "kind": "system",
            "severity": "info",
            "source": "orchestrator",
            "observer": "orchestrator",
            "run_id": None,
            "ts": datetime.now(timezone.utc).isoformat(),
            "detail": {"op": op, "id": vm_id, "tier": "burn", **extra},
        }

    def _probe_runner(self, base_url: str) -> bool:
        request = urllib.request.Request(
            f"{base_url}/healthz",
            headers={"Authorization": f"Bearer {self.runner_token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                state = json.loads(response.read(65536))
                return (
                    state.get("ok") is True
                    and state.get("runtime") == "runsc"
                    and state.get("observer") == "gvisor"
                    and state.get("observer_verified") is True
                )
        except (OSError, ValueError):
            return False

    def _wait_ready(self, vm_id: str) -> str:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            response = self._request("GET", f"/instances/{vm_id}")
            if response is None:
                raise FleetError("Vultr instance disappeared before readiness")
            instance = response.get("instance", {})
            if all(
                instance.get(key) == value
                for key, value in (
                    ("status", "active"),
                    ("power_status", "running"),
                    ("server_status", "ok"),
                )
            ):
                networks = self._request("GET", f"/instances/{vm_id}/vpcs") or {}
                address = next(
                    (
                        network.get("ip_address", "")
                        for network in networks.get("vpcs", [])
                        if network.get("id") == self.vpc_id
                    ),
                    "",
                )
                try:
                    ip = ipaddress.ip_address(address)
                except ValueError:
                    ip = None
                if ip and ip.is_private and not ip.is_loopback:
                    base_url = f"http://{address}:9000"
                    if self._probe_runner(base_url):
                        return base_url
            time.sleep(self.poll_interval)
        raise FleetError("Vultr VM or verified Runner readiness timed out")

    def acquire(self, tier: str, job_id: str):
        from . import RunnerHandle

        if tier == "standard":
            if not self.runner_url or not self.runner_token:
                raise FleetError("Standard Runner is not configured")
            return RunnerHandle(self.runner_url, self.runner_token, "standard")
        if tier != "burn" or not self.configured:
            raise FleetError(
                "Real Burn VM requires API credentials, snapshot, region, plan, VPC, firewall and runner authentication; no mock fallback"
            )
        with self._lock:
            if len(self._instances()) >= self.fleet_max_burn_vms:
                raise FleetError("Burn VM concurrency limit reached")
            payload = {
                "region": self.vultr_region,
                "plan": self.vultr_plan_burn,
                "os_id": 164,
                "snapshot_id": self.vultr_snapshot_id,
                "firewall_group_id": self.firewall_group,
                "vpc_ids": [self.vpc_id],
                "label": f"airlock-burn-{job_id[:24]}",
                "tags": [self.owner_tag, "airlock-burn", f"job-{job_id}"],
            }
            response = self._request("POST", "/instances", payload) or {}
            instance = response.get("instance", {})
            vm_id = instance.get("id")
            try:
                uuid.UUID(vm_id)
            except (ValueError, TypeError, AttributeError):
                raise FleetError(
                    "Vultr did not return a real instance ID; inspect the account for an orphan"
                ) from None
            try:
                base_url = self._wait_ready(vm_id)
            except FleetError as error:
                try:
                    self._delete_confirmed(vm_id)
                except FleetError:
                    raise FleetError(
                        f"Provisioning and cleanup failed for instance {vm_id}; operator cleanup required"
                    ) from None
                raise error
            return RunnerHandle(
                base_url,
                self.runner_token,
                "burn",
                vm_id,
                [
                    self.event(
                        "vm_create",
                        vm_id,
                        plan=self.vultr_plan_burn,
                        region=self.vultr_region,
                    ),
                    self.event("runner_ready", vm_id),
                ],
            )

    def _delete_confirmed(self, vm_id: str):
        try:
            uuid.UUID(vm_id)
        except (ValueError, TypeError, AttributeError):
            raise FleetError("Refusing invalid VM identity") from None
        self._request("DELETE", f"/instances/{vm_id}")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self._request("GET", f"/instances/{vm_id}") is None:
                return
            time.sleep(self.poll_interval)
        raise FleetError(
            f"Deletion unconfirmed for instance {vm_id}; operator cleanup required"
        )

    def release(self, handle, destroy: bool = True) -> list:
        if handle.tier != "burn" or not handle.vm_id or not destroy:
            return []
        if not self.vultr_api_key:
            raise FleetError("Vultr credentials missing; deletion was not performed")
        state = self._request("GET", f"/instances/{handle.vm_id}")
        if state is not None:
            tags = state.get("instance", {}).get("tags", [])
            if self.owner_tag not in tags or "airlock-burn" not in tags:
                raise FleetError(
                    "Refusing to delete an instance outside this fleet's ownership tags"
                )
            self._delete_confirmed(handle.vm_id)
        return [self.event("vm_destroy", handle.vm_id, confirmed=True)]

    def reap(self) -> int:
        if not self.vultr_api_key:
            raise FleetError("Vultr credentials missing; reaping unavailable")
        from . import RunnerHandle

        count = 0
        for instance in self._instances():
            created = datetime.fromisoformat(
                instance["date_created"].replace("Z", "+00:00")
            )
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if (
                datetime.now(timezone.utc) - created
            ).total_seconds() > self.fleet_max_age_min * 60:
                self.release(
                    RunnerHandle("", self.runner_token, "burn", instance["id"]), True
                )
                count += 1
        return count
