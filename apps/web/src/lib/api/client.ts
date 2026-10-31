import type { z } from "zod";

import { useAuthStore } from "@/stores/auth-store";

import { ApiError } from "./errors";
import { errorEnvelopeSchema, tokenResponseSchema } from "./schemas";

export const API_BASE = "/api/v1";

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export interface RequestOptions {
  method?: Method;
  body?: unknown;
  /** Attach the access token and retry once after refreshing on 401. Default true. */
  auth?: boolean;
  signal?: AbortSignal;
}

async function toApiError(res: Response): Promise<ApiError> {
  const payload: unknown = await res.json().catch(() => null);
  const parsed = errorEnvelopeSchema.safeParse(payload);
  if (parsed.success) {
    const { code, message, details } = parsed.data.error;
    return new ApiError(res.status, code, message, details);
  }
  return new ApiError(res.status, "HTTP_ERROR", res.statusText || `HTTP ${res.status}`);
}

let refreshInFlight: Promise<boolean> | null = null;

/** Exchange the refresh cookie for a new access token. Single-flight across callers. */
export function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "same-origin",
      });
      if (!res.ok) {
        useAuthStore.getState().clear();
        return false;
      }
      useAuthStore.getState().setSession(tokenResponseSchema.parse(await res.json()));
      return true;
    } catch {
      useAuthStore.getState().clear();
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

function send(path: string, opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const token = useAuthStore.getState().accessToken;
  if (opts.auth !== false && token) headers.Authorization = `Bearer ${token}`;
  return fetch(`${API_BASE}${path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    credentials: "same-origin",
    signal: opts.signal,
  });
}

/**
 * Typed API request. Every successful response is validated with `schema`
 * (pass `null` for 204 responses).
 */
export async function apiRequest<S extends z.ZodType>(
  path: string,
  schema: S,
  opts?: RequestOptions,
): Promise<z.infer<S>>;
export async function apiRequest(path: string, schema: null, opts?: RequestOptions): Promise<void>;
export async function apiRequest(
  path: string,
  schema: z.ZodType | null,
  opts: RequestOptions = {},
): Promise<unknown> {
  let res = await send(path, opts);
  if (res.status === 401 && opts.auth !== false && (await refreshSession())) {
    res = await send(path, opts);
  }
  if (!res.ok) throw await toApiError(res);
  if (schema === null) return undefined;

  const parsed = schema.safeParse(await res.json());
  if (!parsed.success) {
    // A contract mismatch is a bug; surface it loudly.
    console.error(`Invalid response for ${path}`, parsed.error);
    throw new ApiError(
      res.status,
      "INVALID_RESPONSE",
      "The server returned an unexpected response",
    );
  }
  return parsed.data;
}
