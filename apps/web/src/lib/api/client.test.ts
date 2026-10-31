import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { jsonResponse, mockFetch, tokens } from "@/test/fetch";
import { useAuthStore } from "@/stores/auth-store";

import { apiRequest } from "./client";
import { ApiError } from "./errors";

const okSchema = z.object({ ok: z.boolean() });

beforeEach(() => {
  useAuthStore.setState({ status: "authenticated", accessToken: "access-0", user: null });
});
afterEach(() => vi.unstubAllGlobals());

describe("apiRequest", () => {
  it("sends the bearer token and validates the response", async () => {
    const fetch = mockFetch(jsonResponse({ ok: true }));
    await expect(apiRequest("/thing", okSchema)).resolves.toEqual({ ok: true });
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/api/v1/thing");
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer access-0");
  });

  it("maps the error envelope to ApiError with field errors", async () => {
    mockFetch(
      jsonResponse(
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "Request validation failed",
            details: [{ path: "/email", message: "invalid email" }],
          },
        },
        422,
      ),
    );
    const err = await apiRequest("/thing", okSchema).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("VALIDATION_ERROR");
    expect((err as ApiError).fieldErrors()).toEqual({ email: "invalid email" });
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    const fetch = mockFetch(
      jsonResponse({ error: { code: "UNAUTHORIZED", message: "expired", details: [] } }, 401),
      jsonResponse(tokens("access-2")),
      jsonResponse({ ok: true }),
    );
    await expect(apiRequest("/thing", okSchema)).resolves.toEqual({ ok: true });
    expect(fetch.mock.calls[1]![0]).toBe("/api/v1/auth/refresh");
    const retryHeaders = fetch.mock.calls[2]![1]?.headers as Record<string, string>;
    expect(retryHeaders.Authorization).toBe("Bearer access-2");
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("clears the session when refresh fails", async () => {
    mockFetch(
      jsonResponse({ error: { code: "UNAUTHORIZED", message: "expired", details: [] } }, 401),
      jsonResponse({ error: { code: "UNAUTHORIZED", message: "no", details: [] } }, 401),
    );
    await expect(apiRequest("/thing", okSchema)).rejects.toMatchObject({ status: 401 });
    expect(useAuthStore.getState()).toMatchObject({ status: "anonymous", accessToken: null });
  });

  it("rejects responses that violate the contract", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mockFetch(jsonResponse({ ok: "yes" }));
    await expect(apiRequest("/thing", okSchema)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("returns undefined for 204 responses", async () => {
    mockFetch(jsonResponse(null, 204));
    await expect(apiRequest("/thing", null, { method: "DELETE" })).resolves.toBeUndefined();
  });
});
