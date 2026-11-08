import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { apiUrl, post, request } from "../http";
import { errorMessage, httpError } from "../errors";
import { createRealApi } from "../real-api";

afterEach(() => vi.unstubAllGlobals());
describe("API boundary", () => {
  it("joins a production /api prefix exactly once", () => {
    expect(apiUrl("/api/", "/api/jobs")).toBe("/api/jobs");
    expect(apiUrl("https://staging.example/api", "jobs/x")).toBe(
      "https://staging.example/api/jobs/x",
    );
    expect(apiUrl("/api", "jobs/a%2Fb")).toBe("/api/jobs/a%2Fb");
    expect(() => apiUrl("javascript:alert(1)", "jobs")).toThrow();
    expect(() => apiUrl("https://user:pass@example.com/api", "jobs")).toThrow();
  });
  it("normalizes errors without reflecting raw HTML or secret-bearing messages", () => {
    const error = httpError(403, {
      error: { code: "forbidden", message: "private-value <img src=x>" },
    });
    expect(errorMessage(error)).toContain("forbidden");
    expect(errorMessage(error)).not.toContain("private-value");
    expect(errorMessage(error)).not.toContain("<img");
  });
  it("validates successful payloads and reports non-JSON failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response('{"ok":true}'))
        .mockResolvedValueOnce(new Response("<html>secret</html>", { status: 502 })),
    );
    await expect(request("/api/health", z.object({ ok: z.boolean() }))).resolves.toEqual({
      ok: true,
    });
    await expect(request("/api/health", z.unknown())).rejects.toMatchObject({
      code: "invalid_json",
      status: 502,
    });
  });
  it("does not retry a non-idempotent job submission", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("Network failure"));
    vi.stubGlobal("fetch", fetcher);
    await expect(
      createRealApi("/api").createJob({
        input_type: "paste",
        content: "text",
        profiles: ["ci"],
        tier: "standard",
      }),
    ).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("sends encoded identifiers and the contract POST status", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response('{"job_id":"job-created"}', { status: 201 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(
      createRealApi("/api").createJob({
        input_type: "paste",
        content: "text",
        profiles: ["ci"],
        tier: "standard",
      }),
    ).resolves.toEqual({ job_id: "job-created" });
    expect(fetcher.mock.calls[0][0]).toBe("/api/jobs");
    expect(post({ text: "<script>" }).body).toBe('{"text":"<script>"}');
  });
  it("accepts the deployed sample 201 response and preserves uploaded filename", async () => {
    const fetcher = vi
      .fn()
      .mockImplementation(
        async () => new Response('{"job_id":"job-created"}', { status: 201 }),
      );
    vi.stubGlobal("fetch", fetcher);
    const api = createRealApi("/api");
    await expect(
      api.runSample("benign-csv-tool", { profiles: ["ci"], tier: "standard" }),
    ).resolves.toEqual({ job_id: "job-created" });
    await api.createJob({
      input_type: "paste",
      filename: "script.py",
      content: "print(1)",
      profiles: ["ci"],
      tier: "standard",
    });
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({
      filename: "script.py",
      input_type: "paste",
    });
  });
  it("rejects an unobserved history wrapper instead of fabricating jobs", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"items":[]}')));
    await expect(createRealApi("/api").listJobs()).rejects.toThrow();
  });
});
