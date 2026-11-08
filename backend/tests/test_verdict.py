import json
from pathlib import Path

from app.verdict import evaluate

MOCK = Path(__file__).resolve().parents[2] / "contracts" / "mock"


def _load(name: str) -> list[dict]:
    p = MOCK / name
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def test_evil_installer_is_malicious():
    events = _load("events_evil-installer.ndjson")
    verdict, score, findings = evaluate({"dev-laptop": events})
    assert verdict == "MALICIOUS"
    assert score >= 85
    rules = {f.rule for f in findings}
    assert "canary_read" in rules
    assert "net_exfil_after_canary" in rules or "exfil_marker_seen" in rules
    # every finding cites real events
    ids = {e["id"] for e in events}
    for f in findings:
        assert set(f.evidence_event_ids) <= ids


def test_benign_is_safe():
    events = _load("events_benign-csv-tool.ndjson")
    verdict, score, findings = evaluate({"dev-laptop": events})
    assert verdict == "SAFE_OBSERVED"
    assert score == 0
    assert findings == []


def test_readme_lies_is_suspicious():
    events = _load("events_readme-lies.ndjson")
    verdict, score, findings = evaluate({"dev-laptop": events})
    assert verdict == "SUSPICIOUS"
    rules = {f.rule for f in findings}
    assert "net_attempt" in rules


def test_env_gated_across_profiles():
    safe = _load("events_benign-csv-tool.ndjson")
    evil = _load("events_evil-installer.ndjson")
    verdict, score, findings = evaluate({"dev-laptop": safe, "ci": evil})
    rules = {f.rule for f in findings}
    assert verdict == "MALICIOUS"
    assert "env_gated" in rules


def test_empty_runs_error():
    verdict, score, findings = evaluate({})
    assert verdict == "ERROR"
    assert findings == []