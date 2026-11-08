import asyncio
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Job, Run as RunORM, Finding as FindingORM
from app.events_bus import publish, next_seq
from app.planner import plan as run_planner
from app.explainer import explain as run_explainer
from app.verdict import evaluate
from app.receipts import create_receipt
from app.runner_factory import get_runner_for, release_runner
from app.samples_data import SAMPLES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _emit_stage(job_id: str, name: str, state: str, message: str = "", run_id: str | None = None):
    seq = await next_seq(job_id)
    await publish(job_id, {
        "id": f"evt_{job_id}_{seq}",
        "job_id": job_id, "run_id": run_id, "seq": seq, "ts": _now(),
        "kind": "stage", "severity": "info",
        "observer": "orchestrator", "source": "orchestrator",
        "detail": {"name": name, "state": state, "run_id": run_id, "message": message},
    })


async def _emit_agent(job_id: str, role: str, step_no: int, summary: str, tin: int, tout: int):
    seq = await next_seq(job_id)
    await publish(job_id, {
        "id": f"evt_{job_id}_{seq}",
        "job_id": job_id, "run_id": None, "seq": seq, "ts": _now(),
        "kind": "agent", "severity": "info",
        "observer": "llm", "source": "orchestrator",
        "detail": {"role": role, "step_no": step_no, "summary": summary,
                   "tokens_in": tin, "tokens_out": tout},
    })


def _artifact_facts(content: str, filename: str) -> dict:
    """Static facts only. Never passes raw user text as instructions."""
    return {
        "filename": filename,
        "size_bytes": len(content.encode()),
        "line_count": content.count("\n") + 1,
        "first_200_chars": content[:200],
        "contains_urls": [w for w in content.split() if w.startswith(("http://", "https://"))][:10],
        "mentions": {
            "credentials": "credentials" in content or "~/.aws" in content,
            "ssh": "ssh" in content or ".ssh" in content,
            "npm": "npm" in content,
            "curl_or_wget": "curl" in content or "wget" in content,
        },
    }


def _kind_from_filename(filename: str) -> str:
    if filename.endswith((".py",)): return "python"
    if filename.endswith(("package.json",)): return "npm"
    return "bash"


async def run_job(job_id: str) -> None:
    try:
        await _run_job_inner(job_id)
    except Exception as e:
        async with SessionLocal() as s:
            job = await s.get(Job, job_id)
            if job:
                job.status = "error"
                job.verdict = "ERROR"
                job.stage = "error"
                job.finished_at = datetime.utcnow()
                await s.commit()
        await _emit_stage(job_id, "verdict", "error", message=f"{type(e).__name__}: {e}")


async def _run_job_inner(job_id: str) -> None:
    # ---- load job ----
    async with SessionLocal() as s:
        job = await s.get(Job, job_id)
        if not job:
            return
        content = job.input_ref
        filename = "install.sh"
        claim_text = job.claim_text or ""
        profiles = list(job.profiles or ["dev-laptop", "ci"])
        tier = job.isolation_tier or "standard"
        job.status = "running"
        await s.commit()

    # ---- plan ----
    await _emit_stage(job_id, "plan", "start")
    await _emit_stage(job_id, "fetch", "start")
    # (fetch stage would download npm/zip inside the sandbox — out of scope here)
    await _emit_stage(job_id, "fetch", "end")

    facts = _artifact_facts(content, filename)
    kind = _kind_from_filename(filename)
    try:
        planner_out, tin, tout, _ph = await run_planner(job_id, facts, profiles, kind)
    except Exception as e:
        planner_out = {
            "hypotheses": [{"id": "h1", "text": "Observe behaviour"}],
            "experiments": [{"profile": p, "focus": "all"} for p in profiles],
            "harness": __import__("app.harness_templates", fromlist=["pick"]).pick(kind),
        }
        tin = tout = 0
        await _emit_stage(job_id, "plan", "error", message=f"Planner fallback: {e}")
    else:
        async with SessionLocal() as s:
            j = await s.get(Job, job_id)
            j.llm_tokens_in += tin; j.llm_tokens_out += tout
            await s.commit()
        await _emit_agent(job_id, "planner", 1,
                          f"{len(planner_out['hypotheses'])} hypotheses; harness={planner_out['harness'].get('template','?')}",
                          tin, tout)
    await _emit_stage(job_id, "plan", "end")

    # ---- run per profile ----
    await _emit_stage(job_id, "run", "start")
    events_by_profile: dict[str, list[dict]] = {}
    runs_meta: list[dict] = []
    handle = get_runner_for(tier, job_id)

    # propagate fleet's vm_create events if burn
    for ev in (handle.created_events or []):
        seq = await next_seq(job_id)
        await publish(job_id, {**ev, "id": f"evt_{job_id}_{seq}", "job_id": job_id, "seq": seq, "ts": _now()})

    try:
        for profile in profiles:
            run_id = f"run_{job_id}_{profile}"
            manifest = {
                "run_id": run_id,
                "profile": profile,
                "image": "airlock-sandbox:node-py",
                "files": [
                    *[{"path": f["path"], "content_b64": _b64(f["content"])} for f in planner_out["harness"]["files"]],
                    {"path": f"work/artifact/{filename}", "content_b64": _b64(content)},
                ],
                "entrypoint": planner_out["harness"]["entrypoint"],
                "env": {},
                "limits": {"cpu": 1.0, "mem_mb": 512, "pids": 128, "timeout_s": 30,
                           "disk_mb": 128, "stdout_kb": 256},
                "network": {"mode": "honeynet", "allowlist": []},
                "canary_set": "default",
                "fetch": {"type": None, "ref": None},
            }
            try:
                await handle.client.start_run(manifest)
            except Exception as e:
                await _emit_stage(job_id, "run", "error", message=f"{profile}: {e}", run_id=run_id)
                continue

            async with SessionLocal() as s:
                s.add(RunORM(id=run_id, job_id=job_id, profile=profile,
                             limits_json=manifest["limits"]))
                await s.commit()

            collected: list[dict] = []
            async for ev in handle.client.stream_events(run_id):
                seq = await next_seq(job_id)
                out = {**ev, "id": ev.get("id") or f"evt_{job_id}_{seq}",
                       "job_id": job_id, "run_id": run_id, "seq": seq,
                       "ts": ev.get("ts") or _now()}
                collected.append(out)
                await publish(job_id, out)

            events_by_profile[profile] = collected
            try:
                sm = await handle.client.summary(run_id)
            except Exception:
                sm = {"outcome": "completed", "exit_code": 0, "duration_ms": 0, "artifacts": []}
            runs_meta.append({
                "run_id": run_id, "profile": profile,
                "outcome": sm.get("outcome", "completed"),
                "duration_ms": sm.get("duration_ms", 0),
                "event_count": len(collected),
            })
            async with SessionLocal() as s:
                r = await s.get(RunORM, run_id)
                if r:
                    r.outcome = sm.get("outcome", "completed")
                    r.duration_ms = sm.get("duration_ms", 0)
                    r.event_count = len(collected)
                    r.events_sha256 = hashlib.sha256(
                        json.dumps([e.get("kind") for e in collected]).encode()
                    ).hexdigest()
                    r.ended_at = datetime.utcnow()
                    await s.commit()
    finally:
        destroy = tier == "burn"
        try:
            extra = release_runner(handle, destroy=destroy)
        except Exception:
            extra = []
        for ev in extra:
            seq = await next_seq(job_id)
            await publish(job_id, {**ev, "id": f"evt_{job_id}_{seq}", "job_id": job_id,
                                   "seq": seq, "ts": _now()})

    await _emit_stage(job_id, "run", "end")

    # ---- observe/verify stages are folded into the event stream we already have ----
    await _emit_stage(job_id, "observe", "start")
    await _emit_stage(job_id, "observe", "end")

    # ---- verdict ----
    await _emit_stage(job_id, "verdict", "start")
    verdict, score, findings = evaluate(events_by_profile)

    # ---- explainer (narrative only, cannot change verdict) ----
    try:
        narrative, tin, tout = await run_explainer(
            verdict=verdict,
            artifact_claim=claim_text,
            findings=[{
                "id": f.id, "severity": f.severity, "rule": f.rule,
                "claim": f.claim, "observed": f.observed,
                "evidence_event_ids": f.evidence_event_ids,
            } for f in findings],
            event_summaries=[
                {"id": e["id"], "kind": e["kind"], "severity": e["severity"],
                 "detail_trim": _trim(e.get("detail", {}))}
                for run_events in events_by_profile.values() for e in run_events
            ],
        )
        async with SessionLocal() as s:
            j = await s.get(Job, job_id)
            j.llm_tokens_in += tin; j.llm_tokens_out += tout
            await s.commit()
        await _emit_agent(job_id, "explainer", 2, narrative.get("headline", "")[:120], tin, tout)
    except Exception as e:
        narrative = {"headline": f"Verdict: {verdict}", "behavior_summary": "", "recommendations": [], "claim_mismatch": None}
        await _emit_stage(job_id, "verdict", "error", message=f"Explainer: {e}")

    # persist findings
    async with SessionLocal() as s:
        for f in findings:
            s.add(FindingORM(
                id=f.id, job_id=job_id, severity=f.severity, rule=f.rule,
                claim=f.claim, observed=f.observed,
                evidence_event_ids=f.evidence_event_ids, code_ref=f.code_ref,
            ))
        j = await s.get(Job, job_id)
        j.verdict = verdict
        j.risk_score = score
        j.stage = "verdict"
        j.status = "done"
        j.finished_at = datetime.utcnow()
        await s.commit()

    # ---- receipt ----
    manifest = {
        "artifact_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "image_digest": "sha256:airlock-sandbox-node-py-v1",
        "profiles": profiles,
        "runs": [{"run_id": r["run_id"],
                  "events_sha256": hashlib.sha256(json.dumps(r).encode()).hexdigest(),
                  "stdout_sha256": ""} for r in runs_meta],
        "verdict": verdict,
        "created_at": _now(),
    }
    async with SessionLocal() as s:
        receipt = await create_receipt(s, job_id, manifest)

    await _emit_stage(job_id, "verdict", "end",
                      message=f"verdict={verdict} receipt={receipt['receipt_id']}")


def _b64(s: str) -> str:
    import base64
    return base64.b64encode(s.encode()).decode()


def _trim(detail: dict) -> dict:
    out = {}
    for k, v in detail.items():
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "…"
        else:
            out[k] = v
    return out