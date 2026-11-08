import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

class RunEventCollector:
    def __init__(self, run_id: str, observer_type: str = "gvisor"):
        self.run_id = run_id
        self.observer_type = observer_type
        self.seq = 0
        self.events: List[Dict[str, Any]] = []

    def now_utc(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def make_event(
        self,
        kind: str,
        detail: Dict[str, Any],
        severity: Optional[str] = None,
        observer: Optional[str] = None,
        source: str = "host",
    ) -> Dict[str, Any]:
        self.seq += 1
        
        # Determine default severity if not provided
        if severity is None:
            if kind == "canary":
                severity = "alert"
            elif kind == "file" and detail.get("canary") is True:
                severity = "alert"
            elif kind == "net":
                severity = "warn"
            elif kind == "limit":
                severity = "warn"
            elif kind == "proc":
                argv = detail.get("argv", [])
                cmd_line = " ".join(argv).lower()
                if any(tool in cmd_line for tool in ["curl", "wget", "nc ", "base64", "bash -c"]):
                    severity = "warn"
                else:
                    severity = "info"
            else:
                severity = "info"

        evt = {
            "id": f"evt_{uuid.uuid4().hex[:16]}",
            "job_id": None,
            "run_id": self.run_id,
            "seq": self.seq,
            "ts": self.now_utc(),
            "kind": kind,
            "severity": severity,
            "observer": observer or self.observer_type,
            "source": source,
            "detail": detail,
        }
        self.events.append(evt)
        return evt

    def emit_stage(self, name: str, state: str, outcome: Optional[str] = None, exit_code: Optional[int] = None, message: Optional[str] = None):
        detail = {"name": name, "state": state}
        if outcome is not None:
            detail["outcome"] = outcome
        if exit_code is not None:
            detail["exit_code"] = exit_code
        if message is not None:
            detail["message"] = message
        return self.make_event("stage", detail, severity="info", observer="runner")

    def emit_system(self, op: str, container_id: str, tier: str = "standard"):
        detail = {"op": op, "id": container_id, "tier": tier}
        return self.make_event("system", detail, severity="info", observer="runner")

    def emit_file_access(self, op: str, path: str, canary: bool = False, canary_id: Optional[str] = None):
        detail = {"op": op, "path": path}
        if canary:
            detail["canary"] = True
            detail["canary_id"] = canary_id
            # 1. file event with alert
            self.make_event("file", detail, severity="alert")
            # 2. separate canary event with trigger=read
            canary_detail = {
                "canary_id": canary_id,
                "trigger": "read",
                "marker": f"AIRLOCK-CANARY-{canary_id}",
                "where": "file_write" if op == "write" else "argv",
                "encoding": "raw"
            }
            return self.make_event("canary", canary_detail, severity="alert")
        return self.make_event("file", detail, severity="info")

    def emit_proc(self, op: str, argv: List[str], pid: int = 100, ppid: int = 1, exit_code: Optional[int] = 0):
        detail = {"op": op, "argv": argv, "pid": pid, "ppid": ppid}
        if exit_code is not None:
            detail["exit_code"] = exit_code
        return self.make_event("proc", detail)

    def emit_limit(self, resource: str, limit: int, observed: int, unit: str, action: str = "killed"):
        detail = {
            "resource": resource,
            "limit": limit,
            "observed": observed,
            "unit": unit,
            "action": action
        }
        return self.make_event("limit", detail, severity="warn", observer="runner")

    def get_events(self, after_seq: int = 0) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["seq"] > after_seq]

