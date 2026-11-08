import pytest


async def test_health_exposes_explicit_mock_and_capabilities(app_client):
    response = await app_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "mock"
    assert response.json()["runner"] == "down"
    assert response.json()["capabilities"]["zip"] is False


async def test_samples_listed(app_client):
    response = await app_client.get("/api/samples")
    assert "evil-installer" in {sample["id"] for sample in response.json()}


@pytest.mark.parametrize(
    "sample,verdict",
    [
        ("evil-installer", "MALICIOUS"),
        ("benign-csv-tool", "SAFE_OBSERVED"),
        ("readme-lies", "SUSPICIOUS"),
    ],
)
async def test_sample_report_receipt_and_replayed_evidence_ids_match(
    app_client, sample, verdict
):
    created = await app_client.post(
        f"/api/samples/{sample}/run", json={"profiles": ["dev-laptop"]}
    )
    assert created.status_code == 201
    job_id = created.json()["job_id"]
    report_response = await app_client.get(f"/api/jobs/{job_id}/report")
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()
    assert report["verdict"] == verdict
    assert report["mode"] == "mock"
    assert report["limitations"] and report["receipt_id"]
    receipt = await app_client.get(f"/api/receipts/{report['receipt_id']}")
    assert receipt.status_code == 200 and receipt.json()["manifest"]["mode"] == "mock"
    response = await app_client.get(f"/api/jobs/{job_id}/events")
    import json

    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    import hashlib

    for run in receipt.json()["manifest"]["runs"]:
        replayed = [event for event in events if event["run_id"] == run["run_id"]]
        canonical = json.dumps(
            replayed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        assert hashlib.sha256(canonical.encode()).hexdigest() == run["events_sha256"]
    ids = {event["id"] for event in events}
    assert all(event["job_id"] == job_id for event in events)
    assert all(
        reference in ids
        for finding in report["findings"]
        for reference in finding["evidence_event_ids"]
    )


async def test_filename_and_source_are_preserved_end_to_end(app_client, monkeypatch):
    from app import main
    from app.config import settings

    monkeypatch.setattr(settings, "USE_STUB_RUNNER", False)

    async def no_execution(job_id):
        return

    monkeypatch.setattr(main, "run_job", no_execution)
    response = await app_client.post(
        "/api/jobs",
        json={
            "input_type": "paste",
            "filename": "script.py",
            "content": "print('test')",
            "profiles": ["ci"],
        },
    )
    assert response.status_code == 201
    job_id = response.json()["job_id"]
    source = (await app_client.get(f"/api/jobs/{job_id}/source")).json()
    assert source["files"] == [
        {"path": "script.py", "language": "python", "content": "print('test')"}
    ]


async def test_zip_traversal_and_registry_npm_are_rejected_before_job_creation(
    app_client,
):
    from backend.tests.test_artifacts import archive

    response = await app_client.post(
        "/api/jobs",
        json={
            "input_type": "zip",
            "filename": "input.zip",
            "content": archive({"../../etc/test": "test"}),
        },
    )
    assert response.status_code == 422
    response = await app_client.post(
        "/api/jobs", json={"input_type": "npm", "ref": "left-pad@1.3.0"}
    )
    assert response.status_code == 501


async def test_invalid_profiles_are_422_and_mock_never_accepts_arbitrary_upload(
    app_client,
):
    invalid = await app_client.post(
        "/api/samples/benign-csv-tool/run", json={"profiles": ["ci", "ci"]}
    )
    assert invalid.status_code == 422
    missing = await app_client.get("/api/jobs/not-found/events")
    assert missing.status_code == 404
    upload = await app_client.post(
        "/api/jobs",
        json={"input_type": "paste", "filename": "script.py", "content": "print(1)"},
    )
    assert upload.status_code == 503


async def test_terminal_replay_with_cursor_already_consumed_returns(app_client):
    created = await app_client.post(
        "/api/samples/benign-csv-tool/run", json={"profiles": ["ci"]}
    )
    response = await app_client.get(
        f"/api/jobs/{created.json()['job_id']}/events?after_seq=99999"
    )
    assert response.status_code == 200 and "data:" not in response.text


async def test_legacy_runner_health_cannot_claim_observer_ready(
    app_client, monkeypatch
):
    from app.config import settings
    from app.runner_client import RunnerClient

    async def legacy_health(self):
        return {"ok": True, "runtime": "runc", "observer": "strace"}

    monkeypatch.setattr(settings, "USE_STUB_RUNNER", False)
    monkeypatch.setattr(settings, "RUNNER_URL", "http://unit-test")
    monkeypatch.setattr(RunnerClient, "healthz", legacy_health)
    response = await app_client.get("/api/health")
    assert response.json()["runner"] == "down"
    assert response.json()["observer_verified"] is False


async def test_legacy_queued_stage_remains_compatible_without_overwriting_history(
    app_client,
):
    from app.db import SessionLocal
    from app.models import Job

    async with SessionLocal() as session:
        job = Job(
            input_type="paste",
            input_ref="print(1)",
            stage="queued",
            execution_mode="unknown",
        )
        session.add(job)
        await session.commit()
    response = await app_client.get(f"/api/jobs/{job.id}")
    assert response.json()["stage"] == "fetch" and response.json()["mode"] == "unknown"
    async with SessionLocal() as session:
        assert (await session.get(Job, job.id)).stage == "queued"
