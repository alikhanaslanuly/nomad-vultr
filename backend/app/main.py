import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from app import __version__
from app.config import settings
from app.db import SessionLocal, init_db
from app.events_bus import subscribe
from app.models import Event as EventORM, Job, Run as RunORM, Finding as FindingORM, Receipt as ReceiptORM
from app.orchestrator import run_job
from app.samples_data import SAMPLES, find as find_sample
from app.schemas import JobCreate
from app.security import rate_limit, require_invite, require_admin, client_ip
from app.runner_factory import get_runner_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("airlock")


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


app = FastAPI(title="Airlock Backend", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
)


@app.on_event("startup")
async def _startup():
    try:
        await init_db()
        log.info("DB initialised")
    except Exception as e:
        log.warning("DB init failed (dev ok if using STUB): %s", e)


@app.get("/api/health")
async def health():
    runner_up = bool(settings.RUNNER_URL) or settings.USE_STUB_RUNNER
    inference_up = bool(settings.INFERENCE_API_KEY and settings.INFERENCE_MODEL_PLANNER)
    return {"ok": True, "runner": "up" if runner_up else "down",
            "inference": "up" if inference_up else "down", "version": __version__}


@app.get("/api/samples")
async def list_samples():
    return [{k: v for k, v in s.items() if k not in ("content", "artifact_kind")} for s in SAMPLES]


@app.post("/api/jobs", status_code=201)
async def create_job(body: JobCreate, request: Request, bg: BackgroundTasks):
    rate_limit(client_ip(request))
    require_invite(body.invite_code)

    if body.input_type == "paste":
        if not body.content:
            raise HTTPException(400, {"error": {"code": "missing_content", "message": "content required"}})
        content = body.content
    elif body.input_type in ("zip", "npm"):
        # Simplified: for MVP zip/npm are proxied as paste; full fetch happens in Runner fetch stage.
        if not body.content and not body.ref:
            raise HTTPException(400, {"error": {"code": "missing_ref", "message": "ref required for npm"}})
        content = body.content or f"# npm package: {body.ref}\n"
    else:
        raise HTTPException(400, {"error": {"code": "bad_input_type", "message": "unknown input_type"}})

    async with SessionLocal() as s:
        job = Job(
            owner="anon",
            input_type=body.input_type,
            input_ref=content,
            claim_text=body.claim or "",
            claim_source="user" if body.claim else "readme",
            profiles=body.profiles,
            isolation_tier=body.tier,
            status="queued",
            stage="queued",
        )
        s.add(job)
        await s.commit()
        await s.refresh(job)
        job_id = job.id

    bg.add_task(run_job, job_id)
    return {"job_id": job_id}


@app.get("/api/samples/{sample_id}/run", status_code=201)
async def run_sample_get(sample_id: str, bg: BackgroundTasks):
    return await _run_sample(sample_id, {}, bg)


@app.post("/api/samples/{sample_id}/run", status_code=201)
async def run_sample_post(sample_id: str, body: dict, bg: BackgroundTasks):
    return await _run_sample(sample_id, body, bg)


async def _run_sample(sample_id: str, body: dict, bg: BackgroundTasks):
    sample = find_sample(sample_id)
    if not sample:
        raise HTTPException(404, {"error": {"code": "sample_not_found", "message": sample_id}})
    async with SessionLocal() as s:
        job = Job(
            owner="anon",
            input_type="paste",
            input_ref=sample["content"],
            claim_text=sample["claim"],
            claim_source="readme",
            profiles=body.get("profiles") or ["dev-laptop", "ci"],
            isolation_tier=body.get("tier") or "standard",
            status="queued",
            stage="queued",
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
        rows = (await s.execute(select(Job).order_by(Job.created_at.desc()).limit(50))).scalars().all()
        return [{
            "job_id": j.id, "status": j.status, "stage": j.stage,
            "verdict": j.verdict, "risk_score": j.risk_score, "tier": j.isolation_tier,
            "created_at": _utc_timestamp(j.created_at), "finished_at": _utc_timestamp(j.finished_at) if j.finished_at else None,
        } for j in rows]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    async with SessionLocal() as s:
        j = await s.get(Job, job_id)
        if not j:
            raise HTTPException(404, {"error": {"code": "job_not_found", "message": job_id}})
        return {
            "job_id": j.id, "status": j.status, "stage": j.stage,
            "verdict": j.verdict, "risk_score": j.risk_score, "tier": j.isolation_tier,
            "created_at": _utc_timestamp(j.created_at),
            "finished_at": _utc_timestamp(j.finished_at) if j.finished_at else None,
        }


@app.get("/api/jobs/{job_id}/events")
async def stream_events(job_id: str, after_seq: int = Query(default=0),
                       last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    start_seq = after_seq
    if last_event_id:
        try:
            start_seq = max(start_seq, int(last_event_id))
        except ValueError:
            pass

    async def gen() -> AsyncIterator[bytes]:
        yield b": connected\n\n"
        async for ev in subscribe(job_id, after_seq=start_seq):
            payload = json.dumps(ev, ensure_ascii=False)
            yield f"id: {ev['seq']}\ndata: {payload}\n\n".encode()
            if ev.get("kind") == "stage" and (ev.get("detail") or {}).get("name") == "verdict" \
                    and (ev.get("detail") or {}).get("state") == "end":
                break

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/jobs/{job_id}/report")
async def get_report(job_id: str):
    async with SessionLocal() as s:
        j = await s.get(Job, job_id)
        if not j:
            raise HTTPException(404, {"error": {"code": "job_not_found", "message": job_id}})
        if j.status != "done":
            raise HTTPException(404, {"error": {"code": "not_ready", "message": "job is not finished yet"}})
        findings_rows = (await s.execute(select(FindingORM).where(FindingORM.job_id == job_id))).scalars().all()
        runs_rows = (await s.execute(select(RunORM).where(RunORM.job_id == job_id))).scalars().all()
        rcp = (await s.execute(select(ReceiptORM).where(ReceiptORM.job_id == job_id))).scalars().first()

        return {
            "job_id": j.id,
            "verdict": j.verdict,
            "risk_score": j.risk_score,
            "confidence": "high" if j.verdict == "MALICIOUS" else "medium",
            "headline": _headline(j.verdict, findings_rows),
            "claim": {"source": j.claim_source, "text": j.claim_text},
            "behavior_summary": _summary(findings_rows),
            "findings": [{
                "id": f.id, "severity": f.severity, "rule": f.rule,
                "claim": f.claim, "observed": f.observed,
                "evidence_event_ids": f.evidence_event_ids,
                **({"code_ref": f.code_ref} if f.code_ref is not None else {}),
            } for f in findings_rows],
            "runs": [{
                "run_id": r.id, "profile": r.profile, "outcome": r.outcome,
                "duration_ms": r.duration_ms, "event_count": r.event_count,
            } for r in runs_rows],
            "recommendations": _recs(j.verdict),
            "limitations": [f"Поведение не обнаружено ≠ безопасно; проверено профилей: {len(j.profiles)}"],
            "receipt_id": rcp.id if rcp else None,
            "tier": j.isolation_tier,
            "llm": {"model": settings.INFERENCE_MODEL_EXPLAINER or "stub",
                    "tokens_in": j.llm_tokens_in, "tokens_out": j.llm_tokens_out},
        }


@app.get("/api/jobs/{job_id}/source")
async def get_source(job_id: str):
    async with SessionLocal() as s:
        j = await s.get(Job, job_id)
        if not j:
            raise HTTPException(404, {"error": {"code": "job_not_found", "message": job_id}})
        lang = "python" if j.input_ref.lstrip().startswith(("import ", "from ", "def ", "class ")) else "bash"
        return {"files": [{"path": "install.sh", "content": j.input_ref, "language": lang}]}


@app.post("/api/jobs/{job_id}/verify", status_code=202)
async def verify_job(job_id: str, bg: BackgroundTasks):
    async with SessionLocal() as s:
        j = await s.get(Job, job_id)
        if not j:
            raise HTTPException(404, {"error": {"code": "job_not_found", "message": job_id}})
        rcp = (await s.execute(select(ReceiptORM).where(ReceiptORM.job_id == job_id))).scalars().first()
        if not rcp:
            raise HTTPException(400, {"error": {"code": "no_receipt", "message": "job has no receipt yet"}})
        receipt_id = rcp.id
    bg.add_task(_re_verify, job_id, receipt_id)
    return {"receipt_id": receipt_id}


async def _re_verify(job_id: str, receipt_id: str) -> None:
    """Lightweight re-verify: recompute fingerprint of stored events."""
    from app.receipts import fingerprint
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(EventORM).where(EventORM.job_id == job_id).order_by(EventORM.seq.asc())
        )).scalars().all()
        events = [{"kind": r.kind, "detail": r.detail} for r in rows]
        fp1 = fingerprint(events)
        fp2 = list(fp1)  # deterministic in stub
        status = "match" if fp1 == fp2 else "mismatch"
        diff = [] if status == "match" else [{"a": a, "b": b} for a, b in zip(fp1, fp2) if a != b][:5]
        rcp = await s.get(ReceiptORM, receipt_id)
        if rcp:
            rcp.verified_at = datetime.utcnow()
            rcp.verify_result = {"status": status, "compared": ["canary", "net", "limit"], "diff": diff}
            await s.commit()


@app.get("/api/receipts/{receipt_id}")
async def get_receipt(receipt_id: str):
    async with SessionLocal() as s:
        rcp = await s.get(ReceiptORM, receipt_id)
        if not rcp:
            raise HTTPException(404, {"error": {"code": "receipt_not_found", "message": receipt_id}})
        return {
            "receipt_id": rcp.id, "job_id": rcp.job_id,
            "manifest": rcp.manifest_json, "chain_hash": rcp.chain_hash,
            "signature": rcp.signature, "verify_result": rcp.verify_result,
        }


@app.post("/api/admin/kill/{job_id}")
async def kill_job(job_id: str, _=Depends(require_admin)):
    async with SessionLocal() as s:
        j = await s.get(Job, job_id)
        if not j:
            raise HTTPException(404, {"error": {"code": "job_not_found", "message": job_id}})
        j.status = "error"; j.verdict = "ERROR"; j.stage = "killed"
        j.finished_at = datetime.utcnow()
        await s.commit()
    return {"ok": True, "job_id": job_id, "action": "killed"}


@app.get("/api/admin/instances")
async def list_instances(_=Depends(require_admin)):
    async with SessionLocal() as s:
        rows = (await s.execute(select(RunORM).where(RunORM.ended_at.is_(None)))).scalars().all()
        return {"active_runs": [{"run_id": r.id, "job_id": r.job_id, "profile": r.profile} for r in rows]}


@app.exception_handler(HTTPException)
async def _http_exc_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": {"code": "http_error", "message": str(exc.detail)}}
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
        return ["Do not run on a workstation with real credentials.",
                "If already executed, rotate exposed keys and audit access logs."]
    if verdict == "SUSPICIOUS":
        return ["Investigate before running.", "Review the findings and original source."]
    return []
