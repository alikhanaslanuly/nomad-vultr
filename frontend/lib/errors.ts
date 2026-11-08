import { z } from "zod";

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const errorPayload = z.object({
  error: z.object({ code: z.string(), message: z.string() }),
});

export function httpError(status: number, payload: unknown): ApiError {
  const parsed = errorPayload.safeParse(payload);
  const code =
    parsed.success && /^[a-z][a-z0-9_]{0,63}$/.test(parsed.data.error.code)
      ? parsed.data.error.code
      : "http_error";
  return new ApiError(code, `Request failed (HTTP ${status}).`, status);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return `${error.message} [${error.code}]`;
  if (error instanceof z.ZodError)
    return "The API returned data outside the agreed contract.";
  return "The request could not be completed. Check your connection and retry.";
}

export function isAborted(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
