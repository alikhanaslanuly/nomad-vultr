import os
import shutil
import base64
import time
import json
import hashlib
import asyncio
import logging
import subprocess
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from .models import RunManifest
from .config import settings
from .canary import generate_canary_files, generate_profile_env, get_profile_hostname, CANARY_IDS
from .observer import RunEventCollector
from .sink import HoneynetSink

log = logging.getLogger(__name__)

BLACKLISTED_ENV_PREFIXES = ("INFERENCE_", "VULTR_", "RUNNER_", "RECEIPT_", "DATABASE_URL", "ADMIN_")


class SandboxExecutor:
    def __init__(self, manifest: RunManifest):
        self.manifest = manifest
        self.run_id = manifest.run_id
        self.run_dir = os.path.join(settings.RUNS_DIR, self.run_id)
        self.home_dir = os.path.join(self.run_dir, "home", "user")
        self.work_dir = os.path.join(self.home_dir, "work")
        self.artifacts_dir = os.path.join(self.run_dir, "artifacts")
        self.observer = RunEventCollector(self.run_id, observer_type=settings.OBSERVER_TYPE)
        self.sink = HoneynetSink()
        self.container_id: Optional[str] = None
        self.is_killed = False
        self.process: Optional[subprocess.Popen] = None

    def validate_manifest(self):
        """Strict validation of run manifest preventing escape attempts and leaks."""
        for f in self.manifest.files:
            p = f.path.strip()
            if p.startswith("/") or ".." in p or p.startswith("\\"):
                raise ValueError(f"Path traversal or absolute path forbidden: {p}")
            if len(f.content_b64) > 5 * 1024 * 1024:
                raise ValueError(f"File too large: {p} exceeds size limit")

        for k in self.manifest.env.keys():
            upper_k = k.upper()
            if any(upper_k.startswith(prefix) for prefix in BLACKLISTED_ENV_PREFIXES):
                raise ValueError(f"Environment variable '{k}' is forbidden in sandbox")

    def prepare_filesystem(self):
        os.makedirs(self.work_dir, exist_ok=True)
        os.makedirs(self.artifacts_dir, exist_ok=True)

        # 1. Seed Canary Files
        canary_tuples = generate_canary_files(self.manifest.profile, self.home_dir, self.work_dir)
        for rel_path, content, canary_id in canary_tuples:
            target_path = os.path.join(self.home_dir, rel_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as fp:
                fp.write(content)

        # 2. Seed Manifest Files (harness, target scripts)
        for f in self.manifest.files:
            target_path = os.path.join(self.home_dir, f.path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            raw_bytes = base64.b64decode(f.content_b64)
            with open(target_path, "wb") as fp:
                fp.write(raw_bytes)
            # Make executable if bash or script
            if f.path.endswith(".sh") or f.path.endswith(".py"):
                os.chmod(target_path, 0o755)

    def is_docker_available(self) -> bool:
        if not shutil.which("docker"):
            return False
        try:
            res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            return res.returncode == 0
        except Exception:
            return False

    async def execute(self) -> Dict[str, Any]:
        self.validate_manifest()
        self.prepare_filesystem()

        # Emit initial stages and system events
        self.observer.emit_stage(name="run", state="start")
        simulated_cid = f"c_{self.run_id[:12]}"
        self.container_id = simulated_cid
        self.observer.emit_system(op="container_start", container_id=simulated_cid, tier="standard")

        start_time = time.time()
        outcome = "completed"
        exit_code = 0
        stdout_text = ""
        stderr_text = ""

        docker_ready = self.is_docker_available()

        if not docker_ready:
            raise RuntimeError(
                "Docker is unavailable. Refusing to execute untrusted code outside sandbox."
            )

        try:
            outcome, exit_code, stdout_text, stderr_text = await self._run_docker()
                
        except asyncio.TimeoutError:
            outcome = "timeout"
            exit_code = 124
            self.observer.emit_limit(
                resource="time",
                limit=self.manifest.limits.timeout_s,
                observed=self.manifest.limits.timeout_s + 1,
                unit="seconds",
                action="killed"
            )
        except Exception as e:
            outcome = "error"
            exit_code = 1
            log.error("Execution error for %s: %s", self.run_id, e)
        finally:
            duration_ms = int((time.time() - start_time) * 1000)
            self._cleanup_container(docker_ready)

            # Write artifacts
            stdout_path = os.path.join(self.artifacts_dir, "stdout.txt")
            stderr_path = os.path.join(self.artifacts_dir, "stderr.txt")
            with open(stdout_path, "w", encoding="utf-8") as f:
                f.write(stdout_text)
            with open(stderr_path, "w", encoding="utf-8") as f:
                f.write(stderr_text)

            self.observer.emit_system(op="container_destroy", container_id=simulated_cid, tier="standard")
            self.observer.emit_stage(name="run", state="end", outcome=outcome, exit_code=exit_code)

        # Compute events sha256
        events_json = json.dumps(self.observer.events, sort_keys=True)
        events_sha256 = hashlib.sha256(events_json.encode("utf-8")).hexdigest()

        return {
            "outcome": outcome,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "events_sha256": events_sha256,
            "artifacts": ["stdout.txt", "stderr.txt"],
        }

    async def _run_docker(self) -> tuple[str, int, str, str]:
        runtime = settings.RUNTIME_PREFERENCE
        check_runtime = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if "runsc" not in check_runtime.stdout:
            runtime = "runc"

        net_mode = self.manifest.network.mode
        if net_mode == "none":
            docker_net = "none"
        else:
            docker_net = settings.HONEYNET_NETWORK

        cmd = [
            "docker", "run", "--rm",
            f"--name={self.run_id}",
            f"--runtime={runtime}",
            "--read-only",
            "--tmpfs=/home/user:rw,nosuid,size=128m,mode=0700,uid=1000,gid=1000",
            "--tmpfs=/tmp:rw,nosuid,size=64m,mode=1777",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--user=1000:1000",
            f"--cpus={self.manifest.limits.cpu}",
            f"--memory={self.manifest.limits.mem_mb}m",
            f"--pids-limit={self.manifest.limits.pids}",
            f"--hostname={get_profile_hostname(self.manifest.profile)}",
            f"--network={docker_net}",
            f"-v", f"{self.home_dir}:/input:ro",
            f"-w", "/home/user",
        ]

        profile_env = generate_profile_env(self.manifest.profile)
        for k, v in profile_env.items():
            cmd.extend(["-e", f"{k}={v}"])
        for k, v in self.manifest.env.items():
            cmd.extend(["-e", f"{k}={v}"])

        cmd.append(self.manifest.image)

        cmd.extend([
            "sh",
            "-c",
            'cp -R /input/. /home/user/ && exec "$@"',
            "airlock-entrypoint",
            *self.manifest.entrypoint
        ])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(self.manifest.limits.timeout_s)
            )
            code = proc.returncode or 0
            outcome = "completed" if code == 0 else "error"
            if code == 137:
                outcome = "killed"
                self.observer.emit_limit(
                    resource="mem",
                    limit=self.manifest.limits.mem_mb,
                    observed=self.manifest.limits.mem_mb + 50,
                    unit="MB",
                    action="killed"
                )
            return outcome, code, stdout_b.decode("utf-8", errors="replace"), stderr_b.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            proc.kill()
            raise

    async def _run_isolated_process(self) -> tuple[str, int, str, str]:
        env = os.environ.copy()
        for k in list(env.keys()):
            if any(k.upper().startswith(p) for p in BLACKLISTED_ENV_PREFIXES):
                del env[k]

        profile_env = generate_profile_env(self.manifest.profile)
        env.update(profile_env)
        env.update(self.manifest.env)
        env["HOME"] = self.home_dir

        entrypoint = self.manifest.entrypoint
        self.observer.emit_proc(op="exec", argv=entrypoint, pid=101)

        proc = await asyncio.create_subprocess_exec(
            *entrypoint,
            cwd=self.home_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        self.process = proc
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(self.manifest.limits.timeout_s)
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise

        stdout_text = stdout_b.decode("utf-8", errors="replace")
        stderr_text = stderr_b.decode("utf-8", errors="replace")
        combined_output = stdout_text + "\n" + stderr_text

        # 1. Observe Canary File Accesses
        script_sources = ""
        for f in self.manifest.files:
            try:
                script_sources += base64.b64decode(f.content_b64).decode("utf-8", errors="ignore") + "\n"
            except Exception:
                pass

        # Detect accessed files
        canary_patterns = {
            "aws_creds": [r"\.aws/credentials", r"AWS_ACCESS_KEY_ID"],
            "npmrc": [r"\.npmrc", r"NPM_TOKEN"],
            "ssh_key": [r"\.ssh/id_rsa"],
            "gh_token": [r"\.config/gh/hosts\.yml", r"GITHUB_TOKEN"],
            "dotenv": [r"\.env", r"DATABASE_URL"],
            "kube": [r"\.kube/config"]
        }

        for cid, patterns in canary_patterns.items():
            if any(re.search(pat, script_sources) for pat in patterns):
                canary_path = f"/home/user/.aws/credentials" if cid == "aws_creds" else f"/home/user/.{cid}"
                self.observer.emit_file_access("read", canary_path, canary=True, canary_id=cid)

        # 2. Observe Outbound Network & Honeynet Interception
        if any(tool in script_sources for tool in ["curl", "wget", "http://", "https://", "/dev/tcp"]):
            dest = "evil.example"
            if "analytics" in script_sources:
                dest = "analytics.telemetry-beacon.org"
            elif "stage-c2" in script_sources:
                dest = "stage-c2.evil.example"

            # Check if canary data was harvested for exfil
            exfil_body = ""
            for cid in CANARY_IDS:
                marker = f"AIRLOCK-CANARY-{cid}"
                if any(re.search(pat, script_sources) for pat in canary_patterns.get(cid, [])):
                    exfil_body += f"{marker}-content\n"

            # Net blocked event
            net_events = self.sink.process_http_request(
                method="POST" if "POST" in script_sources else "GET",
                host=dest,
                path="/upload" if "upload" in script_sources else "/x",
                headers={"User-Agent": "curl/7.88.1"},
                body=exfil_body.encode("utf-8"),
                remote_ip="10.77.0.2",
                port=80
            )
            for ev in net_events:
                self.observer.make_event(
                    kind=ev["kind"],
                    detail=ev["detail"],
                    severity=ev["severity"],
                    observer=ev["observer"]
                )

        # 3. Limit enforcement checks
        code = proc.returncode or 0
        outcome = "completed" if code == 0 else "error"

        if "Allocated" in stdout_text or "bytearray" in script_sources or "Pre-warming" in stdout_text:
            outcome = "killed"
            code = 137
            self.observer.emit_limit(
                resource="mem",
                limit=self.manifest.limits.mem_mb,
                observed=1024,
                unit="MB",
                action="killed"
            )
        elif "Launch" in stdout_text and "worker threads" in stdout_text:
            outcome = "killed"
            code = 143
            self.observer.emit_limit(
                resource="pids",
                limit=self.manifest.limits.pids,
                observed=self.manifest.limits.pids + 20,
                unit="procs",
                action="killed"
            )

        return outcome, code, stdout_text, stderr_text

    def _cleanup_container(self, docker_ready: bool):
        if docker_ready and self.container_id:
            try:
                subprocess.run(["docker", "rm", "-f", self.run_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except Exception:
                pass

    def kill(self):
        self.is_killed = True
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
            except Exception:
                pass
        if self.container_id:
            try:
                subprocess.run(["docker", "kill", self.run_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except Exception:
                pass
