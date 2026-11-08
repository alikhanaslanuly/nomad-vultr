import asyncio
import base64
import binascii
import hashlib
import json
import os
import time
import uuid
from pathlib import Path, PurePosixPath

from .canary import generate_canary_files, generate_profile_env, get_profile_hostname
from .config import settings
from .models import RunManifest
from .observer import RunEventCollector, RunscTraceObserver, TraceTail


BLACKLISTED_ENV_PREFIXES = (
    "INFERENCE_",
    "VULTR_",
    "RUNNER_",
    "RECEIPT_",
    "DATABASE_URL",
    "ADMIN_",
)


async def docker(*args: str, timeout: float = 15) -> str:
    process = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("Docker command timed out") from None
    if process.returncode != 0:
        raise RuntimeError(f"Docker {args[0]} failed")
    return out.decode("utf-8", errors="replace").strip()


async def inspect_container(container: str) -> dict:
    return json.loads(await docker("inspect", container))[0]


class SandboxExecutor:
    def __init__(self, manifest: RunManifest):
        self.manifest = manifest
        self.run_id = manifest.run_id
        self.run_dir = str(Path(settings.RUNS_DIR) / self.run_id)
        self.home_dir = str(Path(self.run_dir) / "home/user")
        self.work_dir = str(Path(self.home_dir) / "work")
        self.artifacts_dir = str(Path(self.run_dir) / "artifacts")
        self.observer = RunEventCollector(self.run_id, maximum=settings.MAX_EVENTS)
        self.trace = RunscTraceObserver(self.observer)
        self.tail: TraceTail | None = None
        self.container_id: str | None = None
        self.sink_id: str | None = None
        self.network_id: str | None = None
        self.is_killed = False
        self.image_digest = ""
        self._sink_process = None
        self._reported_limits: set[str] = set()

    def validate_manifest(self):
        if self.manifest.image != settings.SANDBOX_IMAGE:
            raise ValueError("Sandbox image is not allowed")
        if self.manifest.network.mode == "fetch-allowlist" or (
            self.manifest.fetch and self.manifest.fetch.type
        ):
            raise ValueError(
                "Registry fetching is unavailable; submit a package ZIP instead"
            )
        total = 0
        seen = set()
        for file in self.manifest.files:
            path = PurePosixPath(file.path)
            if (
                not file.path
                or "\\" in file.path
                or path.is_absolute()
                or ".." in path.parts
                or not file.path.startswith("work/")
                or file.path == "work/.env"
                or any(part in {"", ".", ".."} for part in file.path.split("/"))
                or ":" in file.path
                or len(file.path) > 260
                or any(ord(char) < 32 for char in file.path)
                or file.path in seen
            ):
                raise ValueError("Manifest path is forbidden")
            seen.add(file.path)
            try:
                raw = base64.b64decode(file.content_b64, validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("Manifest content must be valid base64") from None
            total += len(raw)
            if len(raw) > 2 * 1024 * 1024 or total > 8 * 1024 * 1024:
                raise ValueError("Manifest exceeds file size limits")
        for key, value in self.manifest.env.items():
            if any(
                key.upper().startswith(prefix) for prefix in BLACKLISTED_ENV_PREFIXES
            ):
                raise ValueError("Environment variable is forbidden in sandbox")
            if (
                len(key) > 100
                or len(value) > 2000
                or "=" in key
                or "\x00" in key + value
            ):
                raise ValueError("Invalid sandbox environment")

    def prepare_filesystem(self):
        home = Path(self.home_dir)
        home.mkdir(parents=True, exist_ok=False)
        Path(self.artifacts_dir).mkdir(parents=True)
        for path, content, _ in generate_canary_files(
            self.manifest.profile, self.home_dir, self.work_dir
        ):
            destination = home / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content)
        for file in self.manifest.files:
            destination = home / file.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(base64.b64decode(file.content_b64, validate=True))

    async def ensure_runtime(self):
        info = json.loads(await docker("info", "--format", "{{json .Runtimes}}"))
        if (
            settings.RUNTIME_PREFERENCE not in info
            or "runsc" not in settings.RUNTIME_PREFERENCE
        ):
            raise RuntimeError(
                "Observed gVisor runtime is unavailable; runc fallback is forbidden"
            )
        directory = Path(settings.TRACE_DIR)
        if not directory.is_dir() or not os.access(directory, os.R_OK):
            raise RuntimeError("Host runsc trace directory is unavailable")
        image = json.loads(await docker("image", "inspect", self.manifest.image))[0]
        self.image_digest = image["Id"]

    async def verify_network_guard(self):
        for arguments in (
            ("INPUT", "-i", "alock+", "-j", "DROP"),
            ("DOCKER-USER", "-i", "alock+", "!", "-o", "alock+", "-j", "DROP"),
        ):
            process = await asyncio.create_subprocess_exec(
                "iptables",
                "-C",
                *arguments,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise RuntimeError(
                    "Host network guard verification timed out"
                ) from None
            if process.returncode != 0:
                raise RuntimeError("Host network isolation guard is unavailable")

    async def prepare_network(self) -> tuple[str, str | None]:
        if self.manifest.network.mode == "none":
            return "none", None
        await self.verify_network_guard()
        suffix = uuid.uuid4().hex[:9]
        name = f"airlock-{suffix}"
        self.network_id = await docker(
            "network",
            "create",
            "--internal",
            "--driver",
            "bridge",
            "--label",
            f"airlock.run_id={self.run_id}",
            "--opt",
            f"com.docker.network.bridge.name=alock{suffix}",
            name,
        )
        network = json.loads(await docker("network", "inspect", self.network_id))[0]
        if network.get("Internal") is not True:
            raise RuntimeError("Honeynet must be an internal network")
        self.sink_id = await docker(
            "run",
            "-d",
            "--network",
            name,
            "--label",
            f"airlock.run_id={self.run_id}",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--user=1000:1000",
            "--sysctl",
            "net.ipv4.ip_unprivileged_port_start=0",
            "--memory=96m",
            "--pids-limit=64",
            "--tmpfs=/tmp:rw,nosuid,size=8m",
            "--log-driver=json-file",
            "--log-opt=max-size=4m",
            "--log-opt=max-file=1",
            "-e",
            f"AIRLOCK_RUN_ID={self.run_id}",
            settings.SINK_IMAGE,
        )
        for _ in range(50):
            try:
                await docker(
                    "exec",
                    self.sink_id,
                    "python3",
                    "-c",
                    "import socket;s=socket.create_connection(('127.0.0.1',80),1);s.close()",
                )
                break
            except RuntimeError:
                await asyncio.sleep(0.1)
        else:
            raise RuntimeError("Honeynet did not become ready")
        state = await inspect_container(self.sink_id)
        ip = state["NetworkSettings"]["Networks"][name]["IPAddress"]
        if not ip:
            raise RuntimeError("Honeynet has no isolated address")
        return name, ip

    async def _sink_events(self):
        self._sink_process = await asyncio.create_subprocess_exec(
            "docker",
            "logs",
            "--follow",
            self.sink_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=65536,
        )
        try:
            while line := await self._sink_process.stdout.readline():
                payload = json.loads(line)
                if (
                    payload.get("run_id") != self.run_id
                    or payload.get("source") != "host"
                    or payload.get("observer") != "sink"
                    or payload.get("kind") not in {"net", "canary"}
                ):
                    raise RuntimeError("Invalid Honeynet observation")
                if self.tail:
                    self.tail.poll()
                self.observer.make_event(
                    payload["kind"],
                    payload["detail"],
                    payload["severity"],
                    "sink",
                    ts=payload["ts"],
                )
        finally:
            if self._sink_process.returncode is None:
                self._sink_process.terminate()
            await self._sink_process.wait()

    async def _read_output(self, stream, path: Path):
        remaining = self.manifest.limits.stdout_kb * 1024
        with path.open("wb") as output:
            while chunk := await stream.read(16384):
                if remaining > 0:
                    output.write(chunk[:remaining])
                    remaining -= min(len(chunk), remaining)

    def _poll_limits(self):
        root = Path(os.getenv("CGROUP_ROOT", "/sys/fs/cgroup"))
        candidates = [
            root / "system.slice" / f"docker-{self.container_id}.scope",
            root / "docker" / self.container_id,
        ]
        for directory in candidates:
            path = directory / "pids.events"
            if path.is_file() and "pids" not in self._reported_limits:
                counters = dict(line.split() for line in path.read_text().splitlines())
                if int(counters.get("max", 0)) > 0:
                    self.observer.emit_limit(
                        "pids",
                        self.manifest.limits.pids,
                        unit="processes",
                        action="denied",
                    )
                    self._reported_limits.add("pids")

    async def _stop_container(self):
        state = await inspect_container(self.container_id)
        if state["State"].get("Running"):
            try:
                await docker("kill", self.container_id)
            except RuntimeError:
                if (await inspect_container(self.container_id))["State"].get("Running"):
                    raise

    async def _run_docker(self):
        network, sink_ip = await self.prepare_network()
        self.trace.isolated = True
        limits = self.manifest.limits
        home_mb = max(1, limits.disk_mb * 3 // 4)
        other_mb = max(1, limits.disk_mb // 8)
        self.trace.disk_limits = {
            "/home/user": home_mb,
            "/tmp": other_mb,
            "/dev/shm": other_mb,
        }
        args = [
            "create",
            "--runtime",
            settings.RUNTIME_PREFERENCE,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--user=1000:1000",
            "--init=false",
            "--label",
            f"airlock.run_id={self.run_id}",
            "--network",
            network,
            f"--cpus={limits.cpu}",
            f"--memory={limits.mem_mb}m",
            f"--memory-swap={limits.mem_mb}m",
            f"--pids-limit={limits.pids}",
            f"--shm-size={other_mb}m",
            "--log-driver=none",
            f"--tmpfs=/home/user:rw,nosuid,size={home_mb}m,mode=0700,uid=1000,gid=1000",
            f"--tmpfs=/tmp:rw,nosuid,size={other_mb}m,mode=1777",
            "--hostname",
            get_profile_hostname(self.manifest.profile),
            "--mount",
            f"type=bind,src={self.home_dir},dst=/input,readonly",
            "--workdir",
            "/home/user",
        ]
        if sink_ip:
            args.extend(["--dns", sink_ip, "--dns-search", "."])
        for key, value in {
            **generate_profile_env(self.manifest.profile),
            **self.manifest.env,
        }.items():
            args.extend(["--env", f"{key}={value}"])
        args.extend(
            [
                self.manifest.image,
                "sh",
                "-c",
                'cp -R /input/. /home/user/ && exec "$@"',
                "airlock-entrypoint",
                *self.manifest.entrypoint,
            ]
        )
        self.container_id = await docker(*args)
        self.tail = TraceTail(
            Path(settings.TRACE_DIR) / f"{self.container_id}.boot.json",
            self.trace,
            settings.MAX_TRACE_BYTES,
        )
        sink_task = asyncio.create_task(self._sink_events()) if self.sink_id else None
        process = await asyncio.create_subprocess_exec(
            "docker",
            "start",
            "--attach",
            self.container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        writers = [
            asyncio.create_task(
                self._read_output(
                    process.stdout, Path(self.artifacts_dir) / "stdout.txt"
                )
            ),
            asyncio.create_task(
                self._read_output(
                    process.stderr, Path(self.artifacts_dir) / "stderr.txt"
                )
            ),
        ]
        deadline = time.monotonic() + limits.timeout_s
        timeout_hit = False
        try:
            for _ in range(80):
                state = await inspect_container(self.container_id)
                if state["State"].get("StartedAt", "0001").startswith("0001"):
                    if process.returncode is not None:
                        raise RuntimeError("gVisor container did not start")
                    await asyncio.sleep(0.025)
                    continue
                self.observer.emit_system("container_start", self.container_id)
                break
            else:
                raise RuntimeError("gVisor startup was not confirmed")
            while process.returncode is None:
                self.tail.poll()
                self._poll_limits()
                if sink_task and sink_task.done():
                    await sink_task
                    raise RuntimeError("Honeynet capture stopped before run completion")
                if self.is_killed or time.monotonic() > deadline:
                    timeout_hit = not self.is_killed
                    await self._stop_container()
                    if timeout_hit:
                        self.observer.emit_limit(
                            "time", limits.timeout_s, unit="seconds"
                        )
                    break
                if len(self.observer.events) > settings.MAX_EVENTS:
                    raise RuntimeError("Observation event budget exceeded")
                await asyncio.sleep(0.025)
            await asyncio.wait_for(process.wait(), 10)
            await asyncio.gather(*writers)
            if sink_task:
                await docker("stop", "--time", "1", self.sink_id)
                await asyncio.wait_for(asyncio.shield(sink_task), 5)
            for _ in range(3):
                while self.tail.poll():
                    if len(self.observer.events) > settings.MAX_EVENTS:
                        raise RuntimeError("Observation event budget exceeded")
                await asyncio.sleep(0.05)
            if self.tail.partial:
                raise RuntimeError("Host trace ended with an incomplete record")
            state = await inspect_container(self.container_id)
            code = int(state["State"]["ExitCode"])
            if state["State"].get("OOMKilled") is True:
                self.observer.emit_limit("mem", limits.mem_mb, unit="MB")
            if self.trace.syscalls == 0 or (
                not timeout_hit
                and not self.is_killed
                and not state["State"].get("OOMKilled")
                and not self.trace.terminated
            ):
                raise RuntimeError("Host runtime observation did not cover completion")
            if timeout_hit:
                return "timeout", 124
            if self.is_killed:
                return "killed", code
            return ("completed" if code == 0 else "error"), code
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            for writer in writers:
                if not writer.done():
                    writer.cancel()
            await asyncio.gather(*writers, return_exceptions=True)
            if sink_task:
                sink_task.cancel()
                result = await asyncio.gather(sink_task, return_exceptions=True)
                if (
                    result
                    and isinstance(result[0], Exception)
                    and not isinstance(result[0], asyncio.CancelledError)
                ):
                    raise RuntimeError("Honeynet capture failed") from result[0]

    async def execute(self) -> dict:
        started = time.monotonic()
        outcome, code = "error", 1
        complete = False
        self.observer.emit_stage("run", "start")
        try:
            self.validate_manifest()
            await self.ensure_runtime()
            self.prepare_filesystem()
            outcome, code = await self._run_docker()
            complete = True
        except Exception as error:
            message = (
                str(error)
                if isinstance(error, (RuntimeError, ValueError, OSError))
                else f"Trusted runtime failed ({type(error).__name__})"
            )
            self.observer.emit_stage("run", "error", message=message)
        finally:
            try:
                await self.cleanup()
            except RuntimeError as error:
                outcome, code, complete = "error", 1, False
                self.observer.emit_stage("run", "error", message=str(error))
            self.observer.emit_stage("run", "end", outcome=outcome, exit_code=code)
        artifacts = Path(self.artifacts_dir)
        artifacts.mkdir(parents=True, exist_ok=True)
        for name in ("stdout.txt", "stderr.txt"):
            if not (artifacts / name).exists():
                (artifacts / name).write_bytes(b"")
        events_hash = hashlib.sha256(
            json.dumps(self.observer.events, sort_keys=True).encode()
        ).hexdigest()
        return {
            "outcome": outcome,
            "exit_code": code,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "events_sha256": events_hash,
            "stdout_sha256": hashlib.sha256(
                (artifacts / "stdout.txt").read_bytes()
            ).hexdigest(),
            "image_digest": self.image_digest,
            "observation_complete": complete,
            "artifacts": ["stdout.txt", "stderr.txt"],
        }

    async def cleanup(self):
        failures = []
        for field, command in (
            ("container_id", ("rm", "-f")),
            ("sink_id", ("rm", "-f")),
            ("network_id", ("network", "rm")),
        ):
            identity = getattr(self, field)
            if identity:
                try:
                    await docker(*command, identity)
                except RuntimeError:
                    failures.append(field)
                else:
                    if field == "container_id":
                        self.observer.emit_system("container_destroy", identity)
                    setattr(self, field, None)
        if failures:
            raise RuntimeError("Cleanup of owned runtime resources was not confirmed")

    def kill(self):
        self.is_killed = True
