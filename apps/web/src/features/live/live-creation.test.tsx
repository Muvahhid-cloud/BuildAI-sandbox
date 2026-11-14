// Live creation end to end in the project page (docs/3d-engine.md §25): one continuous screen
// from the description to the saved version, driven only by what the (fake) backend reports.
// The viewer is replaced by a marker element, so "the same canvas" means the same DOM node.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { demoModelJson } from "@/engine/test-fixtures";
import completed from "@/features/ai/__fixtures__/generation-completed.json";
import { ProjectEditor } from "@/features/editor/components/ProjectEditor";
import { useBuildingStore } from "@/stores/building-store";
import { useRevealStore } from "@/stores/reveal-store";
import { jsonResponse } from "@/test/fetch";
import { flowStep } from "@/viewer/reveal/machine";
import { REVEAL } from "@/viewer/render-settings";

vi.mock("@/viewer/BuildingViewer", () => ({ BuildingViewer: () => <div data-testid="3d" /> }));

const PROJECT = "a0000000-0000-4000-8000-000000000001";
const GENERATION = "c0000000-0000-4000-8000-000000000001";
const JOB = "d0000000-0000-4000-8000-000000000001";
const V1 = "b0000000-0000-4000-8000-000000000001";
const HASH = "hash-of-the-laid-out-model";
const PROMPT = "Modern two-storey family house, about 280 m², 4 bedrooms";
const model = demoModelJson();

type Generation = Record<string, unknown>;

/** A backend whose generation the test moves from stage to stage. */
class FakeBackend {
  generation: Generation = {
    ...completed,
    id: GENERATION,
    project_id: PROJECT,
    prompt: PROMPT,
    status: "queued",
    stage: "queued",
    understanding: null,
    specification: null,
    assumptions: [],
    warnings: [],
    summary: null,
    checks: [],
    version_id: null,
    version_number: null,
    interim_facts: [],
    preview_model_hash: null,
    finished_at: null,
  };
  job: Record<string, unknown> | null = null;
  saved = false;
  previewRequests = 0;
  modelHash = HASH;

  set(patch: Generation) {
    this.generation = { ...this.generation, ...patch };
  }

  save() {
    this.saved = true;
    this.set({
      status: "completed",
      stage: "done",
      version_id: V1,
      version_number: 1,
      preview_model_hash: null,
      summary: completed.summary,
    });
  }

  version() {
    return {
      id: V1,
      project_id: PROJECT,
      parent_version_id: null,
      number: 1,
      label: "AI · Demo house",
      source: "ai_generation",
      schema_version: model.schema_version,
      engine_version: model.engine_version,
      rules_profile: "generic-residential@1",
      seed: 0,
      model_hash: this.modelHash,
      summary: completed.summary,
      created_at: "2026-11-13T00:00:00Z",
    };
  }

  fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const path = String(input).replace(/^\/api\/v1/, "");
    const method = init?.method ?? "GET";
    if (path === "/ai/generate-building" && method === "POST") {
      return jsonResponse(this.generation, 202);
    }
    if (path === `/ai/generations/${GENERATION}`) return jsonResponse(this.generation);
    if (path === `/ai/generations/${GENERATION}/preview` || path === `/jobs/${JOB}/preview`) {
      this.previewRequests += 1;
      const offered = this.generation.preview_model_hash ?? this.job?.preview_model_hash;
      return offered
        ? jsonResponse({ model, model_hash: HASH })
        : jsonResponse({ error: { code: "NOT_FOUND", message: "No preview" } }, 404);
    }
    if (path === `/jobs/${JOB}`) return jsonResponse(this.job);
    if (path === `/projects/${PROJECT}`) {
      return jsonResponse({
        id: PROJECT,
        name: "Live house",
        description: "",
        building_type: "single_family_house",
        region_code: "KZ-ALA",
        currency: "KZT",
        rules_profile_id: "generic-residential@1",
        current_version_id: this.saved ? V1 : null,
        created_at: "2026-11-13T00:00:00Z",
        updated_at: "2026-11-13T00:00:00Z",
      });
    }
    if (path === `/projects/${PROJECT}/versions`) {
      return jsonResponse({ items: this.saved ? [this.version()] : [] });
    }
    if (path === `/projects/${PROJECT}/versions/${V1}`) {
      return jsonResponse({
        ...this.version(),
        prompt: PROMPT,
        spec: null,
        model: structuredClone(model),
        report: null,
        issues: [],
      });
    }
    if (path === `/projects/${PROJECT}/generations`) return jsonResponse({ items: [] });
    if (path.startsWith("/projects")) return jsonResponse({ items: [] });
    throw new Error(`unexpected request ${method} ${path}`);
  };
}

let backend: FakeBackend;

function stubReducedMotion(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reduce && query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })),
  );
}

beforeEach(() => {
  backend = new FakeBackend();
  vi.stubGlobal("fetch", vi.fn(backend.fetch));
  stubReducedMotion(false);
  useRevealStore.getState().dispatch({ type: "reset" });
  useBuildingStore.getState().clear();
});
afterEach(() => vi.unstubAllGlobals());

function openPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ProjectEditor projectId={PROJECT} />
    </QueryClientProvider>,
  );
}

const flow = () => flowStep(useRevealStore.getState(), REVEAL.schedule.lead);
const stages = () =>
  within(screen.getByRole("list", { name: "Generation progress" }))
    .getAllByRole("listitem")
    .map((li) => li.textContent);
const POLL = { timeout: 4000 };

async function describeHouse() {
  openPage();
  await userEvent.type(
    await screen.findByRole("textbox", { name: "Building description" }),
    PROMPT,
  );
  await userEvent.click(screen.getByRole("button", { name: /generate 3d building/i }));
  backend.set({ status: "running", stage: "interpreting" });
  await waitFor(() => expect(flow()).toBe("waiting"), POLL);
}

/** Up to the moment the laid-out model is on screen and being built (not saved yet). */
async function untilTheHouseIsShown() {
  await describeHouse();
  backend.set({ stage: "layout" });
  backend.set({ stage: "checking", preview_model_hash: HASH });
  await waitFor(() => expect(useRevealStore.getState().phase).toBe("assembling"), POLL);
}

describe("one continuous screen", () => {
  it("waiting -> facts -> blueprint -> construction -> saved, on the same canvas", async () => {
    await describeHouse();
    // The canvas is there from the start: the empty site with the drafting sheet.
    const canvas = screen.getByTestId("3d");
    expect(useBuildingStore.getState().scene).toBeNull();
    expect(stages()[0]).toBe("Understanding your requirements"); // active, not done
    expect(
      within(screen.getByRole("region", { name: "Understood so far" })).queryAllByRole("listitem"),
    ).toHaveLength(0);

    // The AI's answer is being written: facts appear one by one, the plot gets its size.
    backend.set({ interim_facts: [{ key: "storeys", value: 2 }] });
    expect(await screen.findByText("2 floors", {}, POLL)).toBeVisible();
    await waitFor(() => expect(flow()).toBe("facts"));
    expect(useRevealStore.getState().plot).toBeNull(); // the area is not known yet
    backend.set({
      interim_facts: [
        { key: "storeys", value: 2 },
        { key: "floor_area_m2", value: 280 },
        { key: "room:bedroom", value: 4 },
      ],
    });
    expect(await screen.findByText("about 280 m²", {}, POLL)).toBeVisible();
    expect(screen.getByText("4 bedrooms")).toBeVisible();
    await waitFor(() => expect(useRevealStore.getState().plot).not.toBeNull());
    expect(useBuildingStore.getState().scene).toBeNull(); // facts are never geometry

    // The layout is done; rules check and saving still run: the house is already built.
    backend.set({ stage: "layout" });
    await waitFor(() => expect(stages()[2]).toBe("Generating the layout"), POLL);
    expect(backend.previewRequests).toBe(0);
    backend.set({ stage: "checking", preview_model_hash: HASH });
    await waitFor(() => expect(useRevealStore.getState().phase).toBe("assembling"), POLL);
    expect(flow()).toBe("blueprint");
    expect(useRevealStore.getState()).toMatchObject({ saved: false, seed: HASH, mode: "build" });
    const scene = useBuildingStore.getState().scene;
    expect(scene).not.toBeNull();
    expect(screen.getByTestId("3d")).toBe(canvas); // the same canvas
    expect(stages().slice(3)).toEqual(["Checking building rules", "Saving the new version"]);
    act(() => useRevealStore.getState().dispatch({ type: "tick", dt: REVEAL.schedule.lead + 0.2 }));
    expect(flow()).toBe("construction");
    expect(screen.queryByText(/building generated successfully/i)).toBeNull();

    // Saved: the version takes over without reloading anything.
    backend.save();
    await screen.findByRole("combobox", { name: "Version" }, POLL);
    await waitFor(() => expect(useRevealStore.getState().saved).toBe(true));
    expect(useRevealStore.getState().phase).toBe("assembling"); // the build simply continues
    expect(useRevealStore.getState().elapsed).toBeGreaterThan(REVEAL.schedule.lead);
    expect(useBuildingStore.getState().scene).toBe(scene); // not rebuilt
    expect(screen.getByTestId("3d")).toBe(canvas); // no remount, no flash
    expect(backend.previewRequests).toBe(1);
    // The summary card waits for the construction to end.
    expect(screen.queryByText(/building generated successfully/i)).toBeNull();
    act(() => useRevealStore.getState().dispatch({ type: "tick", dt: 60 }));
    expect(flow()).toBe("saved");
    expect(await screen.findByText(/building generated successfully/i)).toBeVisible();
  }, 30000);

  it("skipping shows the finished model but never marks a backend stage done", async () => {
    await untilTheHouseIsShown();
    fireEvent.pointerDown(screen.getByTestId("3d")); // the start of a drag
    expect(useRevealStore.getState()).toMatchObject({ phase: "done", saved: false });
    expect(flow()).toBe("built");
    expect(useBuildingStore.getState().scene).not.toBeNull();
    // The backend is still checking: the list says so.
    expect(
      stages()
        .slice(0, 3)
        .every((label) => label?.startsWith("✓")),
    ).toBe(true);
    expect(stages().slice(3)).toEqual(["Checking building rules", "Saving the new version"]);
    backend.set({ stage: "saving" });
    await waitFor(() => expect(stages()[3]).toBe("✓Checking building rules"), POLL);
    expect(stages()[4]).toBe("Saving the new version");
    expect(screen.queryByRole("combobox", { name: "Version" })).toBeNull(); // not opened early
    backend.save();
    await screen.findByRole("combobox", { name: "Version" }, POLL);
    await waitFor(() => expect(flow()).toBe("saved"), POLL);
  }, 30000);

  it("a failure after the layout stops the construction, fades the house out, shows the error", async () => {
    await untilTheHouseIsShown();
    const canvas = screen.getByTestId("3d");
    backend.set({
      status: "failed",
      stage: "saving",
      preview_model_hash: null,
      error: {
        code: "DATABASE_ERROR",
        message: "The design could not be saved. Please try again.",
        details: [],
      },
    });
    expect(await screen.findByRole("alert", {}, POLL)).toHaveTextContent(
      "The design could not be saved. Please try again.",
    );
    await waitFor(() => expect(flow()).toBe("failed"));
    const elapsed = useRevealStore.getState().elapsed;
    expect(canvas.closest("[data-reveal-surface]")!.firstElementChild).toHaveStyle({
      opacity: "0",
    });
    // After the fade: no house, no version, the description can be edited again.
    await waitFor(() => expect(useRevealStore.getState().phase).toBe("idle"), POLL);
    expect(useRevealStore.getState().elapsed).toBeLessThanOrEqual(elapsed);
    expect(useBuildingStore.getState().scene).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Version" })).toBeNull();
    expect(screen.getByRole("button", { name: "Edit and try again" })).toBeVisible();
  }, 30000);

  it("a failure before the layout simply ends the waiting", async () => {
    await describeHouse();
    backend.set({
      status: "failed",
      stage: "interpreting",
      error: { code: "AI_UNAVAILABLE", message: "AI generation is unavailable.", details: [] },
    });
    expect(await screen.findByRole("alert", {}, POLL)).toHaveTextContent("unavailable");
    await waitFor(() => expect(flow()).toBe("idle"));
    expect(screen.queryByTestId("3d")).toBeNull(); // the introduction is back
  }, 30000);

  it("builds the stored model when it was saved before the preview could be shown", async () => {
    await describeHouse();
    backend.save(); // layout, checking and saving all happened between two polls
    await screen.findByRole("combobox", { name: "Version" }, POLL);
    await waitFor(
      () => expect(useRevealStore.getState()).toMatchObject({ phase: "assembling", saved: true }),
      POLL,
    );
    expect(backend.previewRequests).toBe(0);
    expect(useBuildingStore.getState().scene).not.toBeNull();
  }, 30000);

  it("with reduced motion nothing animates: the finished model is shown directly", async () => {
    stubReducedMotion(true);
    openPage();
    await userEvent.type(
      await screen.findByRole("textbox", { name: "Building description" }),
      PROMPT,
    );
    await userEvent.click(screen.getByRole("button", { name: /generate 3d building/i }));
    backend.set({ status: "running", stage: "interpreting" });
    await screen.findByTestId("3d", {}, POLL);
    expect(useRevealStore.getState().phase).toBe("idle"); // no waiting animation
    backend.set({ stage: "checking", preview_model_hash: HASH });
    await waitFor(() => expect(useBuildingStore.getState().scene).not.toBeNull(), POLL);
    expect(useRevealStore.getState()).toMatchObject({ phase: "done", saved: false });
    expect(screen.queryByRole("note")).toBeNull();
    backend.save();
    await screen.findByRole("combobox", { name: "Version" }, POLL);
    await waitFor(() => expect(flow()).toBe("saved"), POLL);
    expect(await screen.findByText(/building generated successfully/i)).toBeVisible();
  }, 30000);
});

describe("specification form (same pipeline)", () => {
  it("shows the laid-out model of the job before it is saved", async () => {
    backend.job = {
      id: JOB,
      project_id: PROJECT,
      kind: "generate",
      status: "running",
      stage: "layout",
      progress: 0.25,
      result: null,
      error: null,
      preview_model_hash: null,
      created_at: "2026-11-13T00:00:00Z",
      started_at: "2026-11-13T00:00:00Z",
      finished_at: null,
    };
    const { liveFromJob } = await import("./live-creation");
    expect(liveFromJob(backend.job as never)).toMatchObject({
      key: JOB,
      status: "running",
      previewHash: null,
      previewPath: `/jobs/${JOB}/preview`,
      versionId: null,
    });
    const saving = { ...backend.job, stage: "saving", preview_model_hash: HASH };
    expect(liveFromJob(saving as never).previewHash).toBe(HASH);
    const done = {
      ...backend.job,
      status: "succeeded",
      stage: "done",
      result: { version_id: V1 },
    };
    expect(liveFromJob(done as never)).toMatchObject({ status: "completed", versionId: V1 });
    const failed = { ...backend.job, status: "failed" };
    expect(liveFromJob(failed as never).status).toBe("failed");
  });
});
