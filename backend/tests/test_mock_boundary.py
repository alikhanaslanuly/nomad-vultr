import pytest

from app.config import settings
from app.runner_client_stub import RunnerStub
from app.runner_factory import get_runner_for


def test_missing_runner_configuration_never_falls_back_to_mock(monkeypatch):
    monkeypatch.setattr(settings, "USE_STUB_RUNNER", False)
    monkeypatch.setattr(settings, "RUNNER_URL", "")
    monkeypatch.setattr(settings, "RUNNER_TOKEN", "")
    with pytest.raises(RuntimeError, match="implicit mock fallback is forbidden"):
        get_runner_for("standard", "unit-test")


async def test_mock_runner_rejects_source_keyword_guessing():
    runner = RunnerStub()
    with pytest.raises(ValueError, match="named team sample"):
        await runner.start_run(
            {
                "run_id": "unit-test",
                "files": [{"path": "evil-installer.sh", "content_b64": "Y3VybA=="}],
            }
        )
    state = await runner.healthz()
    assert (
        state["mode"] == "mock"
        and state["observer_verified"] is False
        and state["ok"] is False
    )


def test_burn_cannot_silently_use_stub_or_standard_runner(monkeypatch):
    monkeypatch.setattr(settings, "USE_STUB_RUNNER", True)
    with pytest.raises(RuntimeError, match="simulated"):
        get_runner_for("burn", "unit-test")
