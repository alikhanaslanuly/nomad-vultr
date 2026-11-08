import type { AirlockEvent } from "./models";
import { stages } from "./models";

export function isCanary(event: AirlockEvent): boolean {
  return (
    event.source === "host" &&
    (event.kind === "canary" || (event.kind === "file" && event.detail.canary === true))
  );
}

export function eventText(event: AirlockEvent): string {
  const detail = event.detail;
  switch (event.kind) {
    case "file":
      return `${event.detail.op} ${event.detail.path}`;
    case "proc":
      return `${event.detail.op} ${event.detail.argv?.join(" ") ?? "process"}${event.detail.exit_code !== undefined ? ` · exit ${event.detail.exit_code}` : ""}`;
    case "net":
      return `${event.detail.op} ${event.detail.dest ?? event.detail.ip ?? "destination unavailable"}${event.detail.port !== undefined ? `:${event.detail.port}` : ""}`;
    case "canary":
      return `${event.detail.trigger} · ${event.detail.canary_id} · ${event.detail.marker}`;
    case "limit":
      return `${event.detail.resource} limit ${event.detail.limit} ${event.detail.unit ?? ""} · ${event.detail.action ?? "action unavailable"}`;
    case "stage":
      return `${event.detail.name} · ${event.detail.state}${event.detail.message ? ` · ${event.detail.message}` : ""}${event.detail.outcome ? ` · ${event.detail.outcome}` : ""}`;
    case "agent":
      return `${event.detail.role} · ${event.detail.summary}`;
    case "system":
      return `${event.detail.op} · ${event.detail.id}`;
    default:
      return JSON.stringify(detail);
  }
}

export function pipelineState(
  events: AirlockEvent[],
): Record<(typeof stages)[number], "pending" | "active" | "done" | "error"> {
  const state: Record<(typeof stages)[number], "pending" | "active" | "done" | "error"> =
    {
      fetch: "pending",
      plan: "pending",
      run: "pending",
      observe: "pending",
      verify: "pending",
      verdict: "pending",
    };
  for (const event of events) {
    if (event.kind !== "stage" || event.run_id !== null || event.detail.run_id) continue;
    state[event.detail.name] =
      event.detail.state === "start"
        ? "active"
        : event.detail.state === "end"
          ? "done"
          : "error";
  }
  return state;
}
