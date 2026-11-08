import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("RECEIPT_SIGNING_KEY", "FAKE-TEST-RECEIPT-KEY")

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def app_client(monkeypatch):
    from app import db, events_bus, main, orchestrator
    from app.config import settings
    from app.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    for module in (db, events_bus, main, orchestrator):
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(settings, "USE_STUB_RUNNER", True)
    monkeypatch.setattr(settings, "INFERENCE_API_KEY", "")
    monkeypatch.setattr(settings, "RECEIPT_SIGNING_KEY", "FAKE-TEST-RECEIPT-KEY")
    monkeypatch.setattr(settings, "invite_codes", [])
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MIN", 1000)
    events_bus._global_seq.clear()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        yield client
    await engine.dispose()
