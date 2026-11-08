import json
import re
import sys
import time
from urllib import parse, request


PLACEHOLDERS = (
    "airlock-runner-token",
    "vultr-inference-api-key",
    "airlock-secret-receipt-key-change-me",
    "airlock-admin-secret-token",
    "airlock_secure_password",
    "changeme",
    "change-me",
    "change_me",
    "replace-me",
    "replace_me",
    "your-secret",
    "your_secret",
    "placeholder",
)


def valid_config(config):
    if not isinstance(config, dict) or not isinstance(config.get("services"), dict):
        return False
    environments = {}
    for name, service in config["services"].items():
        if not isinstance(service, dict):
            return False
        environment = service.get("environment") or {}
        if not isinstance(environment, dict):
            return False
        environments[name] = environment
        for value in environment.values():
            if isinstance(value, str) and (
                any(marker in value.lower() for marker in PLACEHOLDERS)
                or re.search(r"<[^>]+>", value)
            ):
                return False
    backend = environments.get("backend", {})
    postgres = environments.get("postgres", {})
    required = (
        backend.get("RUNNER_URL"),
        backend.get("RUNNER_TOKEN"),
        backend.get("RECEIPT_SIGNING_KEY"),
        postgres.get("POSTGRES_PASSWORD"),
    )
    if not all(isinstance(value, str) and value.strip() for value in required):
        return False
    if str(backend.get("USE_STUB_RUNNER", "")).lower() not in {"0", "false", "no"}:
        return False
    try:
        runner_url = parse.urlsplit(backend["RUNNER_URL"])
        return (
            runner_url.scheme in {"http", "https"}
            and bool(runner_url.hostname)
            and runner_url.username is None
            and runner_url.password is None
            and not runner_url.query
            and not runner_url.fragment
        )
    except ValueError:
        return False


def live_health(health):
    return (
        isinstance(health, dict)
        and health.get("ok") is True
        and health.get("mode") == "live"
        and health.get("runner") == "up"
        and health.get("observer_verified") is True
    )


def wait_for_health(timeout=120.0, interval=2.0):
    deadline = time.monotonic() + timeout
    opener = request.build_opener(request.ProxyHandler({}))
    while True:
        try:
            with opener.open(
                "http://127.0.0.1:8000/api/health", timeout=20
            ) as response:
                if live_health(json.load(response)):
                    return True
        except (OSError, ValueError, TypeError, UnicodeError):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(interval, remaining))


def main():
    if sys.argv[1:] == ["config"]:
        try:
            return 0 if valid_config(json.load(sys.stdin)) else 1
        except (OSError, ValueError, TypeError):
            return 1
    if sys.argv[1:] == ["health"]:
        return 0 if wait_for_health() else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
