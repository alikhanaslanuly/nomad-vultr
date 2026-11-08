import type { AirlockApi } from "../api-types";
import { ApiError } from "../errors";
import { jobSchema, type Profile } from "../models";
import { delay } from "../sse";
import { buildFixture, eventInterval, samples } from "./fixtures";

export function createMockApi(): AirlockApi {
  const jobs = new Map<
    string,
    { sample: string; profiles: Profile[]; created: number }
  >();
  const unavailable = async (): Promise<never> => {
    throw new ApiError(
      "unavailable_in_mock",
      "Unavailable in simulation. Connect the real backend for this operation.",
    );
  };
  const locate = (id: string) => {
    const existing = jobs.get(id);
    if (existing) return existing;
    const match =
      /^mock-(evil-installer|benign-csv-tool|readme-lies)__(dev-laptop|ci|dev-laptop\.ci)$/.exec(
        id,
      );
    if (!match) throw new ApiError("not_found", "Simulated job not found.", 404);
    const entry = {
      sample: match[1],
      profiles: match[2].split(".") as Profile[],
      created: Date.now(),
    };
    jobs.set(id, entry);
    return entry;
  };
  const fixture = (id: string) => {
    const entry = locate(id);
    return buildFixture(entry.sample, id, entry.profiles, entry.created);
  };
  const getJob: AirlockApi["getJob"] = async (id, signal) => {
    signal?.throwIfAborted();
    const entry = locate(id);
    const data = fixture(id);
    const elapsed = Date.now() - entry.created;
    const done = elapsed >= data.duration;
    const progress = data.events
      .filter((event) => event.seq * eventInterval <= elapsed && event.kind === "stage")
      .at(-1);
    return jobSchema.parse({
      job_id: id,
      status: done ? "done" : "running",
      stage: progress?.kind === "stage" ? progress.detail.name : "fetch",
      verdict: done ? data.report.verdict : null,
      risk_score: done ? data.report.risk_score : null,
      tier: "standard",
      created_at: new Date(entry.created).toISOString(),
      finished_at: done ? new Date(entry.created + data.duration).toISOString() : null,
    });
  };
  return {
    createJob: unavailable,
    getJob,
    async streamEvents(id, options) {
      options.onState("connecting");
      const entry = locate(id);
      const data = fixture(id);
      options.onState("connected");
      for (const event of data.events) {
        if (event.seq <= (options.afterSeq ?? 0)) continue;
        await delay(
          Math.max(0, entry.created + event.seq * eventInterval - Date.now()),
          options.signal,
        );
        options.onEvent(event);
      }
      options.onState("complete");
    },
    async getReport(id, signal) {
      if ((await getJob(id, signal)).status !== "done")
        throw new ApiError("not_ready", "Report is not ready yet.", 404);
      return fixture(id).report;
    },
    async getSource(id, signal) {
      signal?.throwIfAborted();
      return fixture(id).source;
    },
    verify: unavailable,
    getReceipt: unavailable,
    async listSamples(signal) {
      signal?.throwIfAborted();
      return samples;
    },
    async runSample(id, input, signal) {
      signal?.throwIfAborted();
      if (!samples.some((sample) => sample.id === id))
        throw new ApiError("not_found", "Sample unavailable.", 404);
      if (
        input.tier !== "standard" ||
        input.profiles.some((profile) => profile === "future-date") ||
        !input.profiles.length
      )
        return unavailable();
      const selected = (["dev-laptop", "ci"] as const).filter((profile) =>
        input.profiles.includes(profile),
      );
      const jobId = `mock-${id}__${selected.join(".")}`;
      jobs.set(jobId, { sample: id, profiles: selected, created: Date.now() });
      return { job_id: jobId };
    },
    async listJobs(signal) {
      signal?.throwIfAborted();
      return Promise.all([...jobs.keys()].map((id) => getJob(id, signal)));
    },
  };
}
