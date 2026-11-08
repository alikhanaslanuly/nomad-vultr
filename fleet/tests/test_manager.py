from unittest.mock import Mock

import pytest

from fleet import RunnerHandle
from fleet.manager import FleetError, FleetManager


VM = "00000000-0000-4000-8000-000000000001"


def manager():
    value = FleetManager()
    value.vultr_api_key = "FAKE_UNIT_TEST_ONLY"
    value.vultr_region, value.vultr_plan_burn, value.vultr_snapshot_id = (
        "test",
        "test-plan",
        "test-snapshot",
    )
    value.firewall_group, value.vpc_id, value.runner_token = (
        "test-firewall",
        "test-vpc",
        "FAKE_TEST_RUNNER",
    )
    value.owner_tag = "airlock-test-only"
    value.timeout = 0.01
    value.poll_interval = 0
    return value


def test_missing_key_never_creates_a_synthetic_vm(monkeypatch):
    value = FleetManager()
    value.vultr_api_key = ""
    request = Mock()
    monkeypatch.setattr(value, "_request", request)
    with pytest.raises(FleetError, match="no mock fallback"):
        value.acquire("burn", "job-test")
    request.assert_not_called()


def test_acquire_waits_for_verified_runner_and_preserves_real_provider_id(monkeypatch):
    value = manager()
    calls = []

    def request(method, path, payload=None):
        calls.append((method, path, payload))
        if path.startswith("/instances?"):
            return {"instances": []}
        if path.endswith("/vpcs"):
            return {"vpcs": [{"id": value.vpc_id, "ip_address": "10.0.0.8"}]}
        if method == "POST":
            return {"instance": {"id": VM}}
        return {
            "instance": {
                "id": VM,
                "internal_ip": "10.0.0.8",
                "status": "active",
                "power_status": "running",
                "server_status": "ok",
            }
        }

    monkeypatch.setattr(value, "_request", request)
    monkeypatch.setattr(value, "_probe_runner", lambda url: True)
    handle = value.acquire("burn", "job-test")
    assert handle.vm_id == VM and handle.base_url == "http://10.0.0.8:9000"
    assert handle.created_events[0]["detail"]["op"] == "vm_create"
    assert calls[1][2]["snapshot_id"] == "test-snapshot"


def test_release_confirms_absence_before_destroy_event(monkeypatch):
    value = manager()
    handle = RunnerHandle("", "", "burn", VM)
    request = Mock(
        side_effect=[
            {"instance": {"tags": [value.owner_tag, "airlock-burn"]}},
            {},
            {"instance": {"status": "active"}},
            None,
        ]
    )
    monkeypatch.setattr(value, "_request", request)
    events = value.release(handle)
    assert request.call_count == 4
    assert events[0]["detail"]["confirmed"] is True
    assert events[0]["detail"]["id"] == VM


def test_release_failure_or_foreign_vm_never_reports_destroyed(monkeypatch):
    value = manager()
    handle = RunnerHandle("", "", "burn", VM)
    monkeypatch.setattr(
        value, "_request", Mock(return_value={"instance": {"tags": ["someone-else"]}})
    )
    with pytest.raises(FleetError, match="ownership"):
        value.release(handle)
    monkeypatch.setattr(
        value, "_request", Mock(side_effect=FleetError("API unavailable"))
    )
    with pytest.raises(FleetError):
        value.release(handle)


def test_already_deleted_vm_is_idempotent_and_destroy_false_does_not_emit(monkeypatch):
    value = manager()
    handle = RunnerHandle("", "", "burn", VM)
    monkeypatch.setattr(value, "_request", Mock(return_value=None))
    assert value.release(handle)[0]["detail"]["confirmed"] is True
    assert value.release(handle, False) == []


def test_provisioning_failure_deletes_the_exact_created_instance(monkeypatch):
    value = manager()
    request = Mock(side_effect=[{"instances": []}, {"instance": {"id": VM}}])
    monkeypatch.setattr(value, "_request", request)
    monkeypatch.setattr(
        value, "_wait_ready", Mock(side_effect=FleetError("Readiness timeout"))
    )
    cleanup = Mock()
    monkeypatch.setattr(value, "_delete_confirmed", cleanup)
    with pytest.raises(FleetError, match="Readiness timeout"):
        value.acquire("burn", "job-test")
    cleanup.assert_called_once_with(VM)


def test_quota_prevents_creating_an_extra_billed_vm(monkeypatch):
    value = manager()
    monkeypatch.setattr(value, "_instances", Mock(return_value=[{}, {}]))
    request = Mock()
    monkeypatch.setattr(value, "_request", request)
    with pytest.raises(FleetError, match="concurrency"):
        value.acquire("burn", "job-test")
    request.assert_not_called()


def test_unconfirmed_deletion_raises_without_success_event(monkeypatch):
    value = manager()
    value.timeout = 0
    request = Mock(
        return_value={"instance": {"tags": [value.owner_tag, "airlock-burn"]}}
    )
    monkeypatch.setattr(value, "_request", request)
    with pytest.raises(FleetError, match="Deletion unconfirmed"):
        value.release(RunnerHandle("", "", "burn", VM))
    assert request.call_args.args == ("DELETE", f"/instances/{VM}")


def test_no_healthy_runner_is_accepted_on_a_public_or_wrong_vpc_ip(monkeypatch):
    value = manager()
    value.timeout = 0.002

    def request(method, path, payload=None):
        if path.endswith("/vpcs"):
            return {"vpcs": [{"id": "foreign-vpc", "ip_address": "10.0.0.9"}]}
        return {
            "instance": {
                "status": "active",
                "power_status": "running",
                "server_status": "ok",
                "internal_ip": "10.0.0.8",
            }
        }

    monkeypatch.setattr(value, "_request", request)
    probe = Mock(return_value=True)
    monkeypatch.setattr(value, "_probe_runner", probe)
    with pytest.raises(FleetError, match="timed out"):
        value._wait_ready(VM)
    probe.assert_not_called()
