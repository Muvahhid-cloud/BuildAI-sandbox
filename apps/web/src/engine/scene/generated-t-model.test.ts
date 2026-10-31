import { describe, expect, it } from "vitest";

import { computeWallJoins } from "../builders/wall-layout";
import { axisOf } from "../math/transform";
import { parseBuildingModel } from "../model/parse";
import { EPS, type Wall } from "../model/types";
import { generatedTModelJson } from "../test-fixtures";
import { buildScene } from "./build-scene";

/**
 * Design Intelligence V1.3: a T-shaped footprint from the layout engine (reference spec 12,
 * data/fixtures/generated-t-house.model.json) goes through the unchanged 3D engine; both inside
 * corners of the T close without a gap or double wall volume.
 */
describe("T-shaped generated BuildingModel through the 3D engine", () => {
  const index = parseBuildingModel(generatedTModelJson());
  const scene = buildScene(index);
  const walls = index.model.elements.filter((e): e is Wall => e.type === "wall");
  const house = walls.filter((w) => w.semantic_key.startsWith("wall:ext:"));
  const ends = new Map(house.map((w) => [w.id, axisOf(w)]));
  const cross = (a: Wall, b: Wall) => {
    const p = ends.get(a.id)!;
    const q = ends.get(b.id)!;
    const u = [p.end[0] - p.start[0], p.end[1] - p.start[1]];
    const v = [q.end[0] - q.start[0], q.end[1] - q.start[1]];
    return { c: u[0] * v[1] - u[1] * v[0], scale: Math.hypot(u[0], u[1]) * Math.hypot(v[0], v[1]) };
  };
  const next = (w: Wall) =>
    house.find((o) => {
      const a = ends.get(w.id)!.end;
      const b = ends.get(o.id)!.start;
      return Math.hypot(a[0] - b[0], a[1] - b[1]) < EPS;
    })!;

  it("builds every element into finite geometry that maps back to it", () => {
    for (const el of index.model.elements) {
      const parts = scene.byElement.get(el.id) ?? [];
      expect(parts.length, `${el.type} ${el.name}`).toBeGreaterThan(0);
      for (const d of parts) {
        expect(d.elementId).toBe(el.id);
        const pos = d.geometry.getAttribute("position").array as Float32Array;
        expect(Array.from(pos).every(Number.isFinite), `${el.name} has NaN vertices`).toBe(true);
      }
    }
  });

  it("has a closed eight-cornered envelope with two inside corners", () => {
    expect(house).toHaveLength(8);
    const turns = house.map((w) => {
      const { c, scale } = cross(w, next(w));
      return Math.abs(c) < EPS * scale ? 0 : Math.sign(c);
    });
    expect(turns.filter((t) => t > 0)).toHaveLength(6);
    expect(turns.filter((t) => t < 0)).toHaveLength(2);
  });

  it("closes both inside corners: arriving wall extends, leaving wall trims", () => {
    const joins = computeWallJoins(walls);
    const inside = house.filter((w) => {
      const { c, scale } = cross(w, next(w));
      return c < -EPS * scale; // w arrives at an inside corner
    });
    expect(inside).toHaveLength(2);
    for (const arriving of inside) {
      const leaving = next(arriving);
      const half = arriving.dimensions.thickness / 2;
      expect(joins.get(arriving.id)!.end).toBeCloseTo(half, 9);
      expect(joins.get(leaving.id)!.start).toBeCloseTo(-half, 9);
    }
  });

  it("has a main roof and a wing roof", () => {
    const keys = index.model.elements
      .filter((e) => e.type === "roof")
      .map((r) => r.semantic_key)
      .sort();
    expect(keys).toEqual(["roof:garage", "roof:main", "roof:wing"]);
  });
});
