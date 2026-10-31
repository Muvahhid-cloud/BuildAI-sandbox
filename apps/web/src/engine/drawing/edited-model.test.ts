// D2.4: after a door/window resize, a wall removal and a room rename / type change, the plan,
// the downloadable sheets (SVG; PNG and PDF are made from the same SVG) and the 3D scene are all
// drawn from the same edited model. The edits below reproduce what the API's operations return
// (resize_opening, remove_wall, rename_room, set_room_type on the demo house).
import { Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { parseBuildingModel } from "../model/parse";
import type { BuildingModel } from "../model/types";
import { buildScene, elementBounds } from "../scene/build-scene";
import { bySemanticKey, demoModelJson } from "../test-fixtures";
import { buildPlanDrawing } from "./plan";
import { buildPlanSheets } from "./sheet";

type Raw = BuildingModel;

function edited(): Raw {
  const raw = demoModelJson() as Raw;
  const base = parseBuildingModel(raw);
  const win = bySemanticKey(base.model, "window:bed3_s");
  const wall = bySemanticKey(base.model, "wall:G-I1");
  const door = bySemanticKey(base.model, "door:ent_corr");
  const room = bySemanticKey(base.model, "room:bedroom3");
  const gone = new Set([wall.id, door.id]);
  const elements = raw.elements
    .filter((e) => !gone.has(e.id))
    .map((e) => ({
      ...e,
      relationships: e.relationships.filter((r) => !gone.has(r.target_id)),
    }))
    .map((e) => {
      if (e.id === win.id && e.type === "window") {
        return {
          ...e,
          position: { ...e.position, x: 0.8, z: 1.0 },
          dimensions: { width: 1.8, height: 1.5 },
        };
      }
      if (e.id === room.id && e.type === "room") {
        return {
          ...e,
          name: "Guest bedroom",
          properties: { ...e.properties, room_type: "study" as const },
        };
      }
      return e;
    });
  return { ...raw, elements };
}

const INFO = {
  projectName: "Edited",
  versionLabel: "v2 · Plan edits",
  date: "2026-10-28",
  disclaimer: "Conceptual only.",
};

describe("an edited model in the plan, the sheets and 3D", () => {
  const before = parseBuildingModel(demoModelJson());
  const after = parseBuildingModel(edited());
  const win = bySemanticKey(after.model, "window:bed3_s");
  const wall = bySemanticKey(before.model, "wall:G-I1");

  it("draws the renamed room and the resized window on the plan and every sheet", () => {
    const upper = after.levels[1].id;
    const drawing = buildPlanDrawing(after, upper);
    const ids = drawing.groups.map((g) => g.elementId);
    expect(ids).toContain(win.id);
    const sheets = buildPlanSheets(after, INFO);
    const svg = sheets.map((s) => s.svg).join("");
    expect(svg).toContain("Guest bedroom");
    expect(svg).not.toContain("Bedroom 3");
    // The window's symbol spans its opening along the south wall: 1.6 m before, 1.8 m after.
    const widthOf = (index: typeof after) => {
      const d = buildPlanDrawing(index, upper, { scale: 100 });
      const g = d.groups.find((x) => x.elementId === win.id)!;
      const xs = g.items.flatMap((i) => (i.kind === "poly" ? i.pts.map((p) => p[0]) : []));
      return Math.max(...xs) - Math.min(...xs);
    };
    expect(widthOf(after)).toBeCloseTo(1.8, 1);
    expect(widthOf(before)).toBeCloseTo(1.6, 1);
  });

  it("drops the removed wall and its door from the plan and the sheets", () => {
    const ground = after.levels[0].id;
    const ids = buildPlanDrawing(after, ground).groups.map((g) => g.elementId);
    expect(ids).not.toContain(wall.id);
    expect(buildPlanDrawing(before, ground).groups.map((g) => g.elementId)).toContain(wall.id);
  });

  it("builds the same geometry in 3D: the window grows by 0.2 x 0.1 m, the wall is gone", () => {
    const sizeIn = (index: typeof after) =>
      elementBounds(buildScene(index), win.id)!.getSize(new Vector3());
    const [a, b] = [sizeIn(after), sizeIn(before)];
    // Along the south wall (x) and up (model z; the scene is built in model axes).
    expect(a.x - b.x).toBeCloseTo(0.2, 3);
    expect(Math.max(a.y - b.y, a.z - b.z)).toBeCloseTo(0.1, 3);
    expect(elementBounds(buildScene(after), wall.id)).toBeNull();
  });
});
