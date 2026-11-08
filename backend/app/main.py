import json
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from app import __version__
from app.config import settings
from app.db import SessionLocal, init_db
from app.events_bus import subscribe
from app.models import Job, Run as RunORM, Finding as FindingORM, Receipt as ReceiptORM
from app.orchestrator import run_job, stop_job
from app.samples_data import SAMPLES, find as find_sample
from app.schemas import JobCreate, SampleRun
from app.artifacts import ArtifactError, prepare_artifact
from app.security import rate_limit, require_invite, require_admin, client_ip

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("airlock")


@asynccontextmanager
async def lifespan(application: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Airlock Backend", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


@app.get("/api/health")
async def health():
    runner_up = False
    observer_verified = False
    from app.llm import inference_health

    inference_up = await inference_health()
    if settings.RUNNER_URL and not settings.USE_STUB_RUNNER:
        from app.runner_client import RunnerClient

        try:
            state = await RunnerClient(
                settings.RUNNER_URL, settings.RUNNER_TOKEN
            ).healthz()
            runner_up = (
                state.get("ok") is True and state.get("observer_verified") is True
            )
            observer_verified = runner_up
        except Exception:
            runner_up = False
    from fleet import get_manager

    return {
        "ok": True,
        "runner": "up" if runner_up else "down",
        "inference": "up" if inference_up else "down",
        "mode": "mock" if settings.USE_STUB_RUNNER else "live",
        "observer_verified": observer_verified,
        "capabilities": {
            "paste": not settings.USE_STUB_RUNNER,
            "zip": not settings.USE_STUB_RUNNER,
            "npm": False,
            "burn": get_manager().configured
            and bool(settings.invite_codes)
            and not settings.USE_STUB_RUNNER,
        },
        "version": __version__,
    }


@app.get("/api/samples")
async def list_samples():
    return [
        {k: v for k, v in s.items() if k not in ("content", "artifact_kind")}
        for s in SAMPLES
    ]


@app.post("/api/jobs", status_code=201)
async def create_job(body: JobCreate, request: Request, bg: BackgroundTasks):
    rate_limit(client_ip(request))
    require_invite(body.invite_code)

    try:
        prepare_artifact(body.input_type, body.content or "", body.filename, body.ref)
    except ArtifactError as error:
        raise HTTPException(
            error.status, {"error": {"code": error.code, "message": str(error)}}
        ) from None
    if settings.USE_STUB_RUNNER:
        raise HTTPException(
            503,
            {
                "error": {
                    "code": "mock_samples_only",
                    "message": "Simulated backend accepts only named team samples; arbitrary uploads require a real runner",
                }
            },
        )
    content = body.content or ""
    if body.tier == "burn":
        if not settings.invite_codes:
            raise HTTPException(
                503,
                {
                    "error": {
                        "code": "burn_access_unconfigured",
                        "message": "Burn VM requires configured invite protection",
                    }
                },
            )
        from fleet import get_manager

        if not get_manager().configured:
            raise HTTPException(
                503,
                {
                    "error": {
                        "code": "burn_unavailable",
                        "message": "Burn VM is not configured",
                    }
                },
            )

    async with SessionLocal() as s:
        job = Job(
            owner="anon",
            input_type=body.input_type,
            filename=body.filename,
            execution_mode="live",
            input_ref=content,
            claim_text=body.claim or "",
            claim_source="user" if body.claim else "readme",
            profiles=body.profiles,
            isolation_tier=body.tier,
            status="queued",
            stage="fetch",
        )
        s.add(job)
        await s.commit()
        await s.refresh(job)
        job_id = job.id

    bg.add_task(run_job, job_id)
    return {"job_id": job_id}


@app.get("/api/samples/{sample_id}/run", status_code=201)
async def run_sample_get(sample_id: str, request: Request, bg: BackgroundTasks):
    rate_limit(client_ip(request))
    return await _run_sample(sample_id, SampleRun(), bg)


@app.post("/api/samples/{sample_id}/run", status_code=201)
async def run_sample_post(
    sample_id: str, body: SampleRun, request: Request, bg: BackgroundTasks
):
    rate_limit(client_ip(request))
    return await _run_sample(sample_id, body, bg)


async def _run_sample(sample_id: str, options: SampleRun, bg: BackgroundTasks):
    if options.tier == "burn":
        if not settings.invite_codes:
            raise HTTPException(
                503,
                {
                    "error": {
                        "code": "burn_access_unconfigured",
                        "message": "Burn VM requires invite protection",
                    }
                },
            )
        require_invite(options.invite_code)
        from fleet import get_manager

        if settings.USE_STUB_RUNNER or not get_manager().configured:
            raise HTTPException(
                503,
                {
                    "error": {
                        "code": "burn_unavailable",
                        "message": "Real Burn VM is not configured",
                    }
                },
            )
    sample = find_sample(sample_id)
    if not sample:
        raise HTTPException(
            404, {"error": {"code": "sample_not_found", "message": sample_id}}
        )
    async with SessionLocal() as s:
        job = Job(
            owner="anon",
            input_type="paste",
            filename=sample.get("filename", "install.sh"),
            execution_mode="mock" if settings.USE_STUB_RUNNER else "live",
            sample_id=sample_id,
            input_ref=sample["content"],
            claim_text=sample["claim"],
            claim_source="readme",
            profiles=options.profiles,
            isolation_tier=options.tier,
            status="queued",
            stage="fetch",
        )
        s.add(job)
        await s.commit()
        await s.refresh(job)
        job_id = job.id
    bg.add_task(run_job, job_id)
    return {"job_id": job_id}


@app.get("/api/jobs")
async def list_jobs():
    async with SessionLocal() as s:
        rows = (
            (await s.execute(select(Job).order_by(Job.created_at.desc()).limit(50)))
            .scalars()
            .all()
        )
        return [
            {
                "job_id": j.id,
                "status": j.status,
                "stage": "fetch" if j.stage == "queued" else j.stage,
                "verdict": j.verdict,
                "risk_score": j.risk_score,
                "tier": j.isolation_tier,
                "mode": j.execution_mode,
                "created_at": j.created_at.replace(tzinfo=timezone.utc).isoformat(),
                "finished_at": j.finished_at.replace(tzinfo=timezone.utc).isoformat()
                if j.finished_at
                else None,
            }
            for j in rows
        ]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    async with SessionLocal() as s:
        j = await s.get(Job, job_id)
        if not j:
            raise HTTPException(
                404, {"error": {"code": "job_not_found", "message": job_id}}
            )
        return {
            "job_id": j.id,
            "status": j.status,
            "stage": "fetch" if j.stage == "queued" else j.stage,
            "verdict": j.verdict,
            "risk_score": j.risk_score,
            "tier": j.isolation_tier,
            "mode": j.execution_mode,
            "created_at": j.created_at.replace(tzinfo=timezone.utc).isoformat(),
            "finished_at": j.finished_at.replace(tzinfo=timezone.utc).isoformat()
            if j.finished_at
            else None,
        }


@app.get("/api/jobs/{job_id}/events")
async def stream_events(
    job_id: str,
    after_seq: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    async with SessionLocal() as session:
        if not await session.get(Job, job_id):
            raise HTTPException(
                404, {"error": {"code": "job_not_found", "message": job_id}}
            )
    start_seq = after_seq
    if last_event_id:
        try:
            start_seq = max(start_seq, int(last_event_id))
        except ValueError:
            pass

    async def gen() -> AsyncIterator[bytes]:
        yield b": connected\n\n"
        async for ev in subscribe(job_id, after_seq=start_seq):
            if ev is None:
                yield b": heartbeat\n\n"
                continue
            payload = json.dumps(ev, ensure_ascii=False)
            yield f"id: {ev['seq']}\ndata: {payload}\n\n".encode()
            if (
                ev.get("kind") == "stage"
                and (ev.get("detail") or {}).get("name") == "verdict"
                and (ev.get("detail") or {}).get("state") == "end"
            ):
                break

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs/{job_id}/report")
async def get_report(job_id: str):
    async with SessionLocal() as s:
        j = await s.get(Job, job_id)
        if not j:
            raise HTTPException(
                404, {"error": {"code": "job_not_found", "message": job_id}}
            )
        if j.status not in {"done", "error"}:
            raise HTTPException(
                404,
                {"error": {"code": "not_ready", "message": "job is not finished yet"}},
            )
        findings_rows = (
            (await s.execute(select(FindingORM).where(FindingORM.job_id == job_id)))
            .scalars()
            .all()
        )
        runs_rows = (
            (await s.execute(select(RunORM).where(RunORM.job_id == job_id)))
            .scalars()
            .all()
        )
        rcp = (
            (await s.execute(select(ReceiptORM).where(ReceiptORM.job_id == job_id)))
            .scalars()
            .first()
        )

        return {
            "job_id": j.id,
            "verdict": j.verdict,
            "risk_score": j.risk_score,
            "confidence": "high" if j.verdict == "MALICIOUS" else "medium",
            "headline": _headline(j.verdict, findings_rows),
            "claim": {"source": j.claim_source, "text": j.claim_text},
            "behavior_summary": _summary(findings_rows),
            "findings": [
                {
                    "id": f.id,
                    "severity": f.severity,
                    "rule": f.rule,
                    "claim": f.claim,
                    "observed": f.observed,
                    "evidence_event_ids": f.evidence_event_ids,
                    **({"code_ref": f.code_ref} if f.code_ref else {}),
                }
                for f in findings_rows
            ],
            "runs": [
                {
                    "run_id": r.id,
                    "profile": r.profile,
                    "outcome": r.outcome,
                    "duration_ms": r.duration_ms,
                    "event_count": r.event_count,
                }
                for r in runs_rows
                if r.ended_at is not None
            ],
            "recommendations": _recs(j.verdict),
            "limitations": [
                f"No issue observed does not mean proven safe; requested profiles: {len(j.profiles)}.",
                "Observation covers traced read/exec/connect calls; mmap, encrypted HTTPS bodies and untraced mechanisms are not fully covered. HTTP bodies are capped at 64 KiB; larger/malformed requests are rejected and marked as truncated.",
                "Honeynet redirects DNS to a local HTTP sink and never forwards payloads upstream. Direct IP attempts are separately observed; internal-network and host-firewall policies are required.",
                "Dependency downloads are disabled; submitted package lifecycle hooks run offline. Binary ZIP files are omitted from the text source viewer.",
            ]
            + (
                ["MOCK/STUB runner: synthetic events, not a real sandbox observation."]
                if j.execution_mode == "mock"
                else [
                    "Legacy job: execution mode was not recorded; runtime provenance is unverified."
                ]
                if j.execution_mode != "live"
                else []
            ),
            "receipt_id": rcp.id if rcp else None,
            "tier": j.isolation_tier,
            "mode": j.execution_mode,
            **(
                {
                    "llm": {
                        "model": j.llm_model,
                        "tokens_in": j.llm_tokens_in,
                        "tokens_out": j.llm_tokens_out,
                    }
                }
                if j.llm_model
                else {}
            ),
        }


@app.get("/api/jobs/{job_id}/source")
async def get_source(job_id: str):
    async with SessionLocal() as s:
        j = await s.get(Job, job_id)
        if not j:
            raise HTTPException(
                404, {"error": {"code": "job_not_found", "message": job_id}}
            )
        artifact = prepare_artifact(j.input_type, j.input_ref, j.filename)
        return {"files": artifact.source_files()}


@app.post("/api/jobs/{job_id}/verify", status_code=202)
async def verify_job(job_id: str, bg: BackgroundTasks):
    raise HTTPException(
        501,
        {
            "error": {
                "code": "reverify_unavailable",
                "message": "Independent re-execution verification is unavailable; the supplied receipt is an integrity artifact only",
            }
        },
    )


@app.get("/api/receipts/{receipt_id}")
async def get_receipt(receipt_id: str):
    async with SessionLocal() as s:
        rcp = await s.get(ReceiptORM, receipt_id)
        if not rcp:
            raise HTTPException(
                404, {"error": {"code": "receipt_not_found", "message": receipt_id}}
            )
        return {
            "receipt_id": rcp.id,
            "job_id": rcp.job_id,
            "manifest": rcp.manifest_json,
            "chain_hash": rcp.chain_hash,
            "signature": rcp.signature,
            "verify_result": rcp.verify_result,
        }


@app.post("/api/admin/kill/{job_id}")
async def kill_job(job_id: str, _=Depends(require_admin)):
    async with SessionLocal() as s:
        j = await s.get(Job, job_id)
        if not j:
            raise HTTPException(
                404, {"error": {"code": "job_not_found", "message": job_id}}
            )
        await stop_job(job_id)
        j.status = "error"
        j.verdict = "ERROR"
        j.stage = "verdict"
        j.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await s.commit()
    return {"ok": True, "job_id": job_id, "action": "killed"}


@app.get("/api/admin/instances")
async def list_instances(_=Depends(require_admin)):
    async with SessionLocal() as s:
        rows = (
            (await s.execute(select(RunORM).where(RunORM.ended_at.is_(None))))
            .scalars()
            .all()
        )
        return {
            "active_runs": [
                {"run_id": r.id, "job_id": r.job_id, "profile": r.profile} for r in rows
            ]
        }


@app.exception_handler(HTTPException)
async def _http_exc_handler(request: Request, exc: HTTPException):
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"error": {"code": "http_error", "message": str(exc.detail)}}
    )
    return JSONResponse(status_code=exc.status_code, content=detail)


def _headline(verdict: str | None, findings) -> str:
    if verdict == "MALICIOUS":
        return "Script reads canary credentials and attempts exfiltration"
    if verdict == "SUSPICIOUS":
        return "Suspicious behaviour observed — see findings"
    if verdict == "SAFE_OBSERVED":
        return "No risky behaviour observed in tested profiles"
    return "Job did not complete"


def _summary(findings) -> str:
    if not findings:
        return "No findings. This does not prove the artifact is safe."
    return "; ".join(f.observed for f in findings[:3])


def _recs(verdict: str | None) -> list[str]:
    if verdict == "MALICIOUS":
        return [
            "Do not run on a workstation with real credentials.",
            "If already executed, rotate exposed keys and audit access logs.",
        ]
    if verdict == "SUSPICIOUS":
        return [
            "Investigate before running.",
            "Review the findings and original source.",
        ]
    return []
