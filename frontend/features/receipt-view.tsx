"use client";

import Link from "next/link";
import { useEffect, useReducer, useState } from "react";
import { api } from "@/lib/api";
import { ApiError, errorMessage, isAborted } from "@/lib/errors";
import type { Receipt } from "@/lib/models";
import { ErrorNotice, Loading } from "@/components/ui";

type State = { receipt?: Receipt; loading: boolean; error?: string; absent: boolean };
export function ReceiptView({ id }: { id: string }) {
  const [state, update] = useReducer(
    (state: State, value: Partial<State>) => ({ ...state, ...value }),
    { loading: true, absent: false },
  );
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    update({ loading: true, error: undefined });
    async function load() {
      try {
        const report = await api.getReport(id, controller.signal);
        if (report.job_id !== id)
          throw new ApiError("wrong_job", "Receipt lookup returned another job.");
        if (!report.receipt_id) {
          update({ absent: true, loading: false });
          return;
        }
        const receipt = await api.getReceipt(report.receipt_id, controller.signal);
        if (receipt.job_id !== id || receipt.receipt_id !== report.receipt_id)
          throw new ApiError(
            "wrong_receipt",
            "Receipt identity did not match the report.",
          );
        update({ receipt, absent: false, loading: false });
      } catch (error: unknown) {
        if (!isAborted(error)) update({ error: errorMessage(error), loading: false });
      }
    }
    void load();
    return () => controller.abort();
  }, [id, reload]);
  return (
    <section className="simple-page">
      <Link className="back-link" href={`/jobs/${encodeURIComponent(id)}`}>
        ← Back to evidence
      </Link>
      <p className="eyebrow">INTEGRITY ARTIFACT</p>
      <h1>The receipt.</h1>
      <p>
        A backend-supplied integrity artifact, not a guarantee of code safety.
        Cryptographic authenticity is not independently verified by this browser.
      </p>
      {state.loading && <Loading>Loading receipt…</Loading>}
      {state.error && (
        <ErrorNotice
          message={state.error}
          retry={() => setReload((value) => value + 1)}
        />
      )}
      {state.absent && (
        <div className="panel empty-state">
          No receipt was supplied for this job. No verification result is implied.
        </div>
      )}
      {state.receipt && (
        <>
          <div className="panel report-notes">
            <h2>
              Re-verification: {state.receipt.verify_result?.status ?? "not supplied"}
            </h2>
            <p>
              Static backend receipt. Starting a new re-verification run is unavailable
              until the endpoint is confirmed operational.
            </p>
          </div>
          <pre className="panel receipt-json" tabIndex={0}>
            {JSON.stringify(state.receipt, null, 2)}
          </pre>
        </>
      )}
    </section>
  );
}
