import asyncio
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Event as EventORM


_global_seq: dict[str, int] = defaultdict(int)
_lock = asyncio.Lock()


async def next_seq(job_id: str) -> int:
    async with _lock:
        if job_id not in _global_seq:
            async with SessionLocal() as session:
                maximum = await session.scalar(
                    select(func.max(EventORM.seq)).where(EventORM.job_id == job_id)
                )
                _global_seq[job_id] = maximum or 0
        _global_seq[job_id] += 1
        return _global_seq[job_id]


async def publish(job_id: str, event: dict) -> dict:
    if event.get("source") not in {"host", "orchestrator"}:
        raise ValueError("Invalid event source")
    timestamp = event["ts"]
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
    async with SessionLocal() as session:
        session.add(
            EventORM(
                id=event["id"],
                job_id=job_id,
                run_id=event.get("run_id"),
                seq=event["seq"],
                ts=timestamp,
                kind=event["kind"],
                severity=event["severity"],
                observer=event["observer"],
                source=event["source"],
                detail=event["detail"],
            )
        )
        await session.commit()
    return {**event, "ts": timestamp.replace(tzinfo=timezone.utc).isoformat()}


async def subscribe(job_id: str, after_seq: int = 0) -> AsyncIterator[dict | None]:
    cursor = after_seq
    heartbeat_at = time.monotonic()
    while True:
        async with SessionLocal() as session:
            rows = (
                (
                    await session.execute(
                        select(EventORM)
                        .where(EventORM.job_id == job_id, EventORM.seq > cursor)
                        .order_by(EventORM.seq)
                    )
                )
                .scalars()
                .all()
            )
        for row in rows:
            cursor = row.seq
            event = _to_dict(row)
            yield event
            if (
                event["kind"] == "stage"
                and event["detail"].get("name") == "verdict"
                and event["detail"].get("state") in {"end", "error"}
            ):
                return
        if not rows:
            async with SessionLocal() as session:
                last = await session.scalar(
                    select(EventORM)
                    .where(EventORM.job_id == job_id)
                    .order_by(EventORM.seq.desc())
                    .limit(1)
                )
            if (
                last
                and last.kind == "stage"
                and last.detail.get("name") == "verdict"
                and last.detail.get("state") in {"end", "error"}
            ):
                return
        if time.monotonic() - heartbeat_at >= 10:
            yield None
            heartbeat_at = time.monotonic()
        await asyncio.sleep(0.1)


def _to_dict(row: EventORM) -> dict:
    timestamp = (
        row.ts.replace(tzinfo=timezone.utc)
        if row.ts.tzinfo is None
        else row.ts.astimezone(timezone.utc)
    )
    return {
        "id": row.id,
        "job_id": row.job_id,
        "run_id": row.run_id,
        "seq": row.seq,
        "ts": timestamp.isoformat(),
        "kind": row.kind,
        "severity": row.severity,
        "observer": row.observer,
        "source": row.source,
        "detail": row.detail,
    }
