"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { api } from "@/lib/api";
import { ApiError, errorMessage, isAborted } from "@/lib/errors";
import type { AirlockEvent, Job, Report, Source } from "@/lib/models";
import { delay, isTerminal, type StreamState } from "@/lib/sse";
import { isCanary } from "@/lib/presentation";

type State = {
  job?: Job;
  report?: Report;
  source?: Source;
  events: AirlockEvent[];
  connection: StreamState;
  error?: string;
  streamError?: string;
  sourceError?: string;
  truncated: boolean;
  canaryObserved: boolean;
};
type Action =
  | { type: "reset" }
  | { type: "job"; job: Job }
  | { type: "report"; report: Report }
  | { type: "source"; source: Source }
  | { type: "event"; event: AirlockEvent }
  | { type: "connection"; connection: StreamState }
  | { type: "error"; field: "error" | "streamError" | "sourceError"; message?: string };
const initial: State = {
  events: [],
  connection: "connecting",
  truncated: false,
  canaryObserved: false,
};

export function jobReducer(state: State, action: Action): State {
  switch (action.type) {
    case "reset":
      return initial;
    case "job":
      return { ...state, job: action.job, error: undefined };
    case "report":
      return { ...state, report: action.report, error: undefined };
    case "source":
      return { ...state, source: action.source, sourceError: undefined };
    case "connection":
      return { ...state, connection: action.connection };
    case "error":
      return { ...state, [action.field]: action.message };
    case "event": {
      if (state.events.some((event) => event.seq === action.event.seq)) return state;
      const events = [...state.events, action.event].sort(
        (left, right) => left.seq - right.seq,
      );
      return {
        ...state,
        events: events.slice(-5000),
        truncated: state.truncated || events.length > 5000,
        canaryObserved: state.canaryObserved || isCanary(action.event),
      };
    }
  }
}

export function useJob(id: string) {
  const [state, dispatch] = useReducer(jobReducer, initial);
  const [retryCount, setRetryCount] = useState(0);
  const checkpoint = useRef({ id, seq: -1, terminal: false });
  useEffect(() => {
    const controller = new AbortController();
    if (checkpoint.current.id !== id) {
      checkpoint.current = { id, seq: -1, terminal: false };
      dispatch({ type: "reset" });
    }
    dispatch({ type: "error", field: "streamError" });
    api
      .getSource(id, controller.signal)
      .then((source) => dispatch({ type: "source", source }))
      .catch((error: unknown) => {
        if (!isAborted(error))
          dispatch({ type: "error", field: "sourceError", message: errorMessage(error) });
      });
    if (checkpoint.current.terminal)
      dispatch({ type: "connection", connection: "complete" });
    else
      api
        .streamEvents(id, {
          signal: controller.signal,
          afterSeq: checkpoint.current.seq,
          onState: (connection) => dispatch({ type: "connection", connection }),
          onEvent: (event) => {
            checkpoint.current.seq = event.seq;
            checkpoint.current.terminal = isTerminal(event);
            dispatch({ type: "event", event });
          },
        })
        .catch((error: unknown) => {
          if (!isAborted(error))
            dispatch({
              type: "error",
              field: "streamError",
              message: errorMessage(error),
            });
        });
    async function poll() {
      try {
        for (let attempt = 0; attempt < 600; attempt += 1) {
          const job = await api.getJob(id, controller.signal);
          if (job.job_id !== id)
            throw new ApiError("wrong_job", "The backend returned a different job.");
          dispatch({ type: "job", job });
          if (job.status === "done" || job.status === "error") {
            for (let reportAttempt = 0; reportAttempt < 4; reportAttempt += 1) {
              try {
                const report = await api.getReport(id, controller.signal);
                if (report.job_id !== id)
                  throw new ApiError(
                    "wrong_job",
                    "The backend returned a different report.",
                  );
                dispatch({ type: "report", report });
                return;
              } catch (error: unknown) {
                if (!(
                  error instanceof ApiError &&
                  error.status === 404 &&
                  reportAttempt < 3
                ))
                  throw error;
                await delay(700, controller.signal);
              }
            }
          }
          if (job.status === "error") {
            dispatch({
              type: "error",
              field: "error",
              message:
                "The backend could not complete this job. No safe verdict is implied.",
            });
            return;
          }
          await delay(1000, controller.signal);
        }
        throw new ApiError(
          "job_timeout",
          "Job polling reached the ten-minute display limit. Retry to check its status.",
        );
      } catch (error: unknown) {
        if (!isAborted(error))
          dispatch({ type: "error", field: "error", message: errorMessage(error) });
      }
    }
    void poll();
    return () => controller.abort();
  }, [id, retryCount]);
  return { ...state, retry: () => setRetryCount((value) => value + 1) };
}
