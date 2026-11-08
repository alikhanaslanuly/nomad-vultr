import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { CodeViewer } from "@/components/code-viewer";
import { EventTimeline } from "@/components/event-timeline";
import { PipelineStages } from "@/components/pipeline";
import { AnalysisReport } from "@/components/report";
import { ErrorNotice, Loading, VerdictBadge } from "@/components/ui";
import { buildFixture } from "../mock/fixtures";
import type { AirlockEvent, Finding } from "../models";
import { pipelineState } from "../presentation";
import { jobReducer } from "@/features/use-job";

const data = buildFixture("evil-installer", "job-ui", ["ci"], 0);
function Timeline({ events = data.events }: { events?: AirlockEvent[] }) {
  return (
    <EventTimeline
      events={events}
      selectedIds={[]}
      filters={{ run: "all", severity: "all" }}
      onFilters={vi.fn()}
      autoScroll={false}
      onAutoScroll={vi.fn()}
      truncated={false}
    />
  );
}
describe("evidence presentation", () => {
  it("progresses job stages without letting per-run completion finish the whole stage", () => {
    const start = data.events.find(
      (event) =>
        event.kind === "stage" && event.detail.name === "run" && event.run_id === null,
    )!;
    const end = data.events.find(
      (event) =>
        event.kind === "stage" && event.detail.name === "run" && event.run_id !== null,
    )!;
    expect(pipelineState([start, end]).run).toBe("active");
    render(<PipelineStages events={data.events} />);
    expect(screen.getByLabelText("Analysis pipeline")).toHaveTextContent("verdict: done");
  });
  it("shows a persistent canary alert and blocked badges only for explicit blocked=true", () => {
    const net = data.events.find((event) => event.kind === "net")!;
    const canary = data.events.find((event) => event.kind === "canary")!;
    const { rerender } = render(<Timeline events={[net, canary]} />);
    expect(screen.getByRole("alert")).toHaveTextContent("CANARY ALERT");
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    if (net.kind !== "net") throw new Error("Missing network fixture");
    rerender(
      <Timeline events={[{ ...net, detail: { ...net.detail, blocked: undefined } }]} />,
    );
    expect(screen.queryByText("Blocked")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("renders unsafe source, claims, and paths as escaped text only", () => {
    const unsafe = '<img src=x onerror="alert(1)"><script>bad()</script>';
    const file: AirlockEvent = {
      ...data.events[0],
      kind: "file",
      source: "host",
      observer: "strace",
      detail: { op: "read", path: unsafe },
    };
    const { container } = render(
      <>
        <Timeline events={[file]} />
        <CodeViewer
          source={{ files: [{ path: "x", language: "html", content: unsafe }] }}
        />
        <AnalysisReport
          report={{ ...data.report, claim: { source: "readme", text: unsafe } }}
          events={[]}
          onFinding={vi.fn()}
        />
      </>,
    );
    expect(screen.getAllByText(unsafe).length).toBeGreaterThan(0);
    expect(container.querySelector("img,script,iframe")).toBeNull();
  });
  it("keeps limitations visible even when the backend omits their text", () => {
    render(
      <AnalysisReport
        report={{ ...data.report, limitations: [] }}
        events={[]}
        onFinding={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { name: "Limitations" })).toBeInTheDocument();
    expect(screen.getByText(/backend did not supply limitations/i)).toBeInTheDocument();
  });
  it("links a finding to its source lines with keyboard activation and reports missing events", async () => {
    function Evidence() {
      const [finding, select] = useState<Finding>();
      return (
        <>
          <AnalysisReport
            report={data.report}
            events={[]}
            selected={finding}
            onFinding={select}
          />
          <CodeViewer source={data.source} finding={finding} />
        </>
      );
    }
    const user = userEvent.setup();
    render(<Evidence />);
    const findingButton = screen.getByRole("button", { name: /read a fake AWS canary/i });
    findingButton.focus();
    await user.keyboard("{Enter}");
    expect(findingButton).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByTestId("highlighted-source-line")).toHaveLength(2);
    expect(screen.getByRole("status")).toHaveTextContent(
      "referenced events are unavailable",
    );
  });
  it("shows missing source and empty timeline without manufacturing evidence", () => {
    render(
      <>
        <CodeViewer source={{ files: [] }} finding={data.report.findings[0]} />
        <Timeline events={[]} />
      </>,
    );
    expect(screen.getByText(/Referenced file unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Waiting for evidence/)).toBeInTheDocument();
  });
  it("distinguishes ERROR from SAFE_OBSERVED and renders loading and retry states", async () => {
    const retry = vi.fn();
    render(
      <>
        <VerdictBadge verdict="ERROR" />
        <VerdictBadge verdict="SAFE_OBSERVED" />
        <Loading />
        <ErrorNotice message="Unavailable" retry={retry} />
      </>,
    );
    expect(screen.getByText("ERROR")).toHaveClass("verdict-error");
    expect(screen.getByRole("status")).toHaveTextContent("Loading evidence");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
  it("deduplicates state events and keeps ERROR independent of any report verdict", () => {
    const initial = jobReducer(
      { events: [], connection: "connecting", truncated: false, canaryObserved: false },
      { type: "reset" },
    );
    const connected = jobReducer(initial, {
      type: "connection",
      connection: "connected",
    });
    const received = jobReducer(connected, { type: "event", event: data.events[0] });
    expect(
      jobReducer(received, { type: "event", event: data.events[0] }).events,
    ).toHaveLength(1);
    const failed = jobReducer(received, {
      type: "error",
      field: "error",
      message: "backend failed",
    });
    expect(failed.report).toBeUndefined();
    expect(failed.error).toBe("backend failed");
  });
});
