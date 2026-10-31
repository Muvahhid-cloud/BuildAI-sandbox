import { describe, expect, it } from "vitest";

import { parseBuildingModel } from "../model/parse";
import type { ModelIndex } from "../model/model-index";
import type { P2 } from "../math/polygon";
import type { Door, Room, Wall } from "../model/types";
import {
  demoModelJson,
  generatedLModelJson,
  generatedModelJson,
  generatedTModelJson,
} from "../test-fixtures";
import { buildPlanDrawing, formatArea } from "./plan";
import { hatchLines, insidePolygon, labelPoint, placeLabel } from "./plan-math";
import type { DrawGroup, DrawItem } from "./primitives";
import { buildPlanSheets, PLAN_SCALES } from "./sheet";
import { paperBox, renderPlanContent, renderPlanSvg } from "./svg";
import { doorItems, roomOutline } from "./symbols";

const FIXTURES: [string, () => ModelIndex][] = [
  ["demo", () => parseBuildingModel(demoModelJson())],
  ["generated 2-storey", () => parseBuildingModel(generatedModelJson())],
  ["generated L", () => parseBuildingModel(generatedLModelJson())],
  ["generated T", () => parseBuildingModel(generatedTModelJson())],
];

const INFO = {
  projectName: "Test <house> & co",
  versionLabel: "v1 · fixture",
  date: "2026-10-26",
  disclaimer: "Conceptual only.",
};

function texts(groups: readonly DrawGroup[]): string[] {
  return groups.flatMap((g) => g.items).flatMap((i) => (i.kind === "text" ? [i.text] : []));
}

function polyArea(pts: readonly P2[]): number {
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % pts.length];
    a += x0 * y1 - x1 * y0;
  }
  return Math.abs(a / 2);
}

describe.each(FIXTURES)("plan drawing: %s", (_, load) => {
  const index = load();

  it("is deterministic", () => {
    for (const level of index.levels) {
      const a = renderPlanContent(buildPlanDrawing(index, level.id), { interactive: true });
      const b = renderPlanContent(buildPlanDrawing(load(), level.id), { interactive: true });
      expect(a).toBe(b);
      expect(a).not.toMatch(/NaN|Infinity|undefined/);
    }
  });

  it("labels every room with its name and the model's area", () => {
    for (const level of index.levels) {
      const drawing = buildPlanDrawing(index, level.id);
      const rooms = (index.elementsByLevel.get(level.id) ?? []).filter(
        (e): e is Room => e.type === "room",
      );
      for (const room of rooms) {
        const label = drawing.groups.find((g) => g.role === "label" && g.elementId === room.id);
        expect(label, room.name).toBeDefined();
        expect(texts([label!])).toEqual([room.name, `${formatArea(room.dimensions.area)} m²`]);
      }
    }
  });

  it("draws every element of the level, each group mapped to one element", () => {
    for (const level of index.levels) {
      const drawing = buildPlanDrawing(index, level.id);
      const drawn = new Set(drawing.groups.map((g) => g.elementId));
      for (const el of index.elementsByLevel.get(level.id) ?? []) {
        if (
          el.type === "roof" ||
          (el.type === "slab" &&
            el.properties.slab_kind !== "balcony" &&
            el.properties.holes.length === 0)
        )
          continue;
        expect(drawn.has(el.id), `${el.type} ${el.name}`).toBe(true);
      }
      for (const g of drawing.groups) {
        if (g.elementId !== null) expect(index.elementsById.has(g.elementId)).toBe(true);
        else expect(g.role).toBe("dimension");
      }
    }
  });

  it("cuts walls with gaps exactly as wide as their openings", () => {
    const level = index.levels[0];
    const drawing = buildPlanDrawing(index, level.id);
    for (const g of drawing.groups.filter((x) => x.role === "wall")) {
      const wall = index.elementsById.get(g.elementId!) as Wall;
      const solid = g.items.reduce(
        (sum, it) => sum + (it.kind === "poly" ? polyArea(it.pts) : 0),
        0,
      );
      const openings = (index.hostedOpenings.get(wall.id) ?? []).reduce(
        (sum, o) => sum + o.dimensions.width,
        0,
      );
      const t = wall.dimensions.thickness;
      // Joins change the length by at most one thickness at each end.
      expect(solid / t).toBeGreaterThan(wall.dimensions.length - openings - 2 * t - 1e-6);
      expect(solid / t).toBeLessThan(wall.dimensions.length - openings + 2 * t + 1e-6);
    }
  });

  it("fits every level on an A3 sheet at a standard scale", () => {
    const sheets = buildPlanSheets(index, INFO);
    expect(sheets).toHaveLength(index.levels.length);
    for (const sheet of sheets) {
      expect(PLAN_SCALES).toContain(sheet.scale);
      expect(sheet.svg.startsWith("<svg")).toBe(true);
      expect(sheet.svg).toContain("Test &lt;house&gt; &amp; co");
      expect(sheet.svg).toContain("NOT FOR CONSTRUCTION");
      expect(sheet.svg).toContain("Conceptual only.");
      expect(sheet.svg).not.toMatch(/NaN|Infinity|undefined|data-element-id|fill-opacity="0"/);
    }
  });
});

describe("plan drawing details", () => {
  it("opens doors into the room they connect to", () => {
    const index = parseBuildingModel(generatedLModelJson());
    const front = index.model.elements.find(
      (e): e is Door => e.type === "door" && e.semantic_key === "door:front",
    )!;
    const host = index.hostOf.get(front.id)!;
    const entrance = index.elementsById.get(
      front.relationships.find((r) => r.kind === "connects")!.target_id,
    ) as Room;
    const items = doorItems(front, host, index);
    const leaf = items.filter(
      (i): i is Extract<DrawItem, { kind: "poly" }> => i.kind === "poly",
    )[2];
    expect(insidePolygon(leaf.pts[1], roomOutline(entrance))).toBe(true);
  });

  it("dimensions the overall footprint in millimeters", () => {
    const index = parseBuildingModel(generatedLModelJson());
    const drawing = buildPlanDrawing(index, index.levels[0].id);
    const dims = texts(drawing.groups.filter((g) => g.role === "dimension"));
    // The L footprint is 17.4 × 16.8 m over the outer wall faces (ground slab outline).
    expect(dims).toContain("17400");
    expect(dims).toContain("16800");
    expect(dims.every((t) => /^\d+$/.test(t))).toBe(true);
  });

  it("shows the stair on both levels, up from below and down from above", () => {
    const index = parseBuildingModel(generatedModelJson());
    const stair = index.model.elements.find((e) => e.type === "stair")!;
    for (const level of index.levels) {
      const drawing = buildPlanDrawing(index, level.id);
      expect(drawing.groups.some((g) => g.role === "stair" && g.elementId === stair.id)).toBe(true);
    }
  });

  it("uses the scale it was built for", () => {
    const index = parseBuildingModel(generatedModelJson());
    const at100 = buildPlanDrawing(index, index.levels[0].id, { scale: 100 });
    const at200 = buildPlanDrawing(index, index.levels[0].id, { scale: 200 });
    const w100 = paperBox(at100.extent, 100).width;
    const w200 = paperBox(at200.extent, 200).width;
    expect(w100 / w200).toBeCloseTo(2, 6);
    expect(renderPlanSvg(at100)).toMatch(/^<svg[^>]+width="[\d.]+mm"/);
  });

  it("can leave out furniture and dimensions", () => {
    const index = parseBuildingModel(generatedLModelJson());
    const d = buildPlanDrawing(index, index.levels[0].id, { furniture: false, dimensions: false });
    expect(d.groups.some((g) => g.role === "furniture" || g.role === "dimension")).toBe(false);
  });
});

describe("plan math", () => {
  const L: P2[] = [
    [0, 0],
    [6, 0],
    [6, 2],
    [2, 2],
    [2, 6],
    [0, 6],
  ];

  it("clips hatch lines to the polygon", () => {
    const lines = hatchLines(L, 0.5);
    expect(lines.length).toBeGreaterThan(0);
    for (const [a, b] of lines) {
      expect(insidePolygon(a, L)).toBe(true);
      expect(insidePolygon(b, L)).toBe(true);
      expect(insidePolygon([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], L)).toBe(true);
    }
    // x = 1 crosses the full height, x = 4 only the bottom bar.
    const at = (x: number) => lines.find(([a]) => Math.abs(a[0] - x) < 1e-9)!;
    expect(Math.abs(at(1.25)[1][1] - at(1.25)[0][1])).toBeCloseTo(6);
    expect(Math.abs(at(4.25)[1][1] - at(4.25)[0][1])).toBeCloseTo(2);
  });

  it("puts labels inside L-shaped rooms", () => {
    expect(insidePolygon(labelPoint(L), L)).toBe(true);
    const placed = placeLabel(L, 1.5, 0.6, [])!;
    expect(insidePolygon(placed.at, L)).toBe(true);
    expect(placeLabel(L, 9, 0.6, [])).toBeNull();
  });

  it("keeps labels clear of obstacles when there is room", () => {
    const room: P2[] = [
      [0, 0],
      [4, 0],
      [4, 4],
      [0, 4],
    ];
    const placed = placeLabel(room, 1, 0.5, [{ minX: 0, minY: 0, maxX: 4, maxY: 2.5 }])!;
    expect(placed.at[1]).toBeGreaterThan(2.5 + 0.25);
  });
});

describe("plan: picking doors and windows", () => {
  it("gives every opening an invisible pointer target in the interactive view only", () => {
    const index = parseBuildingModel(demoModelJson());
    const level = index.levels[0];
    const drawing = buildPlanDrawing(index, level.id);
    const openings = drawing.groups.filter((g) => g.role === "opening");
    expect(openings.length).toBeGreaterThan(0);
    for (const g of openings) {
      expect(g.items.filter((i) => i.kind === "poly" && i.fill === "hit")).toHaveLength(1);
    }
    // Downloads (non-interactive SVG) draw no pointer targets at all.
    expect(renderPlanContent(drawing)).not.toContain('fill-opacity="0"');
    expect(renderPlanContent(drawing, { interactive: true })).toContain('fill-opacity="0"');
  });
});
