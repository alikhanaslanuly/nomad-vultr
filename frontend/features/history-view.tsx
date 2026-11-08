"use client";

import Link from "next/link";
import { useEffect, useReducer, useState } from "react";
import { api, isMock } from "@/lib/api";
import { errorMessage, isAborted } from "@/lib/errors";
import type { Job } from "@/lib/models";
import { ErrorNotice, Loading, VerdictBadge } from "@/components/ui";

type State = { jobs: Job[]; loading: boolean; error?: string };
export function HistoryView() {
  const [state, update] = useReducer(
    (state: State, value: Partial<State>) => ({ ...state, ...value }),
    { jobs: [], loading: true },
  );
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    update({ loading: true, error: undefined });
    api
      .listJobs(controller.signal)
      .then((jobs) => update({ jobs, loading: false }))
      .catch((error: unknown) => {
        if (!isAborted(error)) update({ error: errorMessage(error), loading: false });
      });
    return () => controller.abort();
  }, [reload]);
  return (
    <section className="simple-page">
      <p className="eyebrow">PREVIOUS ANALYSES</p>
      <h1>Evidence trail.</h1>
      <p>
        {isMock
          ? "MOCK: jobs from this browser session only. Nothing is persisted."
          : "The history payload is validated as observed. An unsupported wrapper is shown as a contract error."}
      </p>
      {state.loading && <Loading>Loading history…</Loading>}
      {state.error && (
        <ErrorNotice
          message={state.error}
          retry={() => setReload((value) => value + 1)}
        />
      )}
      {!state.loading && !state.error && (
        <div className="panel">
          {state.jobs.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Status</th>
                    <th>Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {state.jobs.map((job) => (
                    <tr key={job.job_id}>
                      <th scope="row">
                        <Link href={`/jobs/${encodeURIComponent(job.job_id)}`}>
                          {job.job_id}
                        </Link>
                      </th>
                      <td>{job.status}</td>
                      <td>
                        {job.verdict ? <VerdictBadge verdict={job.verdict} /> : "Pending"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty-state">
              No jobs available. <Link href="/">Start an analysis →</Link>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
