import assert from "node:assert/strict";
import { createRealApi } from "../../frontend/lib/real-api";
import { isTerminal } from "../../frontend/lib/sse";
import type { AirlockEvent } from "../../frontend/lib/models";
import { containsSecretSentinel } from "../../frontend/test-support/secret-scan";

async function main() {
  const base = process.env.AIRLOCK_STAGING_API;
  if (!base) {
    process.stdout.write(
      "SKIPPED real API integration: AIRLOCK_STAGING_API is not explicitly configured.\n",
    );
    return;
  }
  const url = new URL(base);
  assert(
    url.protocol === "https:" ||
      (url.protocol === "http:" &&
        ["localhost", "127.0.0.1"].includes(url.hostname)),
    "Use HTTPS staging or explicit loopback HTTP",
  );
  assert(
    !url.username && !url.password && !url.search && !url.hash,
    "Staging URL must not contain credentials or query parameters",
  );
  const sentinels: unknown = process.env.AIRLOCK_SECRET_SENTINELS
    ? JSON.parse(process.env.AIRLOCK_SECRET_SENTINELS)
    : [];
  assert(
    Array.isArray(sentinels) &&
      sentinels.every(
        (value: unknown) => typeof value === "string" && value.length >= 8,
      ),
    "Secret sentinels must be a JSON array of strings of at least eight characters",
  );
  const knownSecrets = sentinels as string[];
  const checkSecrets = (payload: unknown) => {
    assert(
      !containsSecretSentinel(payload, knownSecrets),
      "Secret sentinel detected in API output; values redacted",
    );
  };
  const api = createRealApi(base);
  const samples = await api.listSamples(AbortSignal.timeout(15000));
  checkSecrets(samples);
  for (const id of ["evil-installer", "benign-csv-tool", "readme-lies"]) {
    const sample = samples.find((item) => item.id === id);
    assert(sample, "A required team sample is unavailable");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 180000);
    try {
      const created = await api.runSample(
        id,
        { profiles: ["dev-laptop", "ci"], tier: "standard" },
        controller.signal,
      );
      checkSecrets(created);
      const events: AirlockEvent[] = [];
      await api.streamEvents(created.job_id, {
        signal: controller.signal,
        onEvent: (event) => {
          assert(
            event.source === "host" || event.source === "orchestrator",
            "Invalid event provenance field",
          );
          if (["file", "proc", "net", "canary", "limit"].includes(event.kind))
            assert(
              event.source === "host",
              "Behavioral evidence must carry host source",
            );
          checkSecrets(event);
          events.push(event);
        },
        onState: () => undefined,
      });
      assert(
        events.some(isTerminal),
        "Stream did not complete with a verdict event",
      );
      const job = await api.getJob(created.job_id, controller.signal);
      checkSecrets(job);
      assert.equal(job.status, "done", "Job did not complete");
      const report = await api.getReport(created.job_id, controller.signal);
      const source = await api.getSource(created.job_id, controller.signal);
      checkSecrets(report);
      checkSecrets(source);
      assert.equal(report.job_id, job.job_id, "Report identity mismatch");
      assert.equal(
        report.verdict,
        sample.expected_verdict,
        "Unexpected team sample verdict",
      );
      assert.equal(job.verdict, report.verdict, "Job/report verdict mismatch");
      assert(report.limitations.length > 0, "Report limitations missing");
      for (const finding of report.findings) {
        assert(
          finding.evidence_event_ids.every((eventId) =>
            events.some((event) => event.id === eventId),
          ),
          "Finding references unavailable events",
        );
        if (finding.code_ref) {
          const range = finding.code_ref;
          const file = source.files.find((item) => item.path === range.file);
          assert(
            file && file.content.split("\n").length >= range.line_end,
            "Finding source reference unavailable",
          );
        }
      }
      process.stdout.write(`PASSED staging sample: ${id}\n`);
    } finally {
      clearTimeout(timeout);
      controller.abort();
    }
  }
  if (!knownSecrets.length)
    process.stdout.write(
      "SKIPPED sentinel comparison: AIRLOCK_SECRET_SENTINELS not configured.\n",
    );
  process.stdout.write(
    "LIMITATION: frontend output checks cannot independently prove runner filesystem/env secret isolation or host provenance. Backend/runner owners must verify both.\n",
  );
}

main().catch(() => {
  process.stderr.write(
    "FAILED real API integration. Details withheld to avoid exposing untrusted output or secret sentinels.\n",
  );
  process.exitCode = 1;
});
