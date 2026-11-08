import asyncio
import hashlib
import json
from datetime import datetime, timezone

from app.artifacts import prepare_artifact
from app.config import settings
from app.db import SessionLocal
from app.events_bus import next_seq, publish
from app.explainer import explain as run_explainer
from app.harness_templates import pick
from app.models import Finding as FindingORM, Job, Run as RunORM
from app.planner import plan as run_planner
from app.receipts import create_receipt
from app.runner_factory import get_runner_for, release_runner
from app.verdict import evaluate


ACTIVE: dict[str, object] = {}
ACTIVE_RUNS: dict[str, str] = {}
CANCELLED: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _emit_stage(
    job_id: str, name: str, state: str, message: str = "", run_id: str | None = None
):
    if run_id is None and state == "start":
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            job.stage = name
            await session.commit()
    seq = await next_seq(job_id)
    await publish(
        job_id,
        {
            "id": f"evt_{job_id}_{seq}",
            "job_id": job_id,
            "run_id": run_id,
            "seq": seq,
            "ts": _now(),
            "kind": "stage",
            "severity": "info",
            "observer": "orchestrator",
            "source": "orchestrator",
            "detail": {
                "name": name,
                "state": state,
                "run_id": run_id,
                "message": message,
            },
        },
    )


async def _emit_agent(
    job_id: str, role: str, step_no: int, summary: str, tin: int, tout: int
):
    seq = await next_seq(job_id)
    await publish(
        job_id,
        {
            "id": f"evt_{job_id}_{seq}",
            "job_id": job_id,
            "run_id": None,
            "seq": seq,
            "ts": _now(),
            "kind": "agent",
            "severity": "info",
            "observer": "llm",
            "source": "orchestrator",
            "detail": {
                "role": role,
                "step_no": step_no,
                "summary": summary,
                "tokens_in": tin,
                "tokens_out": tout,
            },
        },
    )


async def _fleet_events(job_id: str, events: list[dict]):
    for event in events:
        seq = await next_seq(job_id)
        await publish(
            job_id,
            {
                **event,
                "id": f"evt_{job_id}_{seq}",
                "job_id": job_id,
                "seq": seq,
                "run_id": None,
            },
        )


async def stop_job(job_id: str):
    CANCELLED.add(job_id)
    handle = ACTIVE.get(job_id)
    run_id = ACTIVE_RUNS.get(job_id)
    if handle and run_id:
        await handle.client.kill(run_id)


async def run_job(job_id: str) -> None:
    try:
        await _run_job_inner(job_id)
    except Exception as error:
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if job:
                job.status, job.verdict, job.stage = "error", "ERROR", "verdict"
                job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
        from fleet.manager import FleetError

        message = (
            str(error)
            if isinstance(error, FleetError)
            else f"Analysis failed: {type(error).__name__}. No successful sandbox result is implied."
        )
        await _emit_stage(job_id, "verdict", "error", message=message)
    finally:
        ACTIVE.pop(job_id, None)
        ACTIVE_RUNS.pop(job_id, None)
        CANCELLED.discard(job_id)


async def _run_job_inner(job_id: str) -> None:
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        artifact = prepare_artifact(job.input_type, job.input_ref, job.filename)
        profiles, tier, claim_text = (
            list(job.profiles),
            job.isolation_tier,
            job.claim_text,
        )
        job.execution_mode = "mock" if settings.USE_STUB_RUNNER else "live"
        sample_id = job.sample_id
        job.status = "running"
        await session.commit()
    await _emit_stage(job_id, "fetch", "start")
    await _emit_stage(
        job_id,
        "fetch",
        "end",
        message=f"Validated {len(artifact.files)} artifact files; no code executed on control plane",
    )
    await _emit_stage(job_id, "plan", "start")
    harness = pick(artifact.kind)
    facts = {
        "filename": artifact.filename,
        "entrypoint": artifact.entrypoint,
        "files": [
            {"path": path, "size": len(content)}
            for path, content in artifact.files.items()
        ],
    }
    plan_message = ""
    if settings.INFERENCE_API_KEY:
        try:
            plan, tin, tout, _ = await run_planner(
                job_id, facts, profiles, artifact.kind
            )
            await _emit_agent(
                job_id,
                "planner",
                1,
                f"{len(plan['hypotheses'])} hypotheses; trusted {artifact.kind} harness",
                tin,
                tout,
            )
        except Exception:
            plan_message = (
                "Inference unavailable; trusted deterministic harness selected"
            )
    await _emit_stage(job_id, "plan", "end", message=plan_message)
    await _emit_stage(job_id, "run", "start")
    handle = await asyncio.to_thread(get_runner_for, tier, job_id)
    ACTIVE[job_id] = handle
    collected_by_profile: dict[str, list[dict]] = {}
    runs = []
    try:
        await _fleet_events(job_id, handle.created_events or [])
        for profile in profiles:
            if job_id in CANCELLED:
                break
            run_id = f"run_{job_id}_{profile}"
            environment = {
                "AIRLOCK_ARTIFACT_ENTRY": artifact.entrypoint,
                "AIRLOCK_ARTIFACT_KIND": artifact.kind,
            }
            if settings.USE_STUB_RUNNER:
                if not sample_id:
                    raise RuntimeError("Mock runner only accepts named team samples")
                environment["AIRLOCK_SAMPLE"] = sample_id
            manifest = {
                "run_id": run_id,
                "profile": profile,
                "image": "airlock-sandbox:node-py",
                "files": [
                    {"path": item["path"], "content_b64": _b64(item["content"])}
                    for item in harness["files"]
                ]
                + artifact.manifest_files(),
                "entrypoint": harness["entrypoint"],
                "env": environment,
                "limits": {
                    "cpu": 1.0,
                    "mem_mb": 512,
                    "pids": 128,
                    "timeout_s": 30,
                    "disk_mb": 128,
                    "stdout_kb": 256,
                },
                "network": {"mode": "honeynet", "allowlist": []},
                "canary_set": "default",
            }
            await handle.client.start_run(manifest)
            ACTIVE_RUNS[job_id] = run_id
            async with SessionLocal() as session:
                session.add(
                    RunORM(
                        id=run_id,
                        job_id=job_id,
                        profile=profile,
                        limits_json=manifest["limits"],
                    )
                )
                await session.commit()
            events = []
            async for event in handle.client.stream_events(run_id):
                if event.get("source") not in {"host", "orchestrator"} or event.get(
                    "run_id"
                ) not in {None, run_id}:
                    raise ValueError("Invalid Runner event identity or source")
                if (
                    event.get("kind") in {"file", "proc", "net", "canary", "limit"}
                    and event["source"] != "host"
                ):
                    raise ValueError("Behavioral evidence must originate from the host")
                seq = await next_seq(job_id)
                output = {**event, "job_id": job_id, "run_id": run_id, "seq": seq}
                output = await publish(job_id, output)
                events.append(output)
            summary = await handle.client.summary(run_id)
            if not settings.USE_STUB_RUNNER and not summary.get("observation_complete"):
                raise RuntimeError("Runtime observation is incomplete")
            event_hash = hashlib.sha256(
                json.dumps(
                    events, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
            runs.append(
                {
                    "run_id": run_id,
                    "profile": profile,
                    **summary,
                    "events_sha256": event_hash,
                }
            )
            collected_by_profile[profile] = sorted(
                events, key=lambda event: event["ts"]
            )
            async with SessionLocal() as session:
                row = await session.get(RunORM, run_id)
                row.outcome, row.exit_code = summary["outcome"], summary["exit_code"]
                row.duration_ms, row.event_count = summary["duration_ms"], len(events)
                row.events_sha256 = event_hash
                row.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
            ACTIVE_RUNS.pop(job_id, None)
    finally:
        try:
            active_run = ACTIVE_RUNS.pop(job_id, None)
            if active_run:
                await handle.client.kill(active_run)
        finally:
            extra = await asyncio.to_thread(release_runner, handle, tier == "burn")
            await _fleet_events(job_id, extra)
    await _emit_stage(job_id, "run", "end")
    await _emit_stage(job_id, "observe", "start")
    await _emit_stage(job_id, "observe", "end")
    await _emit_stage(job_id, "verify", "start")
    verdict, score, findings = evaluate(collected_by_profile)
    if job_id in CANCELLED or (
        verdict == "SAFE_OBSERVED"
        and (
            len(runs) != len(profiles)
            or not all(run["outcome"] == "completed" for run in runs)
        )
    ):
        verdict, score = "ERROR", 0
    verify_message = ""
    if settings.INFERENCE_API_KEY:
        try:
            narrative, tin, tout = await run_explainer(
                verdict,
                claim_text,
                [
                    {
                        "id": finding.id,
                        "rule": finding.rule,
                        "observed": finding.observed,
                        "evidence_event_ids": finding.evidence_event_ids,
                    }
                    for finding in findings
                ],
                [
                    {"id": event["id"], "kind": event["kind"]}
                    for events in collected_by_profile.values()
                    for event in events
                ][:200],
            )
            await _emit_agent(
                job_id,
                "explainer",
                2,
                str(narrative.get("headline", ""))[:500],
                tin,
                tout,
            )
            async with SessionLocal() as session:
                job = await session.get(Job, job_id)
                job.llm_model = settings.INFERENCE_MODEL_EXPLAINER
                job.llm_tokens_in += tin
                job.llm_tokens_out += tout
                await session.commit()
        except Exception:
            verify_message = "Narrative inference unavailable; verdict remains based on host evidence"
    async with SessionLocal() as session:
        for finding in findings:
            session.add(
                FindingORM(
                    id=f"{job_id}_{finding.id}",
                    job_id=job_id,
                    severity=finding.severity,
                    rule=finding.rule,
                    claim=claim_text or finding.claim,
                    observed=finding.observed,
                    evidence_event_ids=finding.evidence_event_ids,
                    code_ref=finding.code_ref,
                )
            )
        job = await session.get(Job, job_id)
        job.verdict, job.risk_score, job.stage = verdict, score, "verify"
        await session.commit()
    receipt_manifest = {
        "artifact_sha256": artifact.sha256,
        "image_digest": runs[0].get("image_digest", "") if runs else "",
        "profiles": profiles,
        "runs": [
            {
                "run_id": run["run_id"],
                "events_sha256": run["events_sha256"],
                "stdout_sha256": run.get("stdout_sha256", ""),
            }
            for run in runs
        ],
        "verdict": verdict,
        "created_at": _now(),
        "mode": "mock" if settings.USE_STUB_RUNNER else "live",
    }
    async with SessionLocal() as session:
        await create_receipt(session, job_id, receipt_manifest)
    await _emit_stage(job_id, "verify", "end", message=verify_message)
    await _emit_stage(job_id, "verdict", "start")
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        job.status = "error" if verdict == "ERROR" else "done"
        job.stage = "verdict"
        job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()
    await _emit_stage(job_id, "verdict", "end", message=f"verdict={verdict}")


def _b64(value: str) -> str:
    import base64

    return base64.b64encode(value.encode()).decode()
