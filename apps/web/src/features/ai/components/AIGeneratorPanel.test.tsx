import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch } from "@/test/fetch";

import clarification from "../__fixtures__/generation-clarification.json";
import completed from "../__fixtures__/generation-completed.json";
import { EXAMPLE_PROMPTS } from "../api";
import { AIGenerationStatus, StageList } from "./AIGenerationStatus";
import { AIGeneratorPanel } from "./AIGeneratorPanel";

const PROJECT = completed.project_id;

function generation(patch: Record<string, unknown>) {
  return { ...completed, ...patch };
}

function renderPanel(onCompleted = vi.fn()) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <AIGeneratorPanel projectId={PROJECT} onCompleted={onCompleted} />
    </QueryClientProvider>,
  );
  return onCompleted;
}

afterEach(() => vi.unstubAllGlobals());

describe("AIGeneratorPanel", () => {
  it("fills the description from an example prompt", async () => {
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: EXAMPLE_PROMPTS[1] }));
    expect(screen.getByRole("textbox", { name: "Building description" })).toHaveValue(
      EXAMPLE_PROMPTS[1],
    );
  });

  it("keeps the primary action disabled until there is a description", async () => {
    renderPanel();
    const button = screen.getByRole("button", { name: /generate 3d building/i });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Building description" }), "Villa");
    expect(button).toBeEnabled();
  });

  it("starts a generation, follows the real stages and hands over the result", async () => {
    const fetch = mockFetch(
      jsonResponse(generation({ status: "queued", stage: "queued", version_id: null }), 202),
      jsonResponse(generation({ status: "running", stage: "layout", version_id: null })),
      jsonResponse(completed),
      jsonResponse({ items: [] }),
      jsonResponse({ items: [] }),
      jsonResponse({ items: [] }),
      jsonResponse({ items: [] }),
    );
    const onCompleted = renderPanel();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Building description" }),
      "Modern villa with four bedrooms",
    );
    await userEvent.click(
      screen.getByRole("button", {
        name: "Optional details" + " — area, floors, style, budget, region",
      }),
    );
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Floors" }), "2");
    await userEvent.type(screen.getByRole("spinbutton", { name: "Budget amount" }), "300000000");
    await userEvent.click(screen.getByRole("button", { name: /generate 3d building/i }));

    await waitFor(() => expect(onCompleted).toHaveBeenCalledTimes(1), { timeout: 4000 });
    expect(onCompleted.mock.calls[0]![0].version_id).toBe(completed.version_id);
    const [url, init] = fetch.mock.calls[0]!;
    expect(String(url)).toBe("/api/v1/ai/generate-building");
    expect(JSON.parse(init!.body as string)).toEqual({
      project_id: PROJECT,
      prompt: "Modern villa with four bedrooms",
      options: { storeys: 2, budget: { amount: "300000000", currency: "KZT" } },
    });
    expect(String(fetch.mock.calls[1]![0])).toBe(`/api/v1/ai/generations/${completed.id}`);
  });

  it("shows the API error when a generation cannot start", async () => {
    mockFetch(
      jsonResponse(
        { error: { code: "AI_RATE_LIMITED", message: "Too many AI generations", details: [] } },
        429,
      ),
    );
    renderPanel();
    await userEvent.type(screen.getByRole("textbox", { name: "Building description" }), "Villa");
    await userEvent.click(screen.getByRole("button", { name: /generate 3d building/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many AI generations");
  });
});

describe("AIGenerationStatus", () => {
  const noop = () => undefined;

  it("marks real stages without percentages", () => {
    render(
      <StageList generation={generation({ status: "running", stage: "checking" }) as never} />,
    );
    const items = within(screen.getByRole("list", { name: "Generation progress" }))
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(items).toEqual([
      "✓Understanding your requirements",
      "✓Validating the building specification",
      "✓Generating the layout",
      "Checking building rules",
      "Saving the new version",
      "Building the 3D model and opening the project",
    ]);
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.getByText("Offline mock interpreter (development mode)")).toBeVisible();
  });

  it("shows the repair step only when it happened", () => {
    render(
      <StageList
        generation={generation({ status: "running", stage: "repairing", repair_count: 0 }) as never}
      />,
    );
    expect(screen.getByText("Correcting the specification")).toBeVisible();
  });

  it("asks the clarification questions and continues with the answers", async () => {
    const onClarified = vi.fn();
    render(
      <AIGenerationStatus
        generation={clarification as never}
        onClarified={onClarified}
        onRetry={noop}
      />,
    );
    const continueButton = screen.getByRole("button", { name: "Continue" });
    expect(continueButton).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: /how many floors/i }), "2");
    await userEvent.click(continueButton);
    expect(onClarified).toHaveBeenCalledWith(
      "Create me a house.\n\nAdditional details:\n- How many floors should the house have (1 to 3)? 2",
    );
  });

  it("explains failures with their reasons and offers a retry", async () => {
    const onRetry = vi.fn();
    render(
      <AIGenerationStatus
        generation={
          generation({
            status: "failed",
            stage: "layout",
            warnings: [
              {
                severity: "warning",
                code: "AI_UNSUPPORTED_REQUEST",
                path: "",
                message: "Swimming pool — not supported by the layout engine yet",
                suggestion: null,
                rule_ref: null,
                element_id: null,
              },
            ],
            error: {
              code: "LAYOUT_INFEASIBLE",
              message: "The requested requirements could not produce a valid layout.",
              details: [
                {
                  severity: "error",
                  code: "LAYOUT_BAND",
                  path: "",
                  message: "floor 2: rooms do not fit the garden-side band",
                  suggestion: null,
                  rule_ref: null,
                  element_id: null,
                },
              ],
            },
          }) as never
        }
        onClarified={noop}
        onRetry={onRetry}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("could not produce a valid layout");
    expect(alert).toHaveTextContent("rooms do not fit the garden-side band");
    expect(screen.getByText(/Swimming pool/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Edit and try again" }));
    expect(onRetry).toHaveBeenCalled();
  });
});
