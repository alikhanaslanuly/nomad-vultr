import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import events_bus, main
from app.models import Base, Event, Finding, Job


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-11-08T20:45:25.627692Z",
        "2026-11-08T22:45:25.627692+02:00",
        datetime(2026, 11, 8, 20, 45, 25, 627692),
        datetime(2026, 11, 8, 22, 45, 25, 627692, timezone(timedelta(hours=2))),
    ],
)
async def test_event_timestamp_persists_and_replays_as_utc(monkeypatch, timestamp):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    queue = asyncio.Queue()
    monkeypatch.setattr(events_bus, "SessionLocal", sessions)
    events_bus._queues["job_timestamp_regression"].append(queue)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(Job(id="job_timestamp_regression", input_type="paste"))
            await session.commit()
        await events_bus.publish(
            "job_timestamp_regression",
            {
                "id": "event_timestamp_regression",
                "job_id": "job_timestamp_regression",
                "run_id": None,
                "seq": 1,
                "ts": timestamp,
                "kind": "stage",
                "severity": "info",
                "observer": "orchestrator",
                "source": "orchestrator",
                "detail": {"name": "fetch", "state": "start"},
            },
        )
        live = queue.get_nowait()
        assert live["ts"] == "2026-11-08T20:45:25.627692Z"
        async with sessions() as session:
            persisted = (await session.execute(select(Event))).scalar_one()
            assert persisted.ts == datetime(2026, 11, 8, 20, 45, 25, 627692)
            assert events_bus._to_dict(persisted)["ts"] == live["ts"]
            persisted.ts = datetime(
                2026, 11, 8, 22, 45, 25, 627692, timezone(timedelta(hours=2))
            )
            assert events_bus._to_dict(persisted)["ts"] == live["ts"]
    finally:
        events_bus._queues.pop("job_timestamp_regression", None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_job_dates_and_nullable_finding_match_frontend_contract(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", sessions)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(
                Job(
                    id="job_contract_regression",
                    input_type="paste",
                    status="done",
                    stage="verdict",
                    verdict="ERROR",
                    created_at=datetime(2026, 11, 8, 20, 45, 25),
                    finished_at=datetime(2026, 11, 8, 20, 45, 30),
                )
            )
            session.add(
                Finding(
                    id="finding_contract_regression",
                    job_id="job_contract_regression",
                    severity="warn",
                    code_ref=None,
                )
            )
            await session.commit()
        job = await main.get_job("job_contract_regression")
        assert job["created_at"] == "2026-11-08T20:45:25Z"
        assert job["finished_at"] == "2026-11-08T20:45:30Z"
        assert (await main.list_jobs())[0] == job
        report = await main.get_report("job_contract_regression")
        assert "code_ref" not in report["findings"][0]
        assert main._utc_timestamp(
            datetime(2026, 11, 8, 22, 45, 25, tzinfo=timezone(timedelta(hours=2)))
        ) == job["created_at"]
    finally:
        await engine.dispose()
