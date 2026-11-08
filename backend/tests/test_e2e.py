import os
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("USE_STUB_RUNNER", "1")
os.environ.setdefault("INFERENCE_MODEL_PLANNER", "stub")
os.environ.setdefault("INFERENCE_MODEL_EXPLAINER", "stub")
os.environ.setdefault("RECEIPT_SIGNING_KEY", "test-key")


@pytest.fixture(scope="session")
async def app_client():
    # fresh in-memory DB per session
    from app import db as db_mod
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    db_mod.engine = engine
    db_mod.SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    from app import models
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(app_client):
    r = await app_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_samples_listed(app_client):
    r = await app_client.get("/api/samples")
    ids = {s["id"] for s in r.json()}
    assert "evil-installer" in ids


@pytest.mark.asyncio
async def test_evil_installer_reports_malicious(app_client):
    r = await app_client.post("/api/samples/evil-installer/run",
                              json={"profiles": ["dev-laptop"]})
    assert r.status_code == 201
    job_id = r.json()["job_id"]
    # poll for done
    import asyncio
    for _ in range(40):
        s = await app_client.get(f"/api/jobs/{job_id}")
        if s.json()["status"] == "done":
            break
        await asyncio.sleep(0.25)
    rep = await app_client.get(f"/api/jobs/{job_id}/report")
    assert rep.status_code == 200, rep.text
    body = rep.json()
    assert body["verdict"] == "MALICIOUS"
    assert body["risk_score"] >= 85
    assert body["receipt_id"]
    assert any(f["evidence_event_ids"] for f in body["findings"])