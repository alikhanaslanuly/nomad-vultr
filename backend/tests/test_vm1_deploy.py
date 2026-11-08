import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
FAKE_SECRET = "FAKE-DEPLOYMENT-SECRET-DO-NOT-PRINT"


@pytest.fixture
def deployment(tmp_path):
    infra = tmp_path / "infra"
    infra.mkdir()
    for name in ("vm1_deploy.sh", "vm1_deploy_check.py", "compose.vm1.yml"):
        shutil.copyfile(ROOT / "infra" / name, infra / name)
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"RUNNER_TOKEN={FAKE_SECRET}\nCOMPOSE_PROJECT_NAME=existing-airlock\n"
    )
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    (executable_dir / "python3").symlink_to(sys.executable)
    docker = executable_dir / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import io, json, os, sys, time, types, urllib.request\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['FAKE_DOCKER_LOG'], 'a') as log:\n"
        "    log.write(json.dumps(args) + '\\n')\n"
        "if args == ['info']:\n"
        "    sys.exit(int(os.environ.get('FAKE_DOCKER_UNAVAILABLE', '0')))\n"
        "if args == ['compose', 'version']:\n"
        "    sys.exit(int(os.environ.get('FAKE_COMPOSE_UNAVAILABLE', '0')))\n"
        "if args[:3] != ['compose', '-f', 'infra/compose.vm1.yml']:\n"
        "    sys.exit(2)\n"
        "operation = args[3:]\n"
        "if operation == ['config', '--format', 'json']:\n"
        "    if os.environ.get('FAKE_INVALID_COMPOSE'):\n"
        "        print(os.environ['FAKE_COMPOSE_CONFIG'], file=sys.stderr)\n"
        "        sys.exit(1)\n"
        "    print(os.environ['FAKE_COMPOSE_CONFIG'])\n"
        "elif operation in [['build'], ['up', '-d']]:\n"
        "    failure = 'FAKE_BUILD_FAILURE' if operation == ['build'] else 'FAKE_UP_FAILURE'\n"
        "    sys.exit(int(os.environ.get(failure, '0')))\n"
        "elif operation == ['exec', '-T', 'backend', 'python', '-', 'health']:\n"
        "    source = sys.stdin.read()\n"
        "    payload = os.environ['FAKE_API_HEALTH'].encode()\n"
        "    urllib.request.build_opener = lambda *a: types.SimpleNamespace(open=lambda *a, **k: io.BytesIO(payload))\n"
        "    clock = iter([0.0, 121.0])\n"
        "    time.monotonic = lambda: next(clock, 121.0)\n"
        "    time.sleep = lambda seconds: None\n"
        "    sys.argv = ['-', 'health']\n"
        "    exec(compile(source, '<backend-health-check>', 'exec'), {'__name__': '__main__'})\n"
        "else:\n"
        "    sys.exit(2)\n"
    )
    docker.chmod(0o755)
    config = {
        "services": {
            "backend": {
                "environment": {
                    "RUNNER_URL": "http://10.77.0.10:9000",
                    "RUNNER_TOKEN": FAKE_SECRET,
                    "RECEIPT_SIGNING_KEY": FAKE_SECRET,
                    "USE_STUB_RUNNER": "0",
                    "INFERENCE_API_KEY": "",
                }
            },
            "postgres": {"environment": {"POSTGRES_PASSWORD": FAKE_SECRET}},
        }
    }
    health = {
        "ok": True,
        "mode": "live",
        "runner": "up",
        "observer_verified": True,
        "inference": "down",
        "error": FAKE_SECRET,
    }
    environment = {
        "PATH": f"{executable_dir}:/usr/bin:/bin",
        "FAKE_DOCKER_LOG": str(tmp_path / "docker.jsonl"),
        "FAKE_COMPOSE_CONFIG": json.dumps(config),
        "FAKE_API_HEALTH": json.dumps(health),
    }

    def run():
        result = subprocess.run(
            ["bash", str(infra / "vm1_deploy.sh")],
            cwd=tmp_path,
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert FAKE_SECRET not in result.stdout + result.stderr
        log_file = Path(environment["FAKE_DOCKER_LOG"])
        commands = (
            [json.loads(line) for line in log_file.read_text().splitlines()]
            if log_file.exists()
            else []
        )
        return result, [
            command[3:]
            for command in commands
            if command[:3] == ["compose", "-f", "infra/compose.vm1.yml"]
        ]

    return env_file, environment, config, health, run


def test_missing_env_is_not_created(deployment):
    env_file, _, _, _, run = deployment
    env_file.unlink()
    result, commands = run()
    assert result.returncode != 0
    assert "existing .env is required" in result.stderr
    assert not env_file.exists()
    assert commands == []


@pytest.mark.parametrize(
    "missing",
    ["RUNNER_URL", "RUNNER_TOKEN", "RECEIPT_SIGNING_KEY", "POSTGRES_PASSWORD"],
)
def test_missing_effective_configuration_prevents_build(deployment, missing):
    _, environment, config, _, run = deployment
    for service in config["services"].values():
        service["environment"].pop(missing, None)
    environment["FAKE_COMPOSE_CONFIG"] = json.dumps(config)
    result, commands = run()
    assert result.returncode != 0
    assert "configuration is invalid" in result.stderr
    assert commands == [["config", "--format", "json"]]


@pytest.mark.parametrize(
    "placeholder",
    [
        "airlock-runner-token",
        "airlock_secure_password",
        "<YOUR_SECRET_RUNNER_TOKEN>",
        "change-me",
    ],
)
def test_placeholder_configuration_prevents_build(deployment, placeholder):
    _, environment, config, _, run = deployment
    config["services"]["backend"]["environment"]["RUNNER_TOKEN"] = placeholder
    environment["FAKE_COMPOSE_CONFIG"] = json.dumps(config)
    result, commands = run()
    assert result.returncode != 0
    assert "placeholder values are forbidden" in result.stderr
    assert commands == [["config", "--format", "json"]]
    assert placeholder not in result.stdout + result.stderr


def test_compose_configuration_errors_do_not_expose_values(deployment):
    _, environment, _, _, run = deployment
    environment["FAKE_INVALID_COMPOSE"] = "1"
    result, commands = run()
    assert result.returncode != 0
    assert "configuration is invalid" in result.stderr
    assert commands == [["config", "--format", "json"]]


@pytest.mark.parametrize(
    "runner_url",
    [
        f"http://{FAKE_SECRET}@10.77.0.10:9000",
        f"http://user:{FAKE_SECRET}@10.77.0.10:9000",
        f"http://10.77.0.10:9000?token={FAKE_SECRET}",
        f"http://10.77.0.10:9000#{FAKE_SECRET}",
    ],
)
def test_runner_url_rejects_userinfo_query_and_fragment(deployment, runner_url):
    _, environment, config, _, run = deployment
    config["services"]["backend"]["environment"]["RUNNER_URL"] = runner_url
    environment["FAKE_COMPOSE_CONFIG"] = json.dumps(config)
    result, commands = run()
    assert result.returncode != 0
    assert "configuration is invalid" in result.stderr
    assert commands == [["config", "--format", "json"]]


@pytest.mark.parametrize(
    "failure", ["FAKE_DOCKER_UNAVAILABLE", "FAKE_COMPOSE_UNAVAILABLE"]
)
def test_missing_prerequisites_prevent_build(deployment, failure):
    _, environment, _, _, run = deployment
    environment[failure] = "1"
    result, commands = run()
    assert result.returncode != 0
    assert commands == []
    assert "required" in result.stderr or "must be available" in result.stderr


@pytest.mark.parametrize("failure", ["FAKE_BUILD_FAILURE", "FAKE_UP_FAILURE"])
def test_failed_build_or_start_never_reports_success(deployment, failure):
    _, environment, _, _, run = deployment
    environment[failure] = "1"
    result, commands = run()
    assert result.returncode != 0
    assert "Backend API verified" not in result.stdout
    assert not any(command[0] == "exec" for command in commands)


@pytest.mark.parametrize(
    "changes",
    [
        {"runner": "down"},
        {"mode": "mock"},
        {"observer_verified": False},
        {"observer_verified": "true"},
        {"ok": False},
        {"mode": None, "observer_verified": None},
    ],
)
def test_unverified_health_never_reports_success(deployment, changes):
    _, environment, _, health, run = deployment
    health.update(changes)
    environment["FAKE_API_HEALTH"] = json.dumps(health)
    result, commands = run()
    assert result.returncode != 0
    assert "Backend API verification failed" in result.stderr
    assert "Backend API verified" not in result.stdout
    assert commands[-1] == ["exec", "-T", "backend", "python", "-", "health"]


def test_success_preserves_config_and_project_without_requiring_inference(deployment):
    env_file, _, _, _, run = deployment
    original = env_file.read_bytes()
    result, commands = run()
    assert result.returncode == 0, result.stderr
    assert "Backend API verified from the backend container" in result.stdout
    assert env_file.read_bytes() == original
    assert commands == [
        ["config", "--format", "json"],
        ["build"],
        ["up", "-d"],
        ["exec", "-T", "backend", "python", "-", "health"],
    ]


def test_health_retries_invalid_response_until_verified(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "vm1_deploy_check", ROOT / "infra" / "vm1_deploy_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    replies = iter(
        [
            b"invalid-json",
            b'{"ok":true,"mode":"live","runner":"up","observer_verified":true}',
        ]
    )
    calls = []
    proxy_settings = []

    def urlopen(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(next(replies))

    def build_opener(proxy_handler):
        proxy_settings.append(proxy_handler.proxies)
        return SimpleNamespace(open=urlopen)

    monkeypatch.setattr(module.request, "build_opener", build_opener)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    assert module.wait_for_health(timeout=1)
    assert len(calls) == 2
    assert proxy_settings == [{}]
    assert all(url == "http://127.0.0.1:8000/api/health" for url, _ in calls)
