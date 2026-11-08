import asyncio
import base64
import json
from runner.models import RunManifest, FileSpec
from runner.executor import SandboxExecutor

async def test_evil_installer_execution():
    with open("fixtures/evil-installer/install.sh", "r", encoding="utf-8") as f:
        script_content = f.read()

    manifest = RunManifest(
        run_id="run_test_evil_installer",
        profile="dev-laptop",
        entrypoint=["bash", "work/artifact/install.sh"],
        files=[
            FileSpec(
                path="work/artifact/install.sh",
                content_b64=base64.b64encode(script_content.encode("utf-8")).decode("utf-8")
            )
        ]
    )

    executor = SandboxExecutor(manifest)
    summary = await executor.execute()
    print("Summary:", summary)

    events = executor.observer.events
    print(f"Total events emitted: {len(events)}")
    kinds = [e["kind"] for e in events]
    print(f"Event kinds: {kinds}")

    # Assertions
    assert "stage" in kinds
    assert "system" in kinds
    assert "canary" in kinds, "Canary trigger event must be emitted"
    assert "net" in kinds, "Outbound network blocked event must be emitted"

    canary_events = [e for e in events if e["kind"] == "canary"]
    print("Canary events details:", [e["detail"] for e in canary_events])

    # Check that sequence is monotonic without gaps
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(events) + 1)), "Sequence numbers must be strictly monotonic without gaps"

    # Final event must be stage run end
    last_event = events[-1]
    assert last_event["kind"] == "stage"
    assert last_event["detail"]["name"] == "run"
    assert last_event["detail"]["state"] == "end"

    print("Evil installer test completed successfully!")
    return events

if __name__ == "__main__":
    asyncio.run(test_evil_installer_execution())

