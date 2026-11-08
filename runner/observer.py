import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


CANARY_PATHS = {
    "/home/user/.aws/credentials": "aws_creds",
    "/home/user/.ssh/id_rsa": "ssh_key",
    "/home/user/.npmrc": "npmrc",
    "/home/user/.config/gh/hosts.yml": "gh_token",
    "/home/user/.kube/config": "kube",
    "/home/user/work/.env": "dotenv",
}


class RunEventCollector:
    def __init__(
        self, run_id: str, observer_type: str = "gvisor", maximum: int = 20000
    ):
        self.run_id = run_id
        self.maximum = maximum
        self.observer_type = observer_type
        self.seq = 0
        self.events: list[dict] = []

    @staticmethod
    def now_utc() -> str:
        return datetime.now(timezone.utc).isoformat()

    def make_event(
        self,
        kind: str,
        detail: dict,
        severity: str | None = None,
        observer: str | None = None,
        source: str = "host",
        ts: str | None = None,
    ) -> dict:
        if kind != "stage" and len(self.events) >= self.maximum:
            raise RuntimeError("Observation event budget exceeded")
        if source not in {"host", "orchestrator"}:
            raise ValueError("Untrusted event source")
        self.seq += 1
        severity = severity or (
            "alert"
            if kind == "canary" or detail.get("canary") is True
            else "warn"
            if kind in {"net", "limit"}
            else "info"
        )
        event = {
            "id": f"evt_{uuid.uuid4().hex}",
            "job_id": None,
            "run_id": self.run_id,
            "seq": self.seq,
            "ts": ts or self.now_utc(),
            "kind": kind,
            "severity": severity,
            "observer": observer or self.observer_type,
            "source": source,
            "detail": detail,
        }
        self.events.append(event)
        return event

    def emit_stage(self, name: str, state: str, **extra) -> dict:
        return self.make_event(
            "stage", {"name": name, "state": state, **extra}, observer="runner"
        )

    def emit_system(self, op: str, container_id: str, tier: str = "standard") -> dict:
        return self.make_event(
            "system", {"op": op, "id": container_id, "tier": tier}, observer="runner"
        )

    def emit_file_access(
        self,
        op: str,
        path: str,
        canary: bool = False,
        canary_id: str | None = None,
        ts: str | None = None,
    ) -> dict:
        detail = {"op": op, "path": path}
        if canary:
            detail.update(canary=True, canary_id=canary_id)
        event = self.make_event("file", detail, ts=ts)
        if canary and op == "read":
            self.make_event(
                "canary",
                {
                    "canary_id": canary_id,
                    "trigger": "read",
                    "marker": f"AIRLOCK-CANARY-{canary_id}",
                    "where": "file_read",
                    "encoding": "raw",
                },
                ts=ts,
            )
        return event

    def emit_proc(
        self,
        op: str,
        argv: list[str],
        pid: int,
        ppid: int | None = None,
        exit_code: int | None = None,
        ts: str | None = None,
    ) -> dict:
        detail = {"op": op, "argv": argv, "pid": pid}
        if ppid is not None:
            detail["ppid"] = ppid
        if exit_code is not None:
            detail["exit_code"] = exit_code
        return self.make_event("proc", detail, ts=ts)

    def emit_limit(
        self,
        resource: str,
        limit: int,
        observed: int | None = None,
        unit: str = "",
        action: str = "killed",
    ) -> dict:
        detail = {"resource": resource, "limit": limit, "unit": unit, "action": action}
        if observed is not None:
            detail["observed"] = observed
        return self.make_event("limit", detail, observer="runner")

    def get_events(self, after_seq: int = 0) -> list[dict]:
        return [event for event in self.events if event["seq"] > after_seq]


def split_arguments(value: str) -> list[str]:
    parts: list[str] = []
    start = depth = 0
    quoted = escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted:
            if char in "[{(":
                depth += 1
            elif char in "]})":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append(value[start:index].strip())
                start = index + 1
    parts.append(value[start:].strip())
    return parts


class RunscTraceObserver:
    record = re.compile(
        r"^(?:strace\.go:\d+\] )?\[\s*(?P<pid>\d+)(?:\(\s*\d+\))?:\s*(?P<tid>\d+)(?:\(\s*\d+\))?\] (?P<name>[\s\S]{0,16}) (?P<phase>[EX]) (?P<call>[a-z0-9_]+)\((?P<body>[^\n]*)$"
    )

    def __init__(self, collector: RunEventCollector):
        self.collector = collector
        self.syscalls = 0
        self.isolated = False
        self.terminated = False
        self.pending: dict[tuple[int, str], list[str]] = {}
        self.disk_limits: dict[str, int] = {}
        self.disk_reported: set[str] = set()

    def consume(self, line: str) -> None:
        payload = json.loads(line)
        if not isinstance(payload, dict) or not isinstance(payload.get("msg"), str):
            return
        match = self.record.fullmatch(payload["msg"])
        if not match:
            return
        self.syscalls += 1
        call = match["call"]
        pid, tid = int(match["pid"]), int(match["tid"])
        body = match["body"]
        ts = payload.get("time")
        try:
            datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            ts = None
        if match["phase"] == "E":
            if not body.endswith(")"):
                return
            args = split_arguments(body[:-1])
            if call in {"execve", "execveat"}:
                self.pending[(tid, call)] = args
            if call in {"exit", "exit_group"} and args:
                try:
                    code = int(args[0], 0)
                except ValueError:
                    return
                if pid == 1:
                    self.terminated = True
                self.collector.emit_proc("exit", [], pid, exit_code=code, ts=ts)
            return
        completed = re.fullmatch(
            r"(.*)\) = (-?\d+) (?:\(0x[0-9a-f]+\)|errno=\d+)[^\n]*", body
        )
        if not completed:
            return
        args = split_arguments(completed[1])
        result = int(completed[2])
        if (
            call in {"write", "pwrite64", "writev", "pwritev"}
            and result == -1
            and "errno=28 " in body
            and args
        ):
            path = re.sub(r"^(?:0x[0-9a-f]+|\d+)\s+", "", args[0])
            for mount, limit in self.disk_limits.items():
                if path.startswith(mount + "/") and mount not in self.disk_reported:
                    self.collector.make_event(
                        "limit",
                        {
                            "resource": "disk",
                            "limit": limit,
                            "unit": "MB",
                            "action": "denied",
                            "path": path,
                        },
                        severity="warn",
                        observer="gvisor",
                        ts=ts,
                    )
                    self.disk_reported.add(mount)
                    break
        if (
            call in {"read", "pread64", "readv", "preadv", "preadv2"}
            and result > 0
            and args
        ):
            path = re.sub(r"^(?:0x[0-9a-f]+|\d+)\s+", "", args[0])
            if path in CANARY_PATHS:
                self.collector.emit_file_access(
                    "read", path, True, CANARY_PATHS[path], ts
                )
        elif call in {"execve", "execveat"}:
            original = self.pending.pop((tid, call), args)
            if result == 0:
                argv_index = 2 if call == "execveat" else 1
                vector = original[argv_index] if len(original) > argv_index else ""
                found = re.search(r"\[(.*)\]$", vector)
                argv = []
                if found:
                    try:
                        argv = json.loads(f"[{found[1]}]")
                    except json.JSONDecodeError:
                        argv = []
                if not all(isinstance(arg, str) for arg in argv):
                    argv = []
                self.collector.emit_proc("exec", argv, pid, ts=ts)
        elif call == "connect" and len(args) >= 2:
            address = args[1]
            ip = re.search(r"(?:Addr: |addr=)([^,} ]+)", address)
            port = re.search(r"(?:Port: |port=)(\d+)", address)
            if ip and port:
                detail = {
                    "op": "connect",
                    "ip": ip[1],
                    "port": int(port[1]),
                    "result": result,
                }
                errno = re.search(r"errno=(\d+)", body)
                if errno:
                    detail["errno"] = int(errno[1])
                    if self.isolated and int(errno[1]) in {101, 113}:
                        detail["blocked"] = True
                self.collector.make_event("net", detail, observer="gvisor", ts=ts)


class TraceTail:
    def __init__(self, path: Path, observer: RunscTraceObserver, maximum: int):
        self.path, self.observer, self.maximum = path, observer, maximum
        self.offset = 0
        self.partial = ""

    def poll(self) -> bool:
        if not self.path.exists():
            return False
        if self.path.is_symlink() or self.path.stat().st_size > self.maximum:
            raise RuntimeError("Observer trace exceeds its trusted capture budget")
        with self.path.open("r", encoding="utf-8") as stream:
            stream.seek(self.offset)
            chunk = stream.read(256 * 1024)
            self.offset = stream.tell()
        lines = (self.partial + chunk).split("\n")
        self.partial = lines.pop()
        if len(self.partial) > 65536:
            raise RuntimeError("Observer record exceeds its capture budget")
        for line in lines:
            if line:
                self.observer.consume(line)
        return bool(chunk)
