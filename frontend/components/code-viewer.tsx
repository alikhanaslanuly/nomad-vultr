"use client";

import { useEffect, useRef, useState } from "react";
import { Copy } from "lucide-react";
import type { Finding, Source } from "@/lib/models";

export function CodeViewer({
  source,
  finding,
  error,
}: {
  source?: Source;
  finding?: Finding;
  error?: string;
}) {
  const [selectedPath, setSelectedPath] = useState<string>();
  const [copyState, setCopyState] = useState("");
  const firstLine = useRef<HTMLSpanElement>(null);
  const selectedFile =
    source?.files.find(
      (file) => file.path === (finding?.code_ref?.file ?? selectedPath),
    ) ?? (!finding?.code_ref ? source?.files[0] : undefined);
  const range = finding?.code_ref;
  useEffect(() => {
    if (range) firstLine.current?.scrollIntoView?.({ block: "nearest" });
  }, [range]);
  const lines = selectedFile?.content.slice(0, 200000).split("\n").slice(0, 2000) ?? [];
  async function copy() {
    if (!selectedFile) return;
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopyState("Copied displayed source text.");
    } catch {
      setCopyState("Clipboard unavailable. Select the source text to copy it.");
    }
  }
  return (
    <section className="panel code-panel" aria-labelledby="source-title">
      <div className="panel-heading">
        <h2 id="source-title">Source evidence</h2>
        {selectedFile && (
          <button className="text-button" type="button" onClick={copy}>
            <Copy size={14} />
            Copy text
          </button>
        )}
      </div>
      {source && source.files.length > 1 && (
        <label className="source-select">
          File
          <select
            value={selectedFile?.path ?? ""}
            onChange={(event) => setSelectedPath(event.target.value)}
            disabled={Boolean(range)}
          >
            {source.files.map((file) => (
              <option key={file.path} value={file.path}>
                {file.path}
              </option>
            ))}
          </select>
        </label>
      )}
      {selectedFile ? (
        <>
          <div className="code-file mono">
            {selectedFile.path}
            <span>{selectedFile.language} · text only</span>
          </div>
          <pre
            className="code-source"
            tabIndex={0}
            aria-label={`Source ${selectedFile.path}`}
          >
            <code>
              {lines.map((line, index) => {
                const number = index + 1;
                const highlighted =
                  range &&
                  selectedFile.path === range.file &&
                  number >= range.line_start &&
                  number <= range.line_end;
                return (
                  <span
                    className={`code-line ${highlighted ? "line-highlight" : ""}`}
                    data-testid={highlighted ? "highlighted-source-line" : undefined}
                    key={number}
                    ref={number === range?.line_start ? firstLine : undefined}
                  >
                    <span className="line-number" aria-hidden="true">
                      {number}
                    </span>
                    <span>{line || " "}</span>
                  </span>
                );
              })}
            </code>
          </pre>
          {(selectedFile.content.length > 200000 ||
            selectedFile.content.split("\n").length > 2000) && (
            <p className="availability-note">
              Source display is limited to 200,000 characters / 2,000 lines.
            </p>
          )}
          {range && range.line_end > lines.length && (
            <p className="availability-note">
              Some referenced lines are unavailable or exceed the display limit.
            </p>
          )}
        </>
      ) : (
        <p className="empty-state">
          {error ??
            (range
              ? `Referenced file unavailable: ${range.file}`
              : source
                ? "No source files supplied by the backend."
                : "Source is loading…")}
        </p>
      )}
      {copyState && (
        <p className="fine-print" role="status">
          {copyState}
        </p>
      )}
    </section>
  );
}
