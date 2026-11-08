import { ApiError, isAborted } from "./errors";
import { eventSchema, type AirlockEvent } from "./models";

export type StreamState =
  "connecting" | "connected" | "reconnecting" | "complete" | "disconnected";
export type StreamOptions = {
  signal: AbortSignal;
  afterSeq?: number;
  onEvent: (event: AirlockEvent) => void;
  onState: (state: StreamState) => void;
};
export type Frame = { data: string; id?: string };

export class SseParser {
  private buffer = "";
  private data: string[] = [];
  private id: string | undefined;
  private size = 0;

  push(chunk: string): Frame[] {
    this.buffer += chunk;
    const frames: Frame[] = [];
    for (;;) {
      const match = /\r\n|\r|\n/.exec(this.buffer);
      if (!match || (match[0] === "\r" && match.index === this.buffer.length - 1)) break;
      const line = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      this.size += line.length;
      if (this.size > 262144)
        throw new ApiError("event_limit", "An event exceeded the display limit.");
      if (line === "") {
        if (this.data.length) frames.push({ data: this.data.join("\n"), id: this.id });
        this.data = [];
        this.id = undefined;
        this.size = 0;
      } else if (!line.startsWith(":")) {
        const separator = line.indexOf(":");
        const field = separator === -1 ? line : line.slice(0, separator);
        const value = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");
        if (field === "data") this.data.push(value);
        if (field === "id" && !value.includes("\0")) this.id = value;
      }
    }
    if (this.buffer.length > 262144)
      throw new ApiError("event_limit", "An event exceeded the display limit.");
    return frames;
  }
}

export function isTerminal(event: AirlockEvent): boolean {
  return (
    event.kind === "stage" &&
    event.detail.name === "verdict" &&
    (event.detail.state === "end" || event.detail.state === "error")
  );
}

export class EventSequence {
  private pending = new Map<number, AirlockEvent>();
  constructor(public checkpoint = -1) {}

  accept(event: AirlockEvent): AirlockEvent[] {
    if (event.seq <= this.checkpoint) return [];
    if (this.checkpoint === -1 && event.seq === 1) this.checkpoint = 0;
    this.pending.set(event.seq, event);
    if (this.pending.size > 1000)
      throw new ApiError(
        "sequence_gap",
        "Event sequence has an unresolved gap. Retry to replay evidence.",
      );
    const ready: AirlockEvent[] = [];
    let next = this.pending.get(this.checkpoint + 1);
    while (next) {
      this.pending.delete(next.seq);
      this.checkpoint = next.seq;
      ready.push(next);
      next = this.pending.get(this.checkpoint + 1);
    }
    return ready;
  }

  flush(): AirlockEvent[] {
    const ready = [...this.pending.values()].sort((left, right) => left.seq - right.seq);
    this.pending.clear();
    for (const event of ready) this.checkpoint = event.seq;
    return ready;
  }
}

export function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const cancel = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", cancel);
      resolve();
    }, ms);
    signal.addEventListener("abort", cancel, { once: true });
  });
}

export async function streamSse(
  url: string,
  jobId: string,
  options: StreamOptions,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const sequence = new EventSequence(options.afterSeq ?? -1);
  for (let attempt = 0; attempt <= 5; attempt += 1) {
    if (options.signal.aborted) return;
    options.onState(attempt === 0 ? "connecting" : "reconnecting");
    try {
      const response = await fetcher(url, {
        signal: options.signal,
        cache: "no-store",
        credentials: "omit",
        headers: {
          Accept: "text/event-stream",
          ...(sequence.checkpoint >= 0
            ? { "Last-Event-ID": String(sequence.checkpoint) }
            : {}),
        },
      });
      if (!response.ok)
        throw new ApiError(
          "stream_http",
          `Event stream unavailable (HTTP ${response.status}).`,
          response.status,
        );
      if (
        !response.body ||
        !response.headers.get("content-type")?.includes("text/event-stream")
      )
        throw new ApiError(
          "stream_format",
          "The backend did not provide an event stream.",
        );
      options.onState("connected");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SseParser();
      try {
        for (;;) {
          const chunk = await reader.read();
          if (chunk.done) break;
          for (const frame of parser.push(
            decoder.decode(chunk.value, { stream: true }),
          )) {
            const payload: unknown = JSON.parse(frame.data);
            const event = eventSchema.parse(payload);
            if (event.job_id !== null && event.job_id !== jobId)
              throw new ApiError(
                "wrong_job",
                "The stream returned evidence for a different job.",
              );
            for (const ordered of sequence.accept(event)) {
              options.onEvent(ordered);
              if (isTerminal(ordered)) {
                options.onState("complete");
                return;
              }
            }
          }
          for (const ordered of sequence.flush()) {
            options.onEvent(ordered);
            if (isTerminal(ordered)) {
              options.onState("complete");
              return;
            }
          }
        }
      } finally {
        await reader.cancel().catch((error: unknown) => {
          if (!isAborted(error)) throw error;
        });
        reader.releaseLock();
      }
    } catch (error: unknown) {
      if (isAborted(error) || options.signal.aborted) return;
      if (
        !(error instanceof TypeError) &&
        !(
          error instanceof ApiError &&
          error.status !== undefined &&
          (error.status >= 500 || error.status === 429)
        )
      ) {
        options.onState("disconnected");
        throw error;
      }
    }
    if (attempt < 5)
      await delay(
        Math.min(500 * 2 ** attempt, 8000) * (0.8 + Math.random() * 0.4),
        options.signal,
      );
  }
  options.onState("disconnected");
  throw new ApiError(
    "stream_disconnected",
    "The event stream disconnected after bounded retries. Retry to resume.",
  );
}
