from unittest.mock import AsyncMock

import pytest

from runner.executor import SandboxExecutor
from runner.models import RunManifest


@pytest.mark.asyncio
async def test_cleanup_attempts_all_owned_resources_and_never_claims_failed_destroy(
    monkeypatch,
):
    from runner import executor as module

    executor = SandboxExecutor(RunManifest(run_id="test_cleanup", entrypoint=["true"]))
    executor.container_id, executor.sink_id, executor.network_id = (
        "container",
        "sink",
        "network",
    )
    command = AsyncMock(side_effect=[RuntimeError("denied"), "sink", "network"])
    monkeypatch.setattr(module, "docker", command)
    with pytest.raises(RuntimeError, match="not confirmed"):
        await executor.cleanup()
    assert command.await_count == 3
    assert (
        executor.container_id == "container"
        and executor.sink_id is None
        and executor.network_id is None
    )
    assert not executor.observer.events


@pytest.mark.asyncio
async def test_stop_race_accepts_already_exited_container_without_masking_running_failure(
    monkeypatch,
):
    from runner import executor as module

    executor = SandboxExecutor(RunManifest(run_id="test_stop", entrypoint=["true"]))
    executor.container_id = "container"
    monkeypatch.setattr(
        module,
        "inspect_container",
        AsyncMock(
            side_effect=[{"State": {"Running": True}}, {"State": {"Running": False}}]
        ),
    )
    monkeypatch.setattr(
        module, "docker", AsyncMock(side_effect=RuntimeError("already stopped"))
    )
    await executor._stop_container()
    monkeypatch.setattr(
        module,
        "inspect_container",
        AsyncMock(return_value={"State": {"Running": True}}),
    )
    with pytest.raises(RuntimeError):
        await executor._stop_container()


@pytest.mark.asyncio
async def test_honeynet_fails_closed_without_host_network_guard(monkeypatch):
    from runner import executor as module

    executor = SandboxExecutor(RunManifest(run_id="test_guard", entrypoint=["true"]))
    process = AsyncMock()
    process.returncode = 1
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(RuntimeError, match="isolation guard"):
        await executor.prepare_network()
    assert executor.network_id is None
    assert spawn.call_args.args[0:2] == ("iptables", "-C")
