import type {
  CreateJob,
  Health,
  Job,
  Profile,
  Receipt,
  Report,
  Sample,
  Source,
} from "./models";
import type { StreamOptions } from "./sse";

export interface AirlockApi {
  getHealth(signal?: AbortSignal): Promise<Health>;
  createJob(input: CreateJob, signal?: AbortSignal): Promise<{ job_id: string }>;
  getJob(id: string, signal?: AbortSignal): Promise<Job>;
  streamEvents(id: string, options: StreamOptions): Promise<void>;
  getReport(id: string, signal?: AbortSignal): Promise<Report>;
  getSource(id: string, signal?: AbortSignal): Promise<Source>;
  verify(id: string, signal?: AbortSignal): Promise<{ receipt_id: string }>;
  getReceipt(id: string, signal?: AbortSignal): Promise<Receipt>;
  listSamples(signal?: AbortSignal): Promise<Sample[]>;
  runSample(
    id: string,
    input: { profiles: Profile[]; tier: "standard" | "burn"; invite_code?: string },
    signal?: AbortSignal,
  ): Promise<{ job_id: string }>;
  listJobs(signal?: AbortSignal): Promise<Job[]>;
}
