import asyncio
import json
import os
from pathlib import Path
from typing import AsyncIterator

MOCK_DIR = Path(os.getenv("MOCK_DIR", "contracts/mock"))


class RunnerStub:
    def __init__(self, base_url: str = "stub://local"):
        self.base_url = base_url
        self._runs: dict[str, dict] = {}

    async def healthz(self) -> dict:
        return {"ok": True, "runtime": "stub", "observer": "stub", "image_digest": "stub"}

    async def start_run(self, manifest: dict) -> str:
        run_id = manifest["run_id"]
        sample_id = manifest.get("env", {}).get("AIRLOCK_SAMPLE") or self._guess_from_files(manifest)
        self._runs[run_id] = {"sample_id": sample_id, "manifest": manifest}
        return run_id

    def _guess_from_files(self, manifest: dict) -> str:
        for f in manifest.get("files", []):
            if "install.sh" in f.get("path", ""):
                return "evil-installer"
        return "benign-csv-tool"

    async def stream_events(self, run_id: str, after_seq: int = 0, timeout_s: int = 60) -> AsyncIterator[dict]:
        info = self._runs.get(run_id)
        if not info:
            return
        path = MOCK_DIR / f"events_{info['sample_id']}.ndjson"
        if not path.exists():
            return
        yield {
            "id": f"evt_stub_{run_id}", "job_id": None, "run_id": run_id,
            "seq": 0, "ts": "2026-11-07T09:00:00.000Z",
            "kind": "system", "severity": "info", "observer": "runner",
            "source": "host",
            "detail": {"op": "runner_ready", "mode": "STUB_MODE", "sample": info["sample_id"]},
        }
        seq = 0
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            delay = ev.pop("delay_ms", 0) / 1000.0
            await asyncio.sleep(min(delay, 0.3))
            seq += 1
            ev["seq"] = seq
            ev["run_id"] = run_id
            yield ev

    async def summary(self, run_id: str) -> dict:
        return {"outcome": "completed", "exit_code": 0, "duration_ms": 1500, "events_sha256": "", "artifacts": []}

    async def kill(self, run_id: str) -> None:
        return