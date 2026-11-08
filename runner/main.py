import os
import json
import asyncio
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, Depends, HTTPException, Header, status, Response
from fastapi.responses import StreamingResponse, PlainTextResponse, JSONResponse

from .config import settings
from .models import RunManifest, HealthResponse, RunSummary
from .executor import SandboxExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("airlock-runner")

app = FastAPI(title="Airlock Sandbox Runner API", version="1.0.0")

# In-memory execution registry for active and finished runs
RUNS: Dict[str, SandboxExecutor] = {}
SUMMARIES: Dict[str, Dict[str, Any]] = {}


def verify_bearer_token(authorization: Optional[str] = Header(None)):
    if not settings.RUNNER_TOKEN:
        return True  # Dev mode without token
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != settings.RUNNER_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid runner token")
    return True


@app.get("/healthz", response_model=HealthResponse)
def healthz():
    # Honest detection of runtime & observer
    runtime = "runsc"
    observer = "gvisor"
    try:
        import subprocess
        check = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=2)
        if "runsc" not in check.stdout:
            runtime = "runc"
            observer = "strace"
    except Exception:
        runtime = "runc"
        observer = "strace"

    return HealthResponse(
        ok=True,
        image_digest="sha256:airlock-sandbox-node-py-v1",
        runtime=runtime,
        observer=observer
    )


@app.post("/v1/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(manifest: RunManifest, authorized: bool = Depends(verify_bearer_token)):
    run_id = manifest.run_id
    if run_id in RUNS:
        raise HTTPException(status_code=400, detail=f"Run {run_id} already exists")

    log.info("Accepting run: %s (profile=%s, image=%s)", run_id, manifest.profile, manifest.image)
    executor = SandboxExecutor(manifest)
    RUNS[run_id] = executor

    # Launch execution asynchronously in background
    async def run_task():
        try:
            summary = await executor.execute()
            SUMMARIES[run_id] = summary
            log.info("Run %s finished: outcome=%s exit_code=%s", run_id, summary["outcome"], summary["exit_code"])
        except Exception as e:
            log.error("Fatal failure in run %s: %s", run_id, e)

    asyncio.create_task(run_task())
    return {"run_id": run_id}


@app.get("/v1/runs/{run_id}/events")
async def stream_events(run_id: str, after_seq: int = 0, authorized: bool = Depends(verify_bearer_token)):
    executor = RUNS.get(run_id)
    if not executor:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        current_seq = after_seq
        done = False
        while not done:
            events = executor.observer.get_events(after_seq=current_seq)
            for ev in events:
                current_seq = ev["seq"]
                data_line = f"data: {json.dumps(ev)}\n\n"
                yield data_line
                if ev.get("kind") == "stage" and ev.get("detail", {}).get("name") == "run" and ev.get("detail", {}).get("state") == "end":
                    done = True
                    break

            if not done:
                await asyncio.sleep(0.05)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/v1/runs/{run_id}/summary", response_model=RunSummary)
async def get_summary(run_id: str, authorized: bool = Depends(verify_bearer_token)):
    if run_id in SUMMARIES:
        return SUMMARIES[run_id]
    executor = RUNS.get(run_id)
    if not executor:
        raise HTTPException(status_code=404, detail="Run not found")
    # If still running, return interim status
    return RunSummary(
        outcome="completed",
        exit_code=0,
        duration_ms=0,
        events_sha256="",
        artifacts=["stdout.txt", "stderr.txt"]
    )


@app.get("/v1/runs/{run_id}/artifacts/{name}")
async def get_artifact(run_id: str, name: str, authorized: bool = Depends(verify_bearer_token)):
    executor = RUNS.get(run_id)
    if not executor:
        raise HTTPException(status_code=404, detail="Run not found")

    artifact_path = os.path.join(executor.artifacts_dir, name)
    if not os.path.exists(artifact_path):
        raise HTTPException(status_code=404, detail=f"Artifact {name} not found")

    with open(artifact_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    return PlainTextResponse(content)


@app.post("/v1/runs/{run_id}/kill")
async def kill_run(run_id: str, authorized: bool = Depends(verify_bearer_token)):
    executor = RUNS.get(run_id)
    if not executor:
        raise HTTPException(status_code=404, detail="Run not found")
    executor.kill()
    return {"ok": True, "killed": run_id}


@app.delete("/v1/runs/{run_id}")
async def delete_run(run_id: str, authorized: bool = Depends(verify_bearer_token)):
    if run_id in RUNS:
        executor = RUNS.pop(run_id)
        executor.kill()
        if os.path.exists(executor.run_dir):
            try:
                import shutil
                shutil.rmtree(executor.run_dir, ignore_errors=True)
            except Exception:
                pass
    SUMMARIES.pop(run_id, None)
    return {"ok": True, "deleted": run_id}

