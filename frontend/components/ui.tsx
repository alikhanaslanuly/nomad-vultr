import { AlertTriangle, LoaderCircle } from "lucide-react";
import type { Verdict } from "@/lib/models";

export function ErrorNotice({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="error-notice" role="alert">
      <AlertTriangle size={18} />
      <span>{message}</span>
      {retry && (
        <button type="button" className="text-button" onClick={retry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Loading({
  children = "Loading evidence…",
}: {
  children?: React.ReactNode;
}) {
  return (
    <p className="loading" role="status">
      <LoaderCircle size={17} className="spinner" />
      {children}
    </p>
  );
}

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`verdict-badge verdict-${verdict.toLowerCase()}`}>
      {verdict === "SAFE_OBSERVED" ? "SAFE OBSERVED" : verdict}
    </span>
  );
}

export function SectionLabel({
  number,
  children,
}: {
  number: string;
  children: React.ReactNode;
}) {
  return (
    <p className="section-label">
      <span>{number}</span>
      {children}
    </p>
  );
}
