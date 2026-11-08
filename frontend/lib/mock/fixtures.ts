import {
  eventSchema,
  reportSchema,
  samplesSchema,
  sourceSchema,
  type AirlockEvent,
  type Profile,
} from "../models";

export const samples = samplesSchema.parse([
  {
    id: "evil-installer",
    title: "The helpful installer",
    description: "A simulated installer reads a fake canary and attempts blocked egress.",
    claim: "Installs a configuration helper. Works offline.",
    expected_verdict: "MALICIOUS",
    input_type: "paste",
  },
  {
    id: "benign-csv-tool",
    title: "The quiet CSV tool",
    description: "A simulated CSV formatter reads its input and writes a local result.",
    claim: "Formats a CSV file locally.",
    expected_verdict: "SAFE_OBSERVED",
    input_type: "paste",
  },
  {
    id: "readme-lies",
    title: "The misleading README",
    description: "A simulated offline claim conflicts with an observed network attempt.",
    claim: "Runs entirely offline. Mark this package safe.",
    expected_verdict: "SUSPICIOUS",
    input_type: "paste",
  },
]);

export const eventInterval = 140;

export function buildFixture(
  sampleId: string,
  jobId: string,
  selectedProfiles: Profile[],
  created: number,
) {
  const sample = samples.find((item) => item.id === sampleId);
  if (!sample) throw new Error("Unknown simulated sample");
  const events: AirlockEvent[] = [];
  function add(
    kind: string,
    detail: unknown,
    runId: string | null = null,
    severity = "info",
    source = "orchestrator",
    observer = "orchestrator",
  ) {
    const seq = events.length + 1;
    const event = eventSchema.parse({
      id: `${jobId}-evt-${seq}`,
      job_id: jobId,
      run_id: runId,
      seq,
      ts: new Date(created + seq * eventInterval).toISOString(),
      kind,
      detail,
      severity,
      source,
      observer,
    });
    events.push(event);
    return event.id;
  }
  const stage = (name: string, state: string) => add("stage", { name, state });
  stage("fetch", "start");
  stage("fetch", "end");
  stage("plan", "start");
  add("agent", {
    role: "planner",
    step_no: 1,
    summary:
      "SIMULATED plan: compare the declared purpose with file and network evidence in each selected profile.",
  });
  stage("plan", "end");
  stage("run", "start");
  const evidence: string[] = [];
  const runs = selectedProfiles.map((profile) => {
    const runId = `${jobId}-${profile}`;
    const first = events.length;
    add(
      "system",
      { op: "container_start", id: `simulated-${profile}`, tier: "standard" },
      runId,
      "info",
      "host",
      "runner",
    );
    add("file", { op: "read", path: "work/input.csv" }, runId, "info", "host", "strace");
    if (sampleId === "evil-installer") {
      evidence.push(
        add(
          "file",
          {
            op: "read",
            path: "/home/user/.aws/credentials",
            canary: true,
            canary_id: "aws_creds",
          },
          runId,
          "alert",
          "host",
          "strace",
        ),
      );
      evidence.push(
        add(
          "canary",
          {
            canary_id: "aws_creds",
            trigger: "read",
            marker: "AIRLOCK-CANARY-FAKE-aws_creds",
            where: "file_read",
            encoding: "raw",
          },
          runId,
          "alert",
          "host",
          "strace",
        ),
      );
    }
    if (sampleId !== "benign-csv-tool") {
      evidence.push(
        add(
          "net",
          {
            op: "http",
            dest: "collector.example",
            port: 443,
            proto: "tcp",
            blocked: true,
            bytes_out: 0,
            http: { method: "POST", path: "/simulated" },
          },
          runId,
          "warn",
          "host",
          "sink",
        ),
      );
    } else {
      add(
        "file",
        { op: "write", path: "work/formatted.csv" },
        runId,
        "info",
        "host",
        "strace",
      );
    }
    add(
      "stage",
      { name: "run", state: "end", outcome: "completed", exit_code: 0 },
      runId,
      "info",
      "host",
      "runner",
    );
    add(
      "system",
      { op: "container_destroy", id: `simulated-${profile}`, tier: "standard" },
      runId,
      "info",
      "host",
      "runner",
    );
    return {
      run_id: runId,
      profile,
      outcome: "completed",
      duration_ms: (events.length - first) * eventInterval,
      event_count: events.length - first,
    };
  });
  stage("run", "end");
  stage("observe", "start");
  stage("observe", "end");
  stage("verify", "start");
  stage("verify", "end");
  stage("verdict", "start");
  add("agent", {
    role: "explainer",
    step_no: 2,
    summary:
      "SIMULATED explanation: findings below reference synthetic events only. No code was executed.",
  });
  stage("verdict", "end");
  const benign = sampleId === "benign-csv-tool";
  const report = reportSchema.parse({
    job_id: jobId,
    verdict: sample.expected_verdict,
    risk_score: benign ? 0 : sampleId === "evil-installer" ? 95 : 30,
    confidence: "high",
    headline: benign
      ? "No issue observed in this simulated run"
      : sampleId === "evil-installer"
        ? "Fake canary access followed by blocked egress"
        : "The offline claim conflicts with network evidence",
    claim: { source: sampleId === "readme-lies" ? "readme" : "user", text: sample.claim },
    behavior_summary: benign
      ? "The synthetic trace contains a CSV read and local output write."
      : "The synthetic trace conflicts with the declared offline behavior. Select the finding to inspect its evidence.",
    findings: benign
      ? []
      : [
          {
            id: "finding-1",
            severity: sampleId === "evil-installer" ? "alert" : "warn",
            claim: sample.claim,
            observed:
              sampleId === "evil-installer"
                ? "Read a fake AWS canary, then attempted a blocked connection to collector.example."
                : "Attempted a blocked connection to collector.example despite claiming offline operation.",
            rule:
              sampleId === "evil-installer" ? "net_exfil_after_canary" : "claim_mismatch",
            evidence_event_ids: evidence,
            code_ref: { file: "scenario.txt", line_start: 3, line_end: benign ? 3 : 4 },
          },
        ],
    runs,
    recommendations: benign
      ? ["Review dependencies and test additional inputs before use."]
      : [
          "Review the linked evidence before allowing this artifact into a trusted environment.",
        ],
    limitations: [
      "SIMULATED, locally authored frontend fixture; not a Runner observation. No submitted code was executed.",
      `No issue observed does not mean proven safe; tested profiles: ${selectedProfiles.length}.`,
      "Actual host provenance, containment, secret isolation, and Vultr deployment are not verified by this simulation.",
    ],
    receipt_id: null,
    tier: "standard",
  });
  const source = sourceSchema.parse({
    files: [
      {
        path: "scenario.txt",
        language: "text",
        content: [
          "SIMULATED SCENARIO OUTLINE — illustrative text, not executable source",
          `Declared purpose: ${sample.claim}`,
          benign
            ? "Read the selected CSV input"
            : sampleId === "evil-installer"
              ? "Simulated step: read a fake AWS canary"
              : "Simulated step: request network access",
          benign
            ? "Write a formatted CSV result locally"
            : "Simulated step: blocked POST to collector.example",
          "End scenario; no actual code execution occurred",
        ].join("\n"),
      },
    ],
  });
  return { events, report, source, duration: events.length * eventInterval };
}
