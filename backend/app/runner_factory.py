import logging
from dataclasses import dataclass

from app.config import settings
from app.runner_client import RunnerClient
from app.runner_client_stub import RunnerStub

log = logging.getLogger(__name__)


@dataclass
class RunnerHandle:
    client: object
    base_url: str
    tier: str
    vm_id: str | None = None
    created_events: list | None = None


def get_runner_for(tier: str, job_id: str) -> RunnerHandle:
    # 1) fleet (imported lazily)
    if tier == "burn":
        try:
            import fleet  # type: ignore
            h = fleet.acquire("burn", job_id)
            return RunnerHandle(client=RunnerClient(h.base_url, h.token),
                                base_url=h.base_url, tier="burn", vm_id=h.vm_id,
                                created_events=list(getattr(h, "created_events", []) or []))
        except Exception as e:
            log.warning("fleet.burn unavailable (%s); falling back to standard", e)

    # 2) explicit stub override
    if settings.USE_STUB_RUNNER:
        log.info("Using STUB runner for job=%s", job_id)
        return RunnerHandle(client=RunnerStub(), base_url="stub://local", tier=tier)

    # 3) direct runner URL from env
    if settings.RUNNER_URL:
        return RunnerHandle(
            client=RunnerClient(settings.RUNNER_URL, settings.RUNNER_TOKEN),
            base_url=settings.RUNNER_URL, tier=tier,
        )

    # 4) last resort: stub with loud log
    log.warning("No RUNNER_URL configured; falling back to STUB runner (dev only)")
    return RunnerHandle(client=RunnerStub(), base_url="stub://local", tier=tier)


def release_runner(handle: RunnerHandle, destroy: bool) -> list:
    if handle.tier == "burn":
        try:
            import fleet  # type: ignore
            return fleet.release(_make_fleet_handle(handle), destroy=True)
        except Exception as e:
            log.warning("fleet.release failed: %s", e)
    return []


def _make_fleet_handle(handle: RunnerHandle):
    try:
        import fleet  # type: ignore
        return fleet.RunnerHandle(
            base_url=handle.base_url, token="", tier="burn",
            vm_id=handle.vm_id, created_events=handle.created_events or [],
        )
    except Exception:
        return None