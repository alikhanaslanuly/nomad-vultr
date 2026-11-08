from dataclasses import dataclass, field

from .manager import FleetManager


@dataclass
class RunnerHandle:
    base_url: str
    token: str = field(repr=False)
    tier: str
    vm_id: str | None = None
    created_events: list[dict] = field(default_factory=list)


_manager: FleetManager | None = None


def get_manager() -> FleetManager:
    global _manager
    if _manager is None:
        _manager = FleetManager()
    return _manager


def acquire(tier: str, job_id: str) -> RunnerHandle:
    return get_manager().acquire(tier, job_id)


def release(handle: RunnerHandle, destroy: bool = True) -> list:
    return get_manager().release(handle, destroy)


def reap() -> int:
    return get_manager().reap()
