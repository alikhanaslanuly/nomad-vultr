import { z } from "zod";
import type { AirlockApi } from "./api-types";
import { apiUrl, post, request } from "./http";
import {
  healthSchema,
  createJobSchema,
  jobIdSchema,
  jobSchema,
  receiptIdSchema,
  receiptSchema,
  reportSchema,
  samplesSchema,
  sourceSchema,
} from "./models";
import { streamSse } from "./sse";

export function createRealApi(base: string): AirlockApi {
  const url = (path: string) => apiUrl(base, path);
  const job = (id: string) => `jobs/${encodeURIComponent(id)}`;
  return {
    getHealth: (signal) => request(url("health"), healthSchema, { signal }),
    createJob: (input, signal) =>
      request(url("jobs"), jobIdSchema, post(createJobSchema.parse(input), signal), 201),
    getJob: (id, signal) => request(url(job(id)), jobSchema, { signal }),
    streamEvents: (id, options) => streamSse(url(`${job(id)}/events`), id, options),
    getReport: (id, signal) =>
      request(url(`${job(id)}/report`), reportSchema, { signal }),
    getSource: (id, signal) =>
      request(url(`${job(id)}/source`), sourceSchema, { signal }),
    verify: (id, signal) =>
      request(url(`${job(id)}/verify`), receiptIdSchema, post({}, signal), 202),
    getReceipt: (id, signal) =>
      request(url(`receipts/${encodeURIComponent(id)}`), receiptSchema, { signal }),
    listSamples: (signal) => request(url("samples"), samplesSchema, { signal }),
    runSample: (id, input, signal) =>
      request(
        url(`samples/${encodeURIComponent(id)}/run`),
        jobIdSchema,
        post(input, signal),
        [200, 201],
      ),
    listJobs: (signal) => request(url("jobs"), z.array(jobSchema), { signal }),
  };
}
