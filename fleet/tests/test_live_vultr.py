import base64
import os
import uuid

import pytest

from fleet.manager import FleetManager


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("AIRLOCK_BURN_TESTS") != "1",
        reason="Creates a billed staging VM; requires explicit enablement and real secure Vultr configuration",
    ),
]


async def test_real_vultr_create_analyze_delete_confirmed():
    import asyncio
    from app.runner_client import RunnerClient

    manager = FleetManager()
    assert manager.configured, (
        "Real Vultr staging configuration is required; no mock fallback"
    )
    job_id = f"test_{uuid.uuid4().hex}"
    handle = await asyncio.to_thread(manager.acquire, "burn", job_id)
    print(f"Vultr created instance: {handle.vm_id}")
    try:
        client = RunnerClient(handle.base_url, handle.token)
        run_id = f"run_{job_id}"
        source = "print('trusted staging verification')"
        await client.start_run(
            {
                "run_id": run_id,
                "files": [
                    {
                        "path": "work/check.py",
                        "content_b64": base64.b64encode(source.encode()).decode(),
                    }
                ],
                "entrypoint": ["python3", "work/check.py"],
            }
        )
        events = [event async for event in client.stream_events(run_id)]
        summary = await client.summary(run_id)
        assert summary["outcome"] == "completed" and summary["observation_complete"]
        assert any(
            event["kind"] == "proc" and event["observer"] == "gvisor"
            for event in events
        )
    finally:
        destroyed = await asyncio.to_thread(manager.release, handle)
        assert destroyed[0]["detail"]["confirmed"] is True
        assert (
            await asyncio.to_thread(
                manager._request, "GET", f"/instances/{handle.vm_id}"
            )
            is None
        )
        print(f"Vultr deletion confirmed (GET 404): {handle.vm_id}")
