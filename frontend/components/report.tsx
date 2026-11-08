"use client";

import Link from "next/link";
import { ArrowDownRight, Printer, ShieldAlert, ShieldCheck } from "lucide-react";
import type { AirlockEvent, Finding, Report as ReportModel } from "@/lib/models";
import { VerdictBadge } from "./ui";

export function AnalysisReport({
  report,
  events,
  selected,
  onFinding,
}: {
  report: ReportModel;
  events: AirlockEvent[];
  selected?: Finding;
  onFinding: (finding: Finding) => void;
}) {
  const missing =
    selected?.evidence_event_ids.filter(
      (id) => !events.some((event) => event.id === id),
    ) ?? [];
  const safe = report.verdict === "SAFE_OBSERVED";
  return (
    <section id="report" aria-labelledby="report-title" className="report-section">
      <div className={`verdict-banner verdict-${report.verdict.toLowerCase()}`}>
        <div className="verdict-icon">
          {safe ? <ShieldCheck size={28} /> : <ShieldAlert size={28} />}
        </div>
        <div>
          <div className="verdict-top">
            <VerdictBadge verdict={report.verdict} />
            <span>
              {report.confidence} confidence · {report.risk_score}/100 risk
            </span>
          </div>
          <h2 id="report-title">{report.headline}</h2>
          <p>
            {safe
              ? "No issue was observed in the tested profiles. This is not proof of safety."
              : "The verdict is supplied by the backend or explicitly labeled simulation."}
          </p>
        </div>
      </div>
      <div className="report-heading">
        <h2>Claim vs. behavior</h2>
        <button type="button" className="text-button" onClick={() => window.print()}>
          <Printer size={15} />
          Print report
        </button>
      </div>
      <div className="comparison-grid">
        <div className="panel claim-card">
          <p className="section-label">
            THE CLAIM <span>{report.claim.source}</span>
          </p>
          <blockquote>{report.claim.text || "No claim supplied."}</blockquote>
          <p className="fine-print">
            Untrusted description. It does not establish safety.
          </p>
        </div>
        <div className="panel behavior-card">
          <p className="section-label">THE OBSERVATION</p>
          <p>{report.behavior_summary}</p>
        </div>
      </div>
      <div className="findings">
        <h3>
          Findings <span className="count-badge">{report.findings.length}</span>
        </h3>
        {report.findings.length ? (
          report.findings.map((finding) => (
            <button
              type="button"
              key={finding.id}
              className={`finding-card ${selected?.id === finding.id ? "finding-selected" : ""}`}
              aria-pressed={selected?.id === finding.id}
              onClick={() => onFinding(finding)}
            >
              <span className={`finding-severity severity-${finding.severity}`}>
                {finding.severity}
              </span>
              <span>
                <strong>{finding.observed}</strong>
                <span className="finding-rule mono">
                  {finding.rule} · {finding.evidence_event_ids.length} evidence events
                  {finding.code_ref
                    ? ` · ${finding.code_ref.file}:${finding.code_ref.line_start}–${finding.code_ref.line_end}`
                    : " · source reference unavailable"}
                </span>
              </span>
              <ArrowDownRight size={19} />
            </button>
          ))
        ) : (
          <p className="empty-state">No findings supplied for this run.</p>
        )}
      </div>
      {selected && (
        <p className="evidence-note" role="status">
          {selected.evidence_event_ids.length
            ? `Linked evidence is highlighted below. ${missing.length ? `${missing.length} referenced events are unavailable in this view.` : "All referenced events are available."}`
            : "No event references were supplied for this finding."}
          {!selected.code_ref && " No source range was supplied."}
        </p>
      )}
      <div className="panel runs-panel">
        <div className="panel-heading">
          <h3>Tested profiles</h3>
          <span className="mono muted">BACKEND-SUPPLIED OUTCOMES</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Profile</th>
                <th>Outcome</th>
                <th>Duration</th>
                <th>Events</th>
              </tr>
            </thead>
            <tbody>
              {report.runs.map((run) => (
                <tr key={run.run_id}>
                  <th scope="row">{run.profile}</th>
                  <td>{run.outcome}</td>
                  <td>{(run.duration_ms / 1000).toFixed(2)} s</td>
                  <td>{run.event_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!report.runs.length && (
            <p className="empty-state">No run outcomes supplied.</p>
          )}
        </div>
      </div>
      <div className="report-details-grid">
        <section className="panel report-notes">
          <h3>Recommendations</h3>
          {report.recommendations.length ? (
            <ul>
              {report.recommendations.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>No recommendations supplied.</p>
          )}
        </section>
        <section
          className="panel report-notes limitations"
          aria-labelledby="limitations-title"
        >
          <h3 id="limitations-title">Limitations</h3>
          <ul>
            {report.limitations.length ? (
              report.limitations.map((item, index) => <li key={index}>{item}</li>)
            ) : (
              <li>
                The backend did not supply limitations. Assessment coverage is
                unavailable; no proof of safety is implied.
              </li>
            )}
          </ul>
          <p>
            Host provenance enforcement belongs to the backend and runner. Checking an
            event field does not prove provenance.
          </p>
        </section>
      </div>
      <div className="receipt-link">
        {report.receipt_id ? (
          <Link href={`/jobs/${encodeURIComponent(report.job_id)}/receipt`}>
            View integrity receipt →
          </Link>
        ) : (
          <span>Receipt unavailable: no receipt was supplied.</span>
        )}
        <span>Integrity is not a code safety guarantee.</span>
      </div>
    </section>
  );
}
