import { z } from "zod";

export const profiles = ["dev-laptop", "ci", "future-date"] as const;
export const stages = ["fetch", "plan", "run", "observe", "verify", "verdict"] as const;
export const verdicts = ["SAFE_OBSERVED", "SUSPICIOUS", "MALICIOUS", "ERROR"] as const;
const text = z.string();
const count = z.number().int().nonnegative();
const profileSchema = z.enum(profiles);
const tierSchema = z.enum(["standard", "burn"]);
export const verdictSchema = z.enum(verdicts);
const severitySchema = z.enum(["info", "warn", "alert"]);
const timestamp = z.iso.datetime({ offset: true });

const envelope = z.object({
  id: text.min(1),
  job_id: text.nullable(),
  run_id: text.nullable(),
  seq: count,
  ts: timestamp,
  severity: severitySchema,
  observer: z.enum([
    "gvisor",
    "strace",
    "fanotify",
    "sink",
    "runner",
    "orchestrator",
    "llm",
  ]),
  source: z.enum(["host", "orchestrator"]),
});

export const eventSchema = z
  .discriminatedUnion("kind", [
    envelope.extend({
      kind: z.literal("stage"),
      detail: z.object({
        name: z.enum(stages),
        state: z.enum(["start", "end", "error"]),
        message: text.optional(),
        run_id: text.nullable().optional(),
        outcome: text.optional(),
        exit_code: z.number().int().optional(),
      }),
    }),
    envelope.extend({
      kind: z.literal("agent"),
      detail: z.object({
        role: z.enum(["planner", "explainer"]),
        step_no: count,
        summary: text,
        tokens_in: count.optional(),
        tokens_out: count.optional(),
      }),
    }),
    envelope.extend({
      kind: z.literal("system"),
      detail: z.object({
        op: z.enum([
          "container_start",
          "container_destroy",
          "vm_create",
          "vm_destroy",
          "runner_ready",
        ]),
        id: text,
        tier: tierSchema.optional(),
        plan: text.optional(),
        region: text.optional(),
      }),
    }),
    envelope.extend({
      kind: z.literal("file"),
      detail: z.object({
        op: z.enum(["open", "read", "write", "unlink"]),
        path: text,
        canary: z.boolean().optional(),
        canary_id: text.optional(),
      }),
    }),
    envelope.extend({
      kind: z.literal("proc"),
      detail: z.object({
        op: z.enum(["exec", "exit"]),
        argv: z.array(text).optional(),
        pid: count.optional(),
        ppid: count.optional(),
        exit_code: z.number().int().optional(),
      }),
    }),
    envelope.extend({
      kind: z.literal("net"),
      detail: z.object({
        op: z.enum(["dns", "connect", "http"]),
        dest: text.optional(),
        ip: text.optional(),
        port: count.max(65535).optional(),
        proto: text.optional(),
        blocked: z.boolean().optional(),
        bytes_out: count.optional(),
        http: z
          .object({
            method: text.optional(),
            path: text.optional(),
            host: text.optional(),
          })
          .optional(),
      }),
    }),
    envelope.extend({
      kind: z.literal("canary"),
      detail: z.object({
        canary_id: text,
        trigger: z.enum(["read", "exfil_attempt"]),
        marker: text,
        where: text.optional(),
        encoding: text.optional(),
      }),
    }),
    envelope.extend({
      kind: z.literal("limit"),
      detail: z.object({
        resource: z.enum(["cpu", "mem", "pids", "time", "disk"]),
        limit: z.number(),
        observed: z.number().optional(),
        unit: text.optional(),
        action: text.optional(),
      }),
    }),
  ])
  .superRefine((event, context) => {
    if (
      event.kind === "canary" ||
      (event.kind === "file" && event.detail.canary === true)
    ) {
      if (
        event.source !== "host" ||
        event.observer === "llm" ||
        event.observer === "orchestrator" ||
        event.severity !== "alert"
      ) {
        context.addIssue({
          code: "custom",
          message:
            "Canary evidence requires host source, a host observer, and alert severity",
        });
      }
    }
  });

export const jobSchema = z.object({
  job_id: text.min(1),
  status: z.enum(["queued", "running", "done", "error"]),
  stage: z.enum(["queued", ...stages, "error", "killed"]),
  verdict: verdictSchema.nullable(),
  risk_score: z.number().min(0).max(100).nullable().optional(),
  tier: tierSchema,
  created_at: timestamp,
  finished_at: timestamp.nullable().optional(),
});
export const findingSchema = z.object({
  id: text,
  severity: severitySchema,
  claim: text,
  observed: text,
  rule: text,
  evidence_event_ids: z.array(text),
  code_ref: z
    .object({
      file: text,
      line_start: z.number().int().positive(),
      line_end: z.number().int().positive(),
    })
    .refine((range) => range.line_end >= range.line_start)
    .optional(),
});
export const reportSchema = z.object({
  job_id: text,
  verdict: verdictSchema,
  risk_score: z.number().min(0).max(100),
  confidence: z.enum(["low", "medium", "high"]),
  headline: text,
  claim: z.object({ source: z.enum(["user", "readme", "package_json"]), text }),
  behavior_summary: text,
  findings: z.array(findingSchema),
  runs: z.array(
    z.object({
      run_id: text,
      profile: profileSchema,
      outcome: text,
      duration_ms: count,
      event_count: count,
    }),
  ),
  recommendations: z.array(text),
  limitations: z.array(text),
  receipt_id: text.nullable(),
  tier: tierSchema,
  llm: z.object({ model: text, tokens_in: count, tokens_out: count }).optional(),
});
export const sourceSchema = z.object({
  files: z.array(z.object({ path: text, content: text, language: text })),
});
export const receiptSchema = z.object({
  receipt_id: text,
  job_id: text,
  manifest: z.object({
    artifact_sha256: text,
    image_digest: text,
    profiles: z.array(profileSchema),
    runs: z.array(z.object({ run_id: text, events_sha256: text, stdout_sha256: text })),
    verdict: verdictSchema,
    created_at: timestamp,
  }),
  chain_hash: text,
  signature: text,
  verify_result: z
    .object({
      status: z.enum(["match", "mismatch", "error"]),
      compared: z.array(text),
      diff: z.array(z.unknown()),
    })
    .nullable()
    .optional(),
});
export const samplesSchema = z.array(
  z.object({
    id: text,
    title: text,
    description: text,
    claim: text,
    expected_verdict: verdictSchema,
    input_type: z.enum(["paste", "zip", "npm"]),
  }),
);
export const createJobSchema = z
  .object({
    input_type: z.enum(["paste", "zip", "npm"]),
    content: text.max(200000).optional(),
    filename: text.max(200).optional(),
    ref: text.max(200).optional(),
    claim: text.max(2000).optional(),
    profiles: z
      .array(profileSchema)
      .min(1)
      .max(3)
      .refine((values) => new Set(values).size === values.length),
    tier: tierSchema,
    invite_code: text.max(200).optional(),
  })
  .superRefine((input, context) => {
    if ((input.input_type === "npm" ? input.ref : input.content)?.trim()) return;
    context.addIssue({
      code: "custom",
      message: "Provide source content or a package reference",
    });
  });
export const jobIdSchema = z.object({ job_id: text.min(1) });
export const receiptIdSchema = z.object({ receipt_id: text.min(1) });
export type AirlockEvent = z.infer<typeof eventSchema>;
export type Job = z.infer<typeof jobSchema>;
export type Report = z.infer<typeof reportSchema>;
export type Finding = z.infer<typeof findingSchema>;
export type Source = z.infer<typeof sourceSchema>;
export type Receipt = z.infer<typeof receiptSchema>;
export type Sample = z.infer<typeof samplesSchema>[number];
export type CreateJob = z.infer<typeof createJobSchema>;
export type Profile = z.infer<typeof profileSchema>;
export type Verdict = z.infer<typeof verdictSchema>;
