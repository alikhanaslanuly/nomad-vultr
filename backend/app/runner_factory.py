from dataclasses import dataclass

from app.config import settings
from app.runner_client import RunnerClient
from app.runner_client_stub import RunnerStub


@dataclass
class RunnerHandle:
    client: RunnerClient | RunnerStub
    base_url: str
    tier: str
    vm_id: str | None = None
    created_events: list | None = None
    fleet_handle: object | None = None


def get_runner_for(tier: str, job_id: str) -> RunnerHandle:
    if tier == "burn":
        if settings.USE_STUB_RUNNER:
            raise RuntimeError("Burn VM cannot use a simulated runner")
        import fleet

        handle = fleet.acquire("burn", job_id)
        return RunnerHandle(
            RunnerClient(handle.base_url, handle.token),
            handle.base_url,
            "burn",
            handle.vm_id,
            handle.created_events,
            handle,
        )
    if settings.USE_STUB_RUNNER:
        return RunnerHandle(RunnerStub(), "stub://local", "standard")
    if not settings.RUNNER_URL or not settings.RUNNER_TOKEN:
        raise RuntimeError(
            "Real runner URL and authentication must be configured; implicit mock fallback is forbidden"
        )
    return RunnerHandle(
        RunnerClient(settings.RUNNER_URL, settings.RUNNER_TOKEN),
        settings.RUNNER_URL,
        "standard",
    )


def release_runner(handle: RunnerHandle, destroy: bool) -> list:
    if handle.tier == "burn":
        import fleet

        return fleet.release(handle.fleet_handle, destroy=destroy)
    return []
