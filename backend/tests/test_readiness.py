import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def test_inference_health_checks_real_endpoint_and_required_models(monkeypatch):
    from app import llm
    from app.config import settings

    monkeypatch.setattr(settings, "INFERENCE_API_KEY", "FAKE_UNIT_TEST_ONLY")
    monkeypatch.setattr(settings, "INFERENCE_MODEL_PLANNER", "test-model")
    monkeypatch.setattr(settings, "INFERENCE_MODEL_EXPLAINER", "test-model")
    monkeypatch.setattr(llm, "_health_at", 0)
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "test-model"}]})
    )
    monkeypatch.setattr(
        llm.httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport)
    )
    assert await llm.inference_health() is True
    monkeypatch.setattr(llm, "_health_at", 0)
    transport = httpx.MockTransport(lambda request: httpx.Response(403))
    assert await llm.inference_health() is False


async def test_additive_migration_preserves_existing_jobs_and_committed_data(
    monkeypatch, tmp_path
):
    from app import db

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as connection:
        await connection.execute(
            text("CREATE TABLE jobs (id VARCHAR PRIMARY KEY, input_ref TEXT)")
        )
        await connection.execute(
            text("INSERT INTO jobs VALUES ('legacy', 'preserved')")
        )
    monkeypatch.setattr(db, "engine", engine)
    await db.init_db()
    await db.init_db()
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT id, input_ref, filename, execution_mode, sample_id FROM jobs"
                )
            )
        ).one()
        assert tuple(row) == ("legacy", "preserved", "install.sh", "unknown", None)
    await engine.dispose()


async def test_nanosecond_runtime_timestamp_is_canonicalized_for_receipt_replay(
    app_client,
):
    from app.events_bus import next_seq, publish, subscribe
    from app.db import SessionLocal
    from app.models import Job

    async with SessionLocal() as session:
        job = Job(input_type="paste", filename="test.py", input_ref="print(1)")
        session.add(job)
        await session.commit()
    event = {
        "id": "actual-runtime-id",
        "job_id": job.id,
        "run_id": "run",
        "seq": await next_seq(job.id),
        "ts": "2026-11-09T00:00:00.123456789Z",
        "kind": "proc",
        "severity": "info",
        "observer": "gvisor",
        "source": "host",
        "detail": {"op": "exec", "argv": ["/bin/true"], "pid": 7},
    }
    persisted = await publish(job.id, event)
    stream = subscribe(job.id)
    replayed = await anext(stream)
    await stream.aclose()
    assert replayed == persisted
