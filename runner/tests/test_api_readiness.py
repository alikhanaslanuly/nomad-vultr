from unittest.mock import AsyncMock

import httpx
import pytest

from runner import main


pytestmark = pytest.mark.asyncio


async def test_authentication_is_required_and_invalid_health_auth_does_not_probe(
    monkeypatch,
):
    monkeypatch.setattr(main.settings, "RUNNER_TOKEN", "FAKE_UNIT_TEST_ONLY")
    health = AsyncMock()
    monkeypatch.setattr(main, "runtime_health", health)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://unit"
    ) as client:
        response = await client.get(
            "/healthz", headers={"Authorization": "Bearer wrong"}
        )
        assert response.status_code == 403
        response = await client.post(
            "/v1/runs", json={"run_id": "test_auth", "entrypoint": ["true"]}
        )
        assert response.status_code == 403
    health.assert_not_called()


async def test_unverified_health_rejects_execution_without_creating_a_task(monkeypatch):
    monkeypatch.setattr(main.settings, "RUNNER_TOKEN", "FAKE_UNIT_TEST_ONLY")
    monkeypatch.setattr(
        main,
        "runtime_health",
        AsyncMock(return_value={"ok": False, "observer_verified": False}),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://unit"
    ) as client:
        response = await client.post(
            "/v1/runs",
            headers={"Authorization": "Bearer FAKE_UNIT_TEST_ONLY"},
            json={"run_id": "test_unready", "entrypoint": ["true"]},
        )
        assert response.status_code == 503
    assert "test_unready" not in main.RUNS and "test_unready" not in main.TASKS


async def test_unconfigured_authentication_is_never_a_dev_bypass(monkeypatch):
    monkeypatch.setattr(main.settings, "RUNNER_TOKEN", "")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://unit"
    ) as client:
        response = await client.post(
            "/v1/runs",
            headers={"Authorization": "Bearer anything"},
            json={"run_id": "test_no_token", "entrypoint": ["true"]},
        )
        assert response.status_code == 503
