import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch } from "@/test/fetch";

import { GenerationPanel, GenerationProgress } from "./GenerationPanel";

const PROJECT = "22222222-2222-4222-8222-222222222222";
const JOB = "33333333-3333-4333-8333-333333333333";
const VERSION = "44444444-4444-4444-8444-444444444444";

function job(patch: Record<string, unknown>) {
  return {
    id: JOB,
    project_id: PROJECT,
    kind: "generate",
    status: "queued",
    stage: "queued",
    progress: 0,
    result: null,
    error: null,
    created_at: "2026-09-27T00:00:00Z",
    started_at: null,
    finished_at: null,
    ...patch,
  };
}

function renderPanel(onGenerated = vi.fn()) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <GenerationPanel projectId={PROJECT} onGenerated={onGenerated} />
    </QueryClientProvider>,
  );
  return onGenerated;
}

afterEach(() => vi.unstubAllGlobals());

// GET /design-options is requested when the panel mounts (K3).
const designOptions = () =>
  jsonResponse({
    available: [],
    unavailable: [{ id: "modern-minimal", name: "Modern minimal", reason: "it is draft" }],
    palette: [{ name: "yellow", hex: "#e8c547" }],
  });

describe("GenerationPanel", () => {
  it("validates, starts a job, polls it and opens the new version", async () => {
    const fetch = mockFetch(
      designOptions(),
      jsonResponse({ valid: true, issues: [], rules_profile: "generic-residential@1" }),
      jsonResponse(job({}), 202),
      jsonResponse(job({ status: "running", stage: "layout", progress: 0.25 })),
      jsonResponse(
        job({ status: "succeeded", stage: "done", progress: 1, result: { version_id: VERSION } }),
      ),
      jsonResponse({ items: [] }),
      jsonResponse({ items: [] }),
    );
    const onGenerated = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Generate house" }));

    await waitFor(() => expect(onGenerated).toHaveBeenCalledWith(VERSION), { timeout: 3000 });
    const urls = fetch.mock.calls.map((c) => String(c[0]));
    expect(urls[0]).toBe("/api/v1/design-options");
    expect(urls[1]).toBe(`/api/v1/projects/${PROJECT}/spec/validate`);
    expect(urls[2]).toBe(`/api/v1/projects/${PROJECT}/generate`);
    expect(urls[3]).toBe(`/api/v1/jobs/${JOB}`);
    const body = JSON.parse(fetch.mock.calls[2]![1]!.body as string);
    expect(body.seed).toBe(0);
    expect(body.spec.schema_version).toBe("1.0.0");
  });

  it("shows rules errors and does not start a job", async () => {
    const fetch = mockFetch(
      designOptions(),
      jsonResponse({
        valid: false,
        rules_profile: "generic-residential@1",
        issues: [
          {
            severity: "error",
            code: "SPEC_NO_BATHROOM",
            path: "/rooms",
            message: "A house needs at least one bathroom",
            suggestion: "Add a room of type bathroom.",
          },
        ],
      }),
    );
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Generate house" }));
    expect(await screen.findByText(/needs at least one bathroom/)).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(2); // design options + validation, no job
  });
});

describe("GenerationProgress", () => {
  it("marks real stages done/active/pending without percentages", () => {
    render(<GenerationProgress job={job({ status: "running", stage: "checking" }) as never} />);
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      "✓Validating the specification",
      "✓Planning the layout",
      "Checking building rules",
      "Saving the new version",
    ]);
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("explains failures with the engine's reasons", () => {
    render(
      <GenerationProgress
        job={
          job({
            status: "failed",
            error: {
              code: "LAYOUT_INFEASIBLE",
              message: "No feasible layout for this specification",
              details: [{ message: "footprint wider than the plot allows" }],
            },
          }) as never
        }
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("No feasible layout");
    expect(screen.getByRole("alert")).toHaveTextContent("footprint wider than the plot allows");
  });
});
