import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts" / "events.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)
MOCK_DIR = ROOT / "contracts" / "mock"


@pytest.mark.parametrize("name", [
    "events_evil-installer.ndjson",
    "events_benign-csv-tool.ndjson",
    "events_readme-lies.ndjson",
])
def test_mock_events_valid(name):
    for line in (MOCK_DIR / name).read_text().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        ev.pop("delay_ms", None)  # test-only field
        VALIDATOR.validate(ev)


def test_schema_rejects_unknown_kind():
    bad = {"id": "x", "seq": 1, "ts": "2026-11-07T09:00:00.000Z",
           "kind": "not_a_kind", "severity": "info",
           "observer": "runner", "source": "host", "detail": {}}
    with pytest.raises(Exception):
        VALIDATOR.validate(bad)