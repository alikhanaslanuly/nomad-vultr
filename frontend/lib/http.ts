import { z } from "zod";
import { ApiError, httpError } from "./errors";

export function apiUrl(base: string, path: string): string {
  const normalizedBase = base.replace(/\/+$/, "");
  const normalizedPath = path.replace(/^\/+/, "").replace(/^api\//, "");
  if (!normalizedBase.startsWith("/") && !/^https?:\/\//.test(normalizedBase)) {
    throw new ApiError(
      "invalid_base",
      "API base must be an HTTP URL or an absolute path.",
    );
  }
  if (/^https?:/.test(normalizedBase)) {
    const url = new URL(normalizedBase);
    if (url.username || url.password || url.search || url.hash)
      throw new ApiError(
        "invalid_base",
        "API base cannot contain credentials, queries, or fragments.",
      );
  }
  return `${normalizedBase}/${normalizedPath}`;
}

export async function request<T>(
  url: string,
  schema: z.ZodType<T>,
  options: RequestInit = {},
  expectedStatus = 200,
): Promise<T> {
  const response = await fetch(url, {
    ...options,
    signal: options.signal
      ? AbortSignal.any([options.signal, AbortSignal.timeout(15000)])
      : AbortSignal.timeout(15000),
    cache: "no-store",
    credentials: "omit",
    headers: { Accept: "application/json", ...options.headers },
  });
  const body = await response.text();
  if (body.length > 4_000_000)
    throw new ApiError("payload_limit", "API response exceeded the display limit.");
  let payload: unknown;
  try {
    payload = JSON.parse(body);
  } catch {
    throw new ApiError(
      "invalid_json",
      `The API returned a non-JSON response (HTTP ${response.status}).`,
      response.status,
    );
  }
  if (!response.ok) throw httpError(response.status, payload);
  if (response.status !== expectedStatus)
    throw new ApiError(
      "unexpected_status",
      `Unexpected API response (HTTP ${response.status}).`,
      response.status,
    );
  return schema.parse(payload);
}

export function post(body: unknown, signal?: AbortSignal): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  };
}
