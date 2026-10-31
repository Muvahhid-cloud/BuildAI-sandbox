// Regression: a saved plan edit is what every view shows — the plan (2D), the 3D scene and the
// properties panel — also after a page reload, and the base version stays as it was. The API is
// an in-memory fake that stores versions like the real one (immutable, new version on save).
// WebGL does not run in jsdom: the 3D side is checked on the scene graph the viewer renders
// (one mesh per descriptor, docs/3d-engine.md).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Box3, Vector3 } from "three";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { wallLocal, wallPoint } from "@/engine/drawing/opening-edit";
import { buildPlanDrawing } from "@/engine/drawing/plan";
import { buildPlanSheets } from "@/engine/drawing/sheet";
import { parseBuildingModel } from "@/engine/model/parse";
import type { BuildingModel, Door, Wall, Window } from "@/engine/model/types";
import { bySemanticKey, demoModelJson } from "@/engine/test-fixtures";
import completed from "@/features/ai/__fixtures__/generation-completed.json";
import { useEditStore } from "@/features/editing/store";
import type { EditOperation, Version } from "@/lib/api/schemas";
import { useBuildingStore } from "@/stores/building-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";
import { jsonResponse } from "@/test/fetch";

import { drawingVersionLabel, ProjectEditor } from "./ProjectEditor";

vi.mock("@/viewer/BuildingViewer", () => ({ BuildingViewer: () => <div data-testid="3d" /> }));

const PROJECT = "a0000000-0000-4000-8000-000000000001";
const GENERATION = completed.id;
const V1 = "b0000000-0000-4000-8000-000000000001";
const SUMMARY = {
  storeys: 2,
  gross_floor_area_m2: 240,
  net_floor_area_m2: 200,
  rooms: 15,
  bedrooms: 3,
  bathrooms: 2,
  wcs: 0,
  garage: false,
  balconies: 0,
  terraces: 0,
  walls: 21,
  doors: 10,
  windows: 20,
  elements: 116,
};

const hostId = (el: { relationships: { kind: string; target_id: string }[] }) =>
  el.relationships.find((r) => r.kind === "hosted_by")?.target_id;

/**
 * The fake server's operations: a wall shifts sideways (+ = towards its left face); a door or
 * window moves along / to a wall, is added (sized as asked, like the first opening of its
 * kind otherwise) or removed. Refused: wall moves over 1 m, openings past the wall's end or
 * over another opening of the wall.
 */
function moved(model: BuildingModel, ops: readonly EditOperation[]): BuildingModel | null {
  const out = structuredClone(model);
  let added = 0;
  for (const op of ops) {
    if (op.op === "move_wall") {
      if (Math.abs(op.offset_m) > 1) return null;
      const wall = out.elements.find((e) => e.id === op.wall_id);
      if (wall?.type !== "wall") return null;
      const r = wall.rotation.z;
      wall.position.x = Math.round((wall.position.x - Math.sin(r) * op.offset_m) * 1000) / 1000;
      wall.position.y = Math.round((wall.position.y + Math.cos(r) * op.offset_m) * 1000) / 1000;
    } else if (op.op === "remove_element") {
      out.elements = out.elements.filter((e) => e.id !== op.element_id);
    } else if (op.op === "move_opening" || op.op === "add_opening") {
      let el: Door | Window;
      if (op.op === "move_opening") {
        const found = out.elements.find((e) => e.id === op.opening_id);
        if (found?.type !== "door" && found?.type !== "window") return null;
        el = found;
      } else {
        const like = out.elements.find((e) => e.type === op.kind) as Door | Window;
        added += 1;
        el = {
          ...structuredClone(like),
          id: `d0000000-0000-4000-8000-00000000000${added}`,
          name: `New ${op.kind} ${added}`,
          semantic_key: `${op.kind}:edit:${added}`,
          relationships: [{ kind: "hosted_by", target_id: op.host_wall_id }],
          position: { x: 0, y: 0, z: op.sill_m ?? 0 },
        } as Door | Window;
        el.dimensions = { ...el.dimensions, width: op.width_m, height: op.height_m };
        out.elements.push(el);
      }
      const wallId = (op.op === "move_opening" ? op.host_wall_id : op.host_wall_id) ?? hostId(el);
      const wall = out.elements.find((e) => e.id === wallId);
      if (wall?.type !== "wall") return null;
      const [u0, u1] = [op.offset_m, op.offset_m + el.dimensions.width];
      if (u1 > wall.dimensions.length) return null;
      const clash = out.elements.some(
        (o) =>
          (o.type === "door" || o.type === "window") &&
          o.id !== el.id &&
          hostId(o) === wall.id &&
          o.position.x < u1 &&
          o.position.x + o.dimensions.width > u0,
      );
      if (clash) return null;
      el.position.x = op.offset_m;
      el.relationships = [
        { kind: "hosted_by", target_id: wall.id },
        ...el.relationships.filter((r) => r.kind !== "hosted_by"),
      ];
    } else {
      return null;
    }
  }
  return out;
}

function changedIds(before: BuildingModel, after: BuildingModel): string[] {
  const old = new Map(before.elements.map((e) => [e.id, JSON.stringify(e)]));
  const now = new Map(after.elements.map((e) => [e.id, JSON.stringify(e)]));
  const ids = [...now].filter(([id, json]) => old.get(id) !== json).map(([id]) => id);
  return [...ids, ...[...old.keys()].filter((id) => !now.has(id))].sort();
}

class FakeApi {
  versions: Version[] = [];
  current: string;
  saves = 0;

  constructor(base: BuildingModel) {
    this.versions.push(this.version(V1, 1, null, "AI · Demo house", base));
    this.current = V1;
  }

  version(id: string, n: number, parent: string | null, label: string, model: BuildingModel) {
    return {
      id,
      project_id: PROJECT,
      parent_version_id: parent,
      number: n,
      label,
      source: parent ? "manual" : "ai_generation",
      schema_version: model.schema_version,
      engine_version: model.engine_version,
      rules_profile: "generic-residential@1",
      seed: null,
      model_hash: `hash-${n}`,
      summary: SUMMARY,
      created_at: "2026-10-27T00:00:00Z",
      prompt: null,
      spec: null,
      model: structuredClone(model),
      report: null,
      issues: [],
    } satisfies Version;
  }

  fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const path = String(input).replace(/^\/api\/v1/, "");
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    const ops = (body.operations ?? []) as EditOperation[];
    const find = (id: string) => this.versions.find((v) => v.id === id);
    let m: RegExpMatchArray | null;
    if (path === `/ai/generations/${GENERATION}`) {
      return jsonResponse({ ...completed, project_id: PROJECT, version_id: V1 });
    }
    if (path === `/projects/${PROJECT}`) {
      return jsonResponse({
        id: PROJECT,
        name: "Sync test",
        description: "",
        building_type: "single_family_house",
        region_code: "KZ-ALA",
        currency: "KZT",
        rules_profile_id: "generic-residential@1",
        current_version_id: this.current,
        created_at: "2026-10-27T00:00:00Z",
        updated_at: "2026-10-27T00:00:00Z",
      });
    }
    if (path === `/projects/${PROJECT}/versions`) {
      const items = [...this.versions].reverse().map((v) => {
        const { prompt, spec, model, report, issues, ...summary } = v;
        void [prompt, spec, model, report, issues];
        return summary;
      });
      return jsonResponse({ items });
    }
    if ((m = path.match(/^\/projects\/[^/]+\/versions\/([^/]+)\/edits\/preview$/))) {
      const model = moved(find(m[1])!.model as BuildingModel, ops);
      return jsonResponse({
        valid: model !== null,
        model,
        summary: model ? SUMMARY : null,
        warnings: [],
        changed_ids: model ? changedIds(find(m[1])!.model as BuildingModel, model) : [],
        rejection: model
          ? null
          : {
              code: "EDIT_INVALID",
              message: "This change would make the design invalid",
              index: 0,
              element_id: null,
              related_ids: [],
              issues: [],
            },
      });
    }
    if ((m = path.match(/^\/projects\/[^/]+\/versions\/([^/]+)\/edits$/))) {
      const base = find(m[1])!;
      const model = moved(base.model as BuildingModel, ops);
      if (!model) return jsonResponse({ error: { code: "EDIT_REJECTED", message: "no" } }, 422);
      this.saves += 1;
      const n = this.versions.length + 1;
      const id = `b0000000-0000-4000-8000-00000000000${n}`;
      this.versions.push(this.version(id, n, base.id, `Plan edits on v${base.number}`, model));
      this.current = id;
      return jsonResponse(find(id), 201);
    }
    if ((m = path.match(/^\/projects\/[^/]+\/versions\/([^/]+)$/))) {
      const v = find(m[1]);
      return v ? jsonResponse(v) : jsonResponse({ error: { code: "NOT_FOUND", message: "" } }, 404);
    }
    throw new Error(`unexpected request ${init?.method ?? "GET"} ${path}`);
  };
}

/** The project page: the `?generation=` link lives in the URL until the editor releases it. */
let urlGeneration: string | null;

function openPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ProjectEditor
        projectId={PROJECT}
        generationId={urlGeneration}
        onGenerationReleased={() => (urlGeneration = null)}
      />
    </QueryClientProvider>,
  );
}

const shownVersion = () => screen.getByRole("combobox", { name: "Version" }) as HTMLSelectElement;
const shownWall = (id: string) => {
  const el = useBuildingStore.getState().index?.elementsById.get(id);
  if (el?.type !== "wall") throw new Error("wall not shown");
  return el;
};

/** The XY box of the wall's poché in the plan drawing (model meters). */
function planBox(wall: Wall): Box3 {
  const index = useBuildingStore.getState().index!;
  if (!wall.level_id) throw new Error("wall without a level");
  const box = new Box3();
  for (const g of buildPlanDrawing(index, wall.level_id).groups) {
    if (g.elementId !== wall.id || g.role !== "wall") continue;
    for (const item of g.items) {
      if (item.kind !== "poly") continue;
      for (const [x, y] of item.pts) box.expandByPoint(new Vector3(x, y, 0));
    }
  }
  return box;
}

/** The box of the 3D meshes built for an element (model space). */
function sceneBox(wallId: string): Box3 {
  const box = new Box3();
  for (const d of useBuildingStore.getState().scene!.byElement.get(wallId) ?? []) {
    box.union(d.geometry.boundingBox!.clone().applyMatrix4(d.matrix));
  }
  return box;
}

/** The wall runs east (rotation 0): plan and 3D must put its faces at the same y. */
function expectSameWallIn2DAnd3D(wall: Wall) {
  const plan = planBox(wall);
  const solid = sceneBox(wall.id);
  expect(plan.isEmpty()).toBe(false);
  expect(solid.min.y).toBeCloseTo(plan.min.y, 3);
  expect(solid.max.y).toBeCloseTo(plan.max.y, 3);
  // Both straddle the axis stored in the model.
  expect(plan.min.y).toBeLessThan(wall.position.y);
  expect(plan.max.y).toBeGreaterThan(wall.position.y);
  // Along the wall the plan leaves the door gaps out; the 3D panels span the full length.
  expect(plan.min.x).toBeGreaterThanOrEqual(solid.min.x - 1e-3);
  expect(plan.max.x).toBeLessThanOrEqual(solid.max.x + 1e-3);
}

let api: FakeApi;
const base = demoModelJson();
const wallId = bySemanticKey(base, "wall:G-I1").id; // interior, runs east: + = north
const baseY = (bySemanticKey(base, "wall:G-I1") as Wall).position.y;

beforeEach(() => {
  api = new FakeApi(base);
  vi.stubGlobal("fetch", vi.fn(api.fetch));
  urlGeneration = GENERATION; // opened from the dashboard after an AI generation
  useViewerStore.getState().setViewMode("3d");
  useSelectionStore.getState().select(null);
});

afterEach(() => vi.unstubAllGlobals());

describe("plan edits stay in sync with the 3D model", () => {
  it("shows the saved model in the plan, the 3D scene and the properties — after a reload too", async () => {
    const page = openPage();
    await screen.findByTestId("3d");
    expect(shownVersion().selectedOptions[0].textContent).toMatch(/^v1 /);
    expect(shownWall(wallId).position.y).toBe(baseY);

    // Move the wall in the plan and save it as a new version.
    await userEvent.click(screen.getByRole("button", { name: "Floor plan" }));
    useSelectionStore.getState().select(wallId);
    const distance = await screen.findByLabelText("Distance in meters");
    await userEvent.clear(distance);
    await userEvent.type(distance, "0.3");
    await userEvent.click(screen.getByRole("button", { name: "↑ North" }));
    await screen.findByText("1 change");
    await userEvent.click(screen.getByRole("button", { name: "Save version" }));
    await waitFor(() => expect(shownVersion().selectedOptions[0].textContent).toMatch(/^v2 /));

    const saved = api.versions[1];
    const savedWall = (saved.model as BuildingModel).elements.find((e) => e.id === wallId) as Wall;
    expect(savedWall.position.y).toBeCloseTo(baseY + 0.3, 6);
    expect(useEditStore.getState().versionId).toBe(saved.id); // next edits start from v2
    // Every view shows the stored v2.
    expect(shownWall(wallId)).toEqual(savedWall);
    expectSameWallIn2DAnd3D(shownWall(wallId));
    useSelectionStore.getState().select(wallId);
    expect(await screen.findByText(/y 5\.1 m/)).toBeInTheDocument(); // properties panel
    // The base version is unchanged.
    expect(api.versions[0].model).toEqual(base);
    // The generation link no longer pins v1.
    expect(urlGeneration).toBeNull();

    // Reload the page.
    page.unmount();
    expect(useBuildingStore.getState().index).toBeNull();
    openPage();
    await waitFor(() => expect(shownVersion().selectedOptions[0].textContent).toMatch(/^v2 /));
    await waitFor(() => expect(shownWall(wallId).position.y).toBeCloseTo(baseY + 0.3, 6));
    expect(shownWall(wallId)).toEqual(savedWall);
    expectSameWallIn2DAnd3D(shownWall(wallId));

    // v1 still opens as it was.
    await userEvent.selectOptions(shownVersion(), V1);
    await waitFor(() => expect(shownWall(wallId).position.y).toBe(baseY));
    expectSameWallIn2DAnd3D(shownWall(wallId));
    expect(api.saves).toBe(1);
  }, 30_000); // builds the whole scene four times

  it("never changes the shown or stored model when the server refuses an edit", async () => {
    openPage();
    await screen.findByTestId("3d");
    expect(shownVersion().selectedOptions[0].textContent).toMatch(/^v1 /);
    const before = useBuildingStore.getState().index!.model;
    await userEvent.click(screen.getByRole("button", { name: "Floor plan" }));
    useSelectionStore.getState().select(wallId);
    const distance = await screen.findByLabelText("Distance in meters");
    await userEvent.clear(distance);
    await userEvent.type(distance, "2");
    await userEvent.click(screen.getByRole("button", { name: "↑ North" }));
    expect(await screen.findByText(/would make the design invalid/)).toBeInTheDocument();
    expect(screen.getByText("No changes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save version" })).toBeDisabled();
    expect(useBuildingStore.getState().index!.model).toBe(before);
    expect(shownWall(wallId).position.y).toBe(baseY);
    expectSameWallIn2DAnd3D(shownWall(wallId));
    expect(api.saves).toBe(0);
    expect(api.versions).toHaveLength(1);
    expect(api.versions[0].model).toEqual(base);
    expect(urlGeneration).toBe(GENERATION); // still on the generation's version
  });
});

// --- D2.3: doors and windows ---------------------------------------------------------------

const keyId = (key: string) => bySemanticKey(base, key).id;
const shown = (id: string) => useBuildingStore.getState().index?.elementsById.get(id);
const changes = () => screen.getByRole("toolbar", { name: "Plan editing" });

/** Plan centre of what the plan draws for an element (its opening symbol), model meters. */
function planCenter(id: string): Vector3 | null {
  const index = useBuildingStore.getState().index!;
  const box = new Box3();
  for (const level of index.levels) {
    for (const g of buildPlanDrawing(index, level.id).groups) {
      if (g.elementId !== id) continue;
      for (const item of g.items) {
        if (item.kind === "poly")
          for (const [x, y] of item.pts) box.expandByPoint(new Vector3(x, y, 0));
      }
    }
  }
  return box.isEmpty() ? null : box.getCenter(new Vector3());
}

function sceneCenter(id: string): Vector3 | null {
  const box = sceneBox(id);
  return box.isEmpty() ? null : box.getCenter(new Vector3());
}

/** Gaps between the wall's poché panels in the plan, along the wall (u from its start). */
function planWallGaps(wall: Wall): [number, number][] {
  const index = useBuildingStore.getState().index!;
  const spans: [number, number][] = [];
  for (const g of buildPlanDrawing(index, wall.level_id!).groups) {
    if (g.elementId !== wall.id || g.role !== "wall") continue;
    for (const item of g.items) {
      if (item.kind !== "poly") continue;
      const us = item.pts.map((p) => wallLocal(wall, p)[0]);
      spans.push([Math.min(...us), Math.max(...us)]);
    }
  }
  spans.sort((a, b) => a[0] - b[0]);
  const gaps: [number, number][] = [];
  for (let i = 1; i < spans.length; i++) {
    if (spans[i][0] - spans[i - 1][1] > 1e-3) gaps.push([spans[i - 1][1], spans[i][0]]);
  }
  return gaps;
}

/**
 * The opening is where the model says: the plan leaves exactly its span open in the wall's
 * poché (the 3D wall uses the same panel rule) and its 3D meshes stand centred in that span.
 */
function expectOpeningAt(id: string, wallKey: string, offset: number) {
  const el = shown(id) as Door | Window;
  expect(el.position.x).toBeCloseTo(offset, 6);
  const host = useBuildingStore.getState().index!.hostOf.get(id)!;
  expect(host.semantic_key).toBe(wallKey);
  const span: [number, number] = [offset, offset + el.dimensions.width];
  const gap = planWallGaps(host).find(([a, b]) => b > span[0] && a < span[1]);
  expect(gap?.[0]).toBeCloseTo(span[0], 3);
  expect(gap?.[1]).toBeCloseTo(span[1], 3);
  const c = sceneCenter(id)!;
  const [u, v] = wallLocal(host, [c.x, c.y]);
  expect(u).toBeCloseTo(offset + el.dimensions.width / 2, 2);
  expect(Math.abs(v)).toBeLessThanOrEqual(host.dimensions.thickness);
}

function expectGone(id: string) {
  expect(shown(id)).toBeUndefined();
  expect(planCenter(id)).toBeNull();
  expect(sceneCenter(id)).toBeNull();
}

/** Plan pointer events at a model point: the SVG is given its viewBox size in pixels. */
function pointerAt(x: number, y: number) {
  const svg = screen.getByRole("img", { name: /floor plan/ }) as unknown as SVGSVGElement;
  const [vx, vy, vw, vh] = svg.getAttribute("viewBox")!.split(" ").map(Number);
  svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: vw, height: vh }) as DOMRect;
  svg.setPointerCapture = () => undefined;
  // 1:100 -> 10 paper mm per model meter, +y north is up the sheet.
  return { svg, clientX: x * 10 - vx, clientY: -y * 10 - vy };
}

describe("door and window edits stay in sync with the 3D model", () => {
  it("moves, adds and removes openings, undoes and redoes, saves and reloads", async () => {
    const door = keyId("door:ent_corr");
    const gone = keyId("window:ent");
    const page = openPage();
    await screen.findByTestId("3d");
    await userEvent.click(screen.getByRole("button", { name: "Floor plan" }));

    // 1. Move a door along its wall (position field).
    act(() => useSelectionStore.getState().select(door));
    const position = await screen.findByLabelText("Position");
    expect(position).toHaveValue(1.2);
    await userEvent.clear(position);
    await userEvent.type(position, "2");
    await userEvent.click(screen.getByRole("button", { name: "Move" }));
    await waitFor(() => expect(changes()).toHaveTextContent("1 change"));
    expectOpeningAt(door, "wall:G-I1", 2);

    // 2. Add a window to the west wall by clicking it.
    act(() => useSelectionStore.getState().select(null));
    await userEvent.click(screen.getByRole("button", { name: "+ Window" }));
    expect(screen.getByRole("group", { name: "Add a window" })).toBeInTheDocument();
    const west = bySemanticKey(base, "wall:G-W") as Wall;
    const [px, py] = wallPoint(west, 7.5);
    const { svg, clientX, clientY } = pointerAt(px, py);
    fireEvent.pointerMove(svg, { clientX, clientY });
    expect(await screen.findByTestId("opening-ghost")).toBeInTheDocument();
    expect(await screen.findByText(/click to place/)).toBeInTheDocument();
    fireEvent.pointerDown(svg, { clientX, clientY, button: 0 });
    fireEvent.pointerUp(svg, { clientX, clientY, button: 0 });
    await waitFor(() => expect(changes()).toHaveTextContent("2 changes"));
    const added = "d0000000-0000-4000-8000-000000000001";
    expect(useSelectionStore.getState().selectedId).toBe(added); // ready to adjust
    expect(useEditStore.getState().placing).toBeNull();
    const win = shown(added) as Window;
    expectOpeningAt(added, "wall:G-W", 7.5 - win.dimensions.width / 2);

    // 3. Remove a window.
    act(() => useSelectionStore.getState().select(gone));
    await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(changes()).toHaveTextContent("3 changes"));
    expectGone(gone);
    expect(useSelectionStore.getState().selectedId).toBeNull();

    // Undo brings it back, redo removes it again.
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(shown(gone)).toBeDefined());
    expectOpeningAt(gone, "wall:G-S", 0.3);
    await userEvent.click(screen.getByRole("button", { name: "Redo" }));
    await waitFor(() => expectGone(gone));

    // 4. Save: one new version on v1; v1 unchanged.
    await userEvent.click(screen.getByRole("button", { name: "Save version" }));
    await waitFor(() => expect(shownVersion().selectedOptions[0].textContent).toMatch(/^v2 /));
    const saved = api.versions[1];
    expect(saved.parent_version_id).toBe(V1);
    expect(api.versions[0].model).toEqual(base);
    const stored = saved.model as BuildingModel;
    expect(stored.elements.find((e) => e.id === gone)).toBeUndefined();
    expect((stored.elements.find((e) => e.id === door) as Door).position.x).toBe(2);
    expect(stored.elements.find((e) => e.id === added)).toBeDefined();
    expect(useBuildingStore.getState().index!.model).toEqual(stored);

    // 5. Reload: the same openings in the plan and in 3D.
    page.unmount();
    openPage();
    await waitFor(() => expect(shownVersion().selectedOptions[0].textContent).toMatch(/^v2 /));
    await waitFor(() => expect(shown(added)).toBeDefined());
    expectOpeningAt(door, "wall:G-I1", 2);
    expectOpeningAt(added, "wall:G-W", 7.5 - win.dimensions.width / 2);
    expectGone(gone);

    // Downloads (SVG; PNG and PDF are made from the same SVG) show the stored v2.
    const info = {
      projectName: "Sync test",
      versionLabel: "v2",
      date: "2026-10-27",
      disclaimer: "",
    };
    const sheets = buildPlanSheets(useBuildingStore.getState().index!, info);
    expect(sheets.map((s) => s.svg)).toEqual(
      buildPlanSheets(parseBuildingModel(stored), info).map((s) => s.svg),
    );
    const drawn = sheets.flatMap((s) => s.drawing.groups.map((g) => g.elementId));
    expect(drawn).toContain(added);
    expect(drawn).not.toContain(gone);
  }, 60_000); // builds the whole scene many times

  it("refuses an opening over another one and leaves the model alone; discard restores", async () => {
    const win = keyId("window:ent");
    openPage();
    await screen.findByTestId("3d");
    await userEvent.click(screen.getByRole("button", { name: "Floor plan" }));
    act(() => useSelectionStore.getState().select(win));
    const position = await screen.findByLabelText("Position");
    const before = useBuildingStore.getState().index!.model;
    await userEvent.clear(position);
    await userEvent.type(position, "1"); // onto the front door
    await userEvent.click(screen.getByRole("button", { name: "Move" }));
    expect(await screen.findByText(/would make the design invalid/)).toBeInTheDocument();
    expect(changes()).toHaveTextContent("No changes");
    expect(useBuildingStore.getState().index!.model).toBe(before);
    expectOpeningAt(win, "wall:G-S", 0.3);

    // A valid slide with the arrow key, then Discard: back to the stored model.
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    fireEvent.keyDown(window, { key: "ArrowLeft" }); // the wall runs east: west = smaller offset
    await waitFor(() => expect(changes()).toHaveTextContent("1 change"));
    expectOpeningAt(win, "wall:G-S", 0.25);
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(changes()).toHaveTextContent("No changes");
    expect(useBuildingStore.getState().index!.model).toEqual(base);
    expectOpeningAt(win, "wall:G-S", 0.3);
    expect(api.saves).toBe(0);
  }, 30_000);
});

describe("drawingVersionLabel", () => {
  it("marks drawings of a plan with unsaved edits", () => {
    const v = { number: 3, label: "Plan edits on v2" };
    expect(drawingVersionLabel(v)).toBe("v3 · Plan edits on v2");
    expect(drawingVersionLabel(v, 1)).toBe("v3 · Plan edits on v2 + 1 unsaved change");
    expect(drawingVersionLabel(v, 2)).toBe("v3 · Plan edits on v2 + 2 unsaved changes");
  });
});
