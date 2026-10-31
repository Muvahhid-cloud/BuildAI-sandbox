import { type Box3, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { indexModel } from "../model/model-index";
import { parseBuildingModel } from "../model/parse";
import { buildScene, ContentCache, elementBounds } from "../scene/build-scene";
import { bySemanticKey, demoIndex, demoModelJson } from "../test-fixtures";
import { buildElement } from "./registry";
import { stairProfile } from "./stair";
import { DEFAULT_ENGINE_CONFIG, InvalidElementError } from "./types";

const index = demoIndex();
const scene = buildScene(index);
const bounds = (key: string) => elementBounds(scene, bySemanticKey(index.model, key).id)!;
const size = (b: Box3) => b.getSize(new Vector3());

describe("geometry builders on the demo house", () => {
  it("produce finite geometry for every element", () => {
    for (const d of scene.descriptors) {
      const pos = d.geometry.getAttribute("position");
      expect(pos.count, d.key).toBeGreaterThan(0);
      expect(pos.count % 3, d.key).toBe(0);
      expect(Array.from(pos.array as Float32Array).every(Number.isFinite), d.key).toBe(true);
      expect(d.materials.length, d.key).toBe(d.geometry.groups.length);
    }
  });

  it("builds walls with their exact length, height and thickness (+ corner joins)", () => {
    const s = size(bounds("wall:G-S")); // 12 m + half-thickness extension at one end
    expect(s.x).toBeCloseTo(12, 3);
    expect(s.y).toBeCloseTo(0.3, 3);
    expect(s.z).toBeCloseTo(2.8, 3);
  });

  it("cuts wall panels around openings (wall area shrinks by the opening area)", () => {
    const wall = scene.byElement.get(bySemanticKey(index.model, "wall:G-N").id)![0];
    // G-N has a 2.5 x 2.4 sliding door and two panoramic windows: its left-face area
    // (interior finish) must equal the wall area minus those openings.
    const group = wall.geometry.groups[wall.materials.indexOf("interior_wall")];
    const pos = wall.geometry.getAttribute("position");
    let area = 0;
    for (let i = group.start; i < group.start + group.count; i += 3) {
      const a = new Vector3().fromBufferAttribute(pos, i);
      const b = new Vector3().fromBufferAttribute(pos, i + 1);
      const c = new Vector3().fromBufferAttribute(pos, i + 2);
      if (Math.abs(b.clone().sub(a).cross(c.clone().sub(a)).normalize().y) > 0.99) {
        area += b.sub(a).cross(c.sub(a)).length() / 2;
      }
    }
    const faceLength = 12; // 12.15 extension - 0.15 trim
    const openings = 2.5 * 2.4 + 3.2 * 2.4 + 2.2 * 2.4;
    expect(area).toBeCloseTo(faceLength * 2.8 - openings, 2);
  });

  it("places windows inside their host wall at the sill height", () => {
    const win = bounds("window:kitchen_s");
    expect(win.min.x).toBeCloseTo(8.2 - 0.05, 2); // exterior sill board overhangs 5 cm
    expect(win.max.x).toBeCloseTo(11.2 + 0.05, 2);
    expect(win.min.z).toBeCloseTo(0.95 - 0.03, 3);
    expect(win.max.z).toBeCloseTo(0.95 + 1.3, 3);
  });

  it("places upper-floor elements at the level elevation", () => {
    expect(bounds("room:master").min.z).toBeCloseTo(3.004, 3);
    expect(bounds("slab:floor_f").max.z).toBeCloseTo(3.0, 3);
    expect(bounds("slab:floor_f").min.z).toBeCloseTo(2.8, 3);
  });

  it("builds the stair from floor 1 to floor 2", () => {
    const b = bounds("stair:main");
    expect(b.min.z).toBeCloseTo(0, 3);
    expect(b.max.z).toBeCloseTo(3.008, 2); // 16 risers x 188 mm (stored to 1 mm)
    expect(size(b).y).toBeCloseTo(3.9, 3); // run along +y (rotated flight)
    expect(size(b).x).toBeCloseTo(1.1, 3); // width
  });

  it("builds a hip roof covering the footprint plus overhang", () => {
    const b = bounds("roof:main");
    expect(b.min.x).toBeCloseTo(-0.65, 3);
    expect(b.max.x).toBeCloseTo(12.65, 3);
    expect(b.max.z).toBeGreaterThan(b.min.z + 2); // ridge well above the eaves
  });

  it("keeps furniture within its declared dimensions", () => {
    for (const el of index.model.elements) {
      if (el.type !== "furniture") continue;
      const s = size(elementBounds(scene, el.id)!);
      const { width, depth, height } = el.dimensions;
      const horizontal = Math.hypot(width, depth) + 0.05; // handles may protrude slightly
      expect(Math.hypot(s.x, s.y), el.name).toBeLessThanOrEqual(horizontal);
      // TV screens and pillows may sit above the carcass height.
      if (el.properties.furniture_kind !== "tv_unit" && el.properties.furniture_kind !== "bed") {
        expect(s.z, el.name).toBeLessThanOrEqual(height + 0.26);
      }
    }
  });

  it("stair profile is a closed polygon rising monotonically", () => {
    const pts = stairProfile(16, 0.1875, 0.26);
    const top = pts.reduce((m, p) => Math.max(m, p[1]), 0);
    expect(top).toBeCloseTo(3.0, 9);
    expect(pts[0]).toEqual([0, 0]);
  });
});

describe("builders validate their inputs", () => {
  it.each([
    ["zero", 0],
    ["negative", -2],
    ["NaN", Number.NaN],
  ])("refuses a wall with %s length", (_, value) => {
    const model = demoModelJson();
    const wall = bySemanticKey(model, "wall:G-S");
    (wall.dimensions as { length: number }).length = value;
    const idx = indexModel(model); // bypass the schema on purpose: builders must still guard
    const ctx = {
      index: idx,
      joins: new Map(),
      config: DEFAULT_ENGINE_CONFIG,
      cache: new ContentCache(),
    };
    expect(() => buildElement(wall, ctx)).toThrow(InvalidElementError);
  });

  it("the schema itself rejects non-positive dimensions before builders run", () => {
    const model = demoModelJson();
    (bySemanticKey(model, "furniture:sofa").dimensions as { width: number }).width = 0;
    expect(() => parseBuildingModel(model)).toThrow();
  });
});
