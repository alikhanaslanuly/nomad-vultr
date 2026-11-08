import json
from typing import AsyncIterator

import httpx

from app.config import settings


class RunnerClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._headers = {"Authorization": f"Bearer {token}"}

    async def healthz(self) -> dict:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.base_url}/healthz", headers=self._headers)
            r.raise_for_status()
            return r.json()

    async def start_run(self, manifest: dict) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.base_url}/v1/runs", json=manifest, headers=self._headers)
            r.raise_for_status()
            return r.json()["run_id"]

    async def stream_events(self, run_id: str, after_seq: int = 0, timeout_s: int = 120) -> AsyncIterator[dict]:
        url = f"{self.base_url}/v1/runs/{run_id}/events"
        params = {"after_seq": after_seq}
        async with httpx.AsyncClient(timeout=timeout_s) as c:
            async with c.stream("GET", url, params=params, headers=self._headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        continue

    async def summary(self, run_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.base_url}/v1/runs/{run_id}/summary", headers=self._headers)
            r.raise_for_status()
            return r.json()

    async def kill(self, run_id: str) -> None:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{self.base_url}/v1/runs/{run_id}/kill", headers=self._headers)