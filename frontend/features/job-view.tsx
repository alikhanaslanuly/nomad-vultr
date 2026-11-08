"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, Bot } from "lucide-react";
import { CodeViewer } from "@/components/code-viewer";
import { EventTimeline, type EventFilters } from "@/components/event-timeline";
import { PipelineStages } from "@/components/pipeline";
import { AnalysisReport } from "@/components/report";
import { ErrorNotice, Loading } from "@/components/ui";
import type { Finding } from "@/lib/models";
import { isMock } from "@/lib/api";
import { useJob } from "./use-job";

export function JobView({ id }: { id: string }) {
  const state = useJob(id);
  const simulated = isMock || state.job?.mode === "mock" || state.report?.mode === "mock";
  const [selected, setSelected] = useState<Finding>();
  const [filters, setFilters] = useState<EventFilters>({ run: "all", severity: "all" });
  const [autoScroll, setAutoScroll] = useState(true);
  const agents = state.events.filter((event) => event.kind === "agent");
  function selectFinding(finding: Finding) {
    setSelected(finding);
    setFilters({ run: "all", severity: "all" });
    setAutoScroll(false);
  }
  return (
    <>
      <Link className="back-link" href="/">
        <ArrowLeft size={14} />
        New analysis
      </Link>
      <div className="job-heading">
        <div>
          <p className="eyebrow">
            {simulated
              ? "SIMULATED RUN / SYNTHETIC EVIDENCE"
              : "API RUN / RECEIVED EVIDENCE"}
          </p>
          <h1>{state.report ? "The evidence is in." : "Inside the airlock."}</h1>
          <p className="mono muted job-id">{id}</p>
        </div>
        <div className={`connection-status connection-${state.connection}`} role="status">
          <span className="status-dot" />
          {state.job?.status === "error" ? "JOB ERROR" : state.connection.toUpperCase()}
          <span>{state.job?.status ?? "Loading job"}</span>
        </div>
      </div>
      {simulated && (
        <p className="simulation-notice">
          MOCK: synthetic frontend/backend fixtures. Team sample scenarios and fake
          canaries. No code execution. Reload replays the simulation.
        </p>
      )}
      {!simulated && state.job && state.job.mode !== "live" && (
        <p className="availability-note">
          Execution mode was not recorded for this job. Runtime provenance is unverified.
        </p>
      )}
      <PipelineStages events={state.events} />
      {state.error && <ErrorNotice message={state.error} retry={state.retry} />}
      {!state.job && !state.error && <Loading>Loading job…</Loading>}
      {state.job?.status === "done" && !state.report && !state.error && (
        <Loading>Loading completed report…</Loading>
      )}
      {state.report && (
        <AnalysisReport
          report={state.report}
          events={state.events}
          selected={selected}
          onFinding={selectFinding}
        />
      )}
      {state.streamError && (
        <ErrorNotice message={state.streamError} retry={state.retry} />
      )}
      <div className="evidence-layout">
        <EventTimeline
          events={state.events}
          report={state.report}
          selectedIds={selected?.evidence_event_ids ?? []}
          filters={filters}
          onFilters={setFilters}
          autoScroll={autoScroll}
          onAutoScroll={setAutoScroll}
          truncated={state.truncated}
          canaryObserved={state.canaryObserved}
          simulated={simulated}
        />
        <aside className="agent-panel panel">
          <div className="panel-heading">
            <h2>
              <Bot size={16} />
              Agent notes
            </h2>
            <span className="mono muted">EXPLANATION</span>
          </div>
          <div className="agent-notes">
            {agents.length ? (
              agents.map((event) => (
                <article key={event.id}>
                  <p className="section-label">
                    {event.detail.role}
                    <span>STEP {event.detail.step_no}</span>
                  </p>
                  <p>{event.detail.summary}</p>
                </article>
              ))
            ) : (
              <p className="empty-state">No agent summaries received.</p>
            )}
            <p className="fine-print">Agent text is an explanation, not host evidence.</p>
          </div>
        </aside>
      </div>
      <CodeViewer source={state.source} finding={selected} error={state.sourceError} />
    </>
  );
}
