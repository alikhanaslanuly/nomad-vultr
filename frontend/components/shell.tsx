import Link from "next/link";
import { ArrowUpRight, Shield } from "lucide-react";
import { isMock } from "@/lib/api";

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <Link href="/" className="brand" aria-label="Airlock home">
          <span className="brand-icon">
            <Shield size={22} />
          </span>
          AIRLOCK<span className="brand-version">/ 01</span>
        </Link>
        <nav aria-label="Main navigation">
          <Link href="/">New analysis</Link>
          <Link href="/history">History</Link>
          <Link href="/admin">Operator</Link>
        </nav>
        <span className={`mode-badge ${isMock ? "mock" : "live"}`}>
          <span className="status-dot" />
          {isMock ? "MOCK / SIMULATED" : "LIVE API MODE"}
        </span>
      </header>
      <div className="environment-strip">
        <span>{isMock ? "LOCAL SIMULATION" : "BACKEND CONNECTION"}</span>
        <span>
          {isMock
            ? "Synthetic evidence · no code execution"
            : "Availability is determined by API responses"}
        </span>
        <a
          href="https://github.com/alikhanaslanuly/nomad-vultr"
          target="_blank"
          rel="noreferrer"
        >
          Source <ArrowUpRight size={13} />
        </a>
      </div>
      <main id="main" className="main-shell">
        {children}
      </main>
      <footer>
        <span>
          AIRLOCK <span className="muted">/ Evidence before trust.</span>
        </span>
        <span>Team-authored samples. Canary credentials are fake.</span>
        <span>{isMock ? "SIMULATED ENVIRONMENT" : "FRONTEND / CONTRACT v1.0"}</span>
      </footer>
    </>
  );
}
