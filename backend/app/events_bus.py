import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Event as EventORM

_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
_global_seq: dict[str, int] = defaultdict(int)
_lock = asyncio.Lock()


def _utc_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def next_seq(job_id: str) -> int:
    async with _lock:
        _global_seq[job_id] += 1
        return _global_seq[job_id]


async def publish(job_id: str, event: dict) -> None:
    """Persist + fanout."""
    timestamp = _utc_datetime(event["ts"])
    event = {**event, "ts": timestamp.isoformat().replace("+00:00", "Z")}
    async with SessionLocal() as session:
        orm = EventORM(
            job_id=job_id,
            run_id=event.get("run_id"),
            seq=event["seq"],
            ts=timestamp.replace(tzinfo=None),
            kind=event["kind"],
            severity=event["severity"],
            observer=event["observer"],
            source=event["source"],
            detail=event["detail"],
        )
        session.add(orm)
        await session.commit()
    for q in list(_queues.get(job_id, [])):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


async def subscribe(job_id: str, after_seq: int = 0) -> AsyncIterator[dict]:
    """Yield events: replayed history then live."""
    # replay
    async with SessionLocal() as session:
        stmt = (
            select(EventORM)
            .where(EventORM.job_id == job_id, EventORM.seq > after_seq)
            .order_by(EventORM.seq.asc())
        )
        for row in (await session.execute(stmt)).scalars().all():
            yield _to_dict(row)

    q: asyncio.Queue = asyncio.Queue(maxsize=4096)
    _queues[job_id].append(q)
    try:
        while True:
            ev = await q.get()
            if ev["seq"] <= after_seq:
                continue
            yield ev
    finally:
        try:
            _queues[job_id].remove(q)
        except ValueError:
            pass


def _to_dict(row: EventORM) -> dict:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "run_id": row.run_id,
        "seq": row.seq,
        "ts": _utc_datetime(row.ts).isoformat().replace("+00:00", "Z"),
        "kind": row.kind,
        "severity": row.severity,
        "observer": row.observer,
        "source": row.source,
        "detail": row.detail,
    }
