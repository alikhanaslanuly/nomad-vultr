from dataclasses import dataclass, field
from typing import Literal, Optional, List, Dict, Any
import os
import logging
from .manager import FleetManager

log = logging.getLogger(__name__)

@dataclass
class RunnerHandle:
    base_url: str          # http://10.x.x.x:9000
    token: str             # RUNNER_TOKEN для этого раннера
    tier: Literal["standard", "burn"]
    vm_id: Optional[str] = None   # Vultr instance id для burn, иначе None
    created_events: List[Dict[str, Any]] = field(default_factory=list)   # system-события (vm_create и т.п.)

_fleet_manager: Optional[FleetManager] = None

def get_manager() -> FleetManager:
    global _fleet_manager
    if _fleet_manager is None:
        _fleet_manager = FleetManager()
    return _fleet_manager

def acquire(tier: Literal["standard", "burn"], job_id: str) -> RunnerHandle:
    """Acquire a runner handle for the specified tier ('standard' or 'burn')."""
    return get_manager().acquire(tier=tier, job_id=job_id)

def release(handle: RunnerHandle, destroy: bool = True) -> list:
    """Release a runner handle, returning system-events (e.g. vm_destroy)."""
    return get_manager().release(handle=handle, destroy=destroy)

def reap() -> int:
    """Destroy Vultr instances with tag 'airlock' older than FLEET_MAX_AGE_MIN. Returns count destroyed."""
    return get_manager().reap()

__all__ = ["RunnerHandle", "acquire", "release", "reap", "FleetManager"]
