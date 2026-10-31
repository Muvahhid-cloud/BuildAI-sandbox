import { vi } from "vitest";

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Install a fetch mock that answers requests in order. */
export function mockFetch(...responses: Response[]) {
  const fn = vi.fn<typeof fetch>();
  for (const r of responses) fn.mockResolvedValueOnce(r);
  vi.stubGlobal("fetch", fn);
  return fn;
}

export const USER = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "ada@example.com",
  display_name: "Ada",
  created_at: "2026-09-27T00:00:00Z",
};

export const tokens = (access = "access-1") => ({
  access_token: access,
  token_type: "bearer",
  expires_in: 900,
  user: USER,
});
