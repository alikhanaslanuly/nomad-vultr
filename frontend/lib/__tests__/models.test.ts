import { describe, expect, it } from "vitest";
import { createJobSchema, eventSchema, jobSchema, reportSchema } from "../models";
import { buildFixture } from "../mock/fixtures";

const fixture = buildFixture("evil-installer", "job-test", ["ci"], 0);
describe("contract validation", () => {
  it("accepts backend job lifecycle states and requires a timestamp offset", () => {
    const job = {
      job_id: "job-test",
      status: "queued",
      stage: "queued",
      verdict: null,
      tier: "standard",
      created_at: "2026-11-08T22:52:17.786115Z",
    };
    for (const stage of ["queued", "error", "killed", "verdict"])
      expect(jobSchema.safeParse({ ...job, stage }).success).toBe(true);
    expect(
      jobSchema.safeParse({ ...job, created_at: "2026-11-08T22:52:17.786115" })
        .success,
    ).toBe(false);
    expect(jobSchema.safeParse({ ...job, stage: "unknown" }).success).toBe(false);
  });
  it("accepts every local fixture event and report without optional invented fields", () => {
    for (const event of fixture.events)
      expect(eventSchema.safeParse(event).success).toBe(true);
    expect(reportSchema.safeParse(fixture.report).success).toBe(true);
    expect(
      fixture.events.find((event) => event.kind === "agent")?.detail,
    ).not.toHaveProperty("tokens_in");
  });
  it("rejects sandbox sources and LLM canary claims", () => {
    const canary = fixture.events.find((event) => event.kind === "canary");
    expect(eventSchema.safeParse({ ...canary, source: "sandbox" }).success).toBe(false);
    expect(eventSchema.safeParse({ ...canary, observer: "llm" }).success).toBe(false);
    expect(eventSchema.safeParse({ ...canary, source: "orchestrator" }).success).toBe(
      false,
    );
    expect(eventSchema.safeParse({ ...canary, severity: "info" }).success).toBe(false);
  });
  it("rejects out-of-range risk and reversed source ranges", () => {
    expect(reportSchema.safeParse({ ...fixture.report, risk_score: 101 }).success).toBe(
      false,
    );
    expect(
      reportSchema.safeParse({
        ...fixture.report,
        findings: [
          {
            ...fixture.report.findings[0],
            code_ref: { file: "x", line_start: 5, line_end: 2 },
          },
        ],
      }).success,
    ).toBe(false);
  });
  it("strips unknown fields while preserving terminal run stages", () => {
    const terminal = fixture.events.find(
      (event) =>
        event.kind === "stage" && event.detail.name === "run" && event.run_id !== null,
    );
    const parsed = eventSchema.parse({ ...terminal, unexpected: "ignored" });
    expect(parsed).not.toHaveProperty("unexpected");
    expect(parsed.kind).toBe("stage");
  });
  it("requires nonempty input and unique environment profiles", () => {
    const input = {
      input_type: "paste",
      content: "text",
      profiles: ["ci"],
      tier: "standard",
    };
    expect(createJobSchema.safeParse(input).success).toBe(true);
    expect(createJobSchema.safeParse({ ...input, content: " " }).success).toBe(false);
    expect(createJobSchema.safeParse({ ...input, profiles: ["ci", "ci"] }).success).toBe(
      false,
    );
    expect(
      createJobSchema.safeParse({ ...input, content: "x".repeat(200001) }).success,
    ).toBe(false);
  });
});
