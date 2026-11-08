"use client";

import { useEffect, useRef } from "react";
import {
  Activity,
  Bot,
  FileText,
  Globe2,
  Pause,
  Play,
  Server,
  ShieldAlert,
  Terminal,
  Timer,
} from "lucide-react";
import type { AirlockEvent, Report } from "@/lib/models";
import { eventText, isCanary } from "@/lib/presentation";
import { isMock } from "@/lib/api";

const icons = {
  file: FileText,
  proc: Terminal,
  net: Globe2,
  canary: ShieldAlert,
  limit: Timer,
  stage: Activity,
  agent: Bot,
  system: Server,
};
export type EventFilters = { run: string; severity: string };

export function EventTimeline({
  events,
  report,
  selectedIds,
  filters,
  onFilters,
  autoScroll,
  onAutoScroll,
  truncated,
  canaryObserved,
  simulated = isMock,
}: {
  events: AirlockEvent[];
  report?: Report;
  selectedIds: string[];
  filters: EventFilters;
  onFilters: (filters: EventFilters) => void;
  autoScroll: boolean;
  onAutoScroll: (value: boolean) => void;
  truncated: boolean;
  canaryObserved?: boolean;
  simulated?: boolean;
}) {
  const end = useRef<HTMLDivElement>(null);
  const selected = useRef<HTMLLIElement>(null);
  const hasCanary = canaryObserved || events.some(isCanary);
  const visible = events.filter(
    (event) =>
      (filters.run === "all" || event.run_id === filters.run) &&
      (filters.severity === "all" || event.severity === filters.severity),
  );
  const runs = [
    ...new Set(
      events.map((event) => event.run_id).filter((id): id is string => id !== null),
    ),
  ];
  useEffect(() => {
    if (autoScroll && !selectedIds.length)
      end.current?.scrollIntoView?.({ block: "nearest" });
  }, [events.length, autoScroll, selectedIds.length]);
  useEffect(() => {
    if (selectedIds.length) selected.current?.scrollIntoView?.({ block: "nearest" });
  }, [selectedIds]);

  return (
    <section
      className={`panel timeline-panel ${hasCanary ? "canary-triggered" : ""}`}
      aria-labelledby="timeline-title"
    >
      <div className="panel-heading">
        <h2 id="timeline-title">
          Event timeline <span className="count-badge">{events.length}</span>
        </h2>
        <button
          type="button"
          className="text-button"
          aria-pressed={!autoScroll}
          onClick={() => onAutoScroll(!autoScroll)}
        >
          {autoScroll ? <Pause size={14} /> : <Play size={14} />}
          {autoScroll ? "Pause autoscroll" : "Resume autoscroll"}
        </button>
      </div>
      {hasCanary && (
        <div role="alert" className="canary-alert">
          <ShieldAlert size={18} />
          <strong>
            {simulated ? "SIMULATED CANARY ALERT" : "HOST-REPORTED CANARY ALERT"}
          </strong>
          <span>Fake credential tripwire triggered</span>
        </div>
      )}
      <div className="timeline-filters">
        <label>
          Run / profile
          <select
            value={filters.run}
            onChange={(event) => onFilters({ ...filters, run: event.target.value })}
          >
            <option value="all">All runs + job events</option>
            {runs.map((id) => (
              <option key={id} value={id}>
                {report?.runs.find((run) => run.run_id === id)?.profile ?? id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Severity
          <select
            value={filters.severity}
            onChange={(event) => onFilters({ ...filters, severity: event.target.value })}
          >
            <option value="all">All severities</option>
            <option value="info">Info</option>
            <option value="warn">Warning</option>
            <option value="alert">Alert</option>
          </select>
        </label>
        <span className="mono muted">SEQ / HOST TIME</span>
      </div>
      {truncated && (
        <p className="availability-note">
          Only the latest 5,000 events are displayed. Earlier evidence may be unavailable
          in this view.
        </p>
      )}
      <div
        className="timeline-scroll"
        tabIndex={0}
        aria-label="Scrollable event evidence"
      >
        <ol className="event-list">
          {visible.map((event) => {
            const Icon = icons[event.kind];
            const highlighted = selectedIds.includes(event.id);
            return (
              <li
                key={event.id}
                ref={
                  highlighted &&
                  event.id ===
                    selectedIds.find((id) => visible.some((item) => item.id === id))
                    ? selected
                    : undefined
                }
                id={`event-${event.seq}`}
                data-testid="event-row"
                data-event-id={event.id}
                className={`event-row severity-${event.severity} ${highlighted ? "evidence-selected" : ""}`}
              >
                <span className="event-seq">{String(event.seq).padStart(3, "0")}</span>
                <time dateTime={event.ts}>{event.ts.slice(11, 23)}</time>
                <Icon size={15} className="event-icon" />
                <div className="event-content">
                  <div className="event-meta">
                    <span>{event.kind}</span>
                    <span>
                      {event.source} / {event.observer}
                    </span>
                    {event.run_id && (
                      <span>
                        {report?.runs.find((run) => run.run_id === event.run_id)
                          ?.profile ?? event.run_id}
                      </span>
                    )}
                    {event.kind === "net" && event.detail.blocked === true && (
                      <strong className="blocked-badge">
                        {event.detail.intercepted ? "Captured locally" : "Blocked"}
                      </strong>
                    )}
                    {isCanary(event) && <strong className="alert-badge">ALERT</strong>}
                  </div>
                  <p>{eventText(event).slice(0, 1200)}</p>
                  <details>
                    <summary>Inspect event payload</summary>
                    <pre>{JSON.stringify(event, null, 2).slice(0, 16000)}</pre>
                  </details>
                </div>
              </li>
            );
          })}
        </ol>
        {!visible.length && (
          <p className="empty-state">
            {events.length
              ? "No events match these filters."
              : "Waiting for evidence from the event stream…"}
          </p>
        )}
        <div ref={end} />
      </div>
    </section>
  );
}
