import { afterEach, describe, expect, it, vi } from "vitest";
import {
  EventSequence,
  isTerminal,
  SseParser,
  streamSse,
  type StreamState,
} from "../sse";
import { buildFixture } from "../mock/fixtures";
import type { AirlockEvent } from "../models";

const fixture = buildFixture("benign-csv-tool", "job-sse", ["ci"], 0);
const event = fixture.events[0];
const terminal: AirlockEvent = { ...fixture.events.at(-1)!, seq: 2 };
function response(events: AirlockEvent[]) {
  return new Response(
    events
      .map((item) => `id: transport-${item.seq}\ndata: ${JSON.stringify(item)}\n\n`)
      .join(""),
    { headers: { "Content-Type": "text/event-stream" } },
  );
}
afterEach(() => vi.useRealTimers());
describe("stream framing and ordering", () => {
  it("handles every possible chunk boundary, multiline data, CRLF, ids, and heartbeat comments", () => {
    const frame =
      ': heartbeat\r\nid: frame-id\r\ndata: {"value":\r\ndata: "safe text"}\r\n\r\n';
    for (let boundary = 0; boundary < frame.length; boundary += 1) {
      const parser = new SseParser();
      const frames = [
        ...parser.push(frame.slice(0, boundary)),
        ...parser.push(frame.slice(boundary)),
      ];
      expect(frames).toEqual([{ id: "frame-id", data: '{"value":\n"safe text"}' }]);
    }
  });
  it("does not process an unterminated frame and bounds event memory", () => {
    expect(new SseParser().push("data: incomplete")).toEqual([]);
    expect(() => new SseParser().push("x".repeat(262145))).toThrow();
    expect(new SseParser().push("id: bad\0id\ndata: x\n\n")[0].id).toBeUndefined();
  });
  it("orders buffered events and deduplicates replayed job sequences", () => {
    const sequence = new EventSequence();
    expect(sequence.accept({ ...event, seq: 2 })).toEqual([]);
    expect(sequence.accept(event).map((item) => item.seq)).toEqual([1, 2]);
    expect(sequence.accept(event)).toEqual([]);
    expect(sequence.checkpoint).toBe(2);
  });
  it("does not confuse a terminal Runner stage with the final job verdict", () => {
    expect(isTerminal(event)).toBe(false);
    expect(isTerminal(terminal)).toBe(true);
    expect(
      isTerminal({ ...terminal, kind: "stage", detail: { name: "run", state: "end" } }),
    ).toBe(false);
  });
  it("accepts zero-based and sparse monotonic sequences without inventing missing events", async () => {
    const zero = { ...event, seq: 0 };
    expect(new EventSequence().accept(zero)).toEqual([zero]);
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      response([
        { ...event, seq: 17 },
        { ...terminal, seq: 21 },
      ]),
    );
    const received: number[] = [];
    await streamSse(
      "/events",
      "job-sse",
      {
        signal: new AbortController().signal,
        onEvent: (value) => received.push(value.seq),
        onState: vi.fn(),
      },
      fetcher,
    );
    expect(received).toEqual([17, 21]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("resumes after disconnect using the processed job-level seq, not a frame id", async () => {
    vi.useFakeTimers();
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response([event]))
      .mockResolvedValueOnce(response([event, terminal]));
    const received: AirlockEvent[] = [];
    const states: StreamState[] = [];
    const task = streamSse(
      "/api/jobs/job-sse/events",
      "job-sse",
      {
        signal: new AbortController().signal,
        onEvent: (value) => received.push(value),
        onState: (value) => states.push(value),
      },
      fetcher,
    );
    await vi.runAllTimersAsync();
    await task;
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[1][1]?.headers).toMatchObject({ "Last-Event-ID": "1" });
    expect(received.map((item) => item.seq)).toEqual([1, 2]);
    expect(states).toContain("reconnecting");
    expect(states.at(-1)).toBe("complete");
  });
  it("closes on verdict completion without another connection", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response([event, terminal]));
    await streamSse(
      "/events",
      "job-sse",
      { signal: new AbortController().signal, onEvent: vi.fn(), onState: vi.fn() },
      fetcher,
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("rejects cross-job and invalid-provenance evidence without reconnecting", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response([{ ...event, job_id: "another-job" }]));
    await expect(
      streamSse(
        "/events",
        "job-sse",
        { signal: new AbortController().signal, onEvent: vi.fn(), onState: vi.fn() },
        fetcher,
      ),
    ).rejects.toMatchObject({ code: "wrong_job" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("bounds disconnection retries and respects cancellation", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline"));
    const task = streamSse(
      "/events",
      "job-sse",
      { signal: new AbortController().signal, onEvent: vi.fn(), onState: vi.fn() },
      fetcher,
    );
    const rejection = expect(task).rejects.toMatchObject({ code: "stream_disconnected" });
    await vi.runAllTimersAsync();
    await rejection;
    expect(fetcher).toHaveBeenCalledTimes(6);
    const controller = new AbortController();
    controller.abort();
    await streamSse(
      "/events",
      "job-sse",
      { signal: controller.signal, onEvent: vi.fn(), onState: vi.fn() },
      fetcher,
    );
    expect(fetcher).toHaveBeenCalledTimes(6);
  });
});
