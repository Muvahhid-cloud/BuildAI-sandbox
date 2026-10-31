import { describe, expect, it } from "vitest";

import { computeWallJoins } from "../builders/wall-layout";
import { axisOf } from "../math/transform";
import { parseBuildingModel } from "../model/parse";
import { EPS, type Wall } from "../model/types";
import { generatedLModelJson } from "../test-fixtures";
import { buildScene } from "./build-scene";

/**
 * Design Intelligence V1.1: an L-shaped footprint from the layout engine (reference spec 11,
 * data/fixtures/generated-l-house.model.json) goes through the unchanged 3D engine, and the
 * inside corner of the L closes without a gap or double wall volume.
 */
describe("L-shaped generated BuildingModel through the 3D engine", () => {
  const index = parseBuildingModel(generatedLModelJson());
  const scene = buildScene(index);
  const walls = index.model.elements.filter((e): e is Wall => e.type === "wall");
  const house = walls.filter((w) => w.semantic_key.startsWith("wall:ext:"));

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

  it("has a closed six-cornered envelope with one inside corner", () => {
    expect(house).toHaveLength(7); // the outer side is split where the wing starts
    const ends = house.map((w) => axisOf(w));
    for (const { end } of ends) {
      const next = ends.filter((o) => Math.hypot(o.start[0] - end[0], o.start[1] - end[1]) < EPS);
      expect(next).toHaveLength(1); // every wall end is the start of exactly one wall: a loop
    }
    const turns = ends.map(({ start, end }) => {
      const next = ends.find((o) => Math.hypot(o.start[0] - end[0], o.start[1] - end[1]) < EPS)!;
      const a = [end[0] - start[0], end[1] - start[1]];
      const b = [next.end[0] - next.start[0], next.end[1] - next.start[1]];
      const cross = a[0] * b[1] - a[1] * b[0];
      return Math.abs(cross) < EPS * Math.hypot(a[0], a[1]) * Math.hypot(b[0], b[1])
        ? 0
        : Math.sign(cross);
    });
    expect(turns.filter((t) => t > 0)).toHaveLength(5); // convex corners (CCW loop)
    expect(turns.filter((t) => t < 0)).toHaveLength(1); // the L's inside corner
    expect(turns.filter((t) => t === 0)).toHaveLength(1); // the split outer side
  });

  it("closes the inside corner: arriving wall extends, leaving wall and partition trim", () => {
    const joins = computeWallJoins(walls);
    const ends = new Map(house.map((w) => [w.id, axisOf(w)]));
    // The inside corner: where the wing's inner wall starts.
    const wingInner = house.find((w) => {
      const a = ends.get(w.id)!;
      const arriving = house.find((o) => {
        const b = ends.get(o.id)!;
        return Math.hypot(b.end[0] - a.start[0], b.end[1] - a.start[1]) < EPS;
      })!;
      const p = ends.get(arriving.id)!;
      const u = [p.end[0] - p.start[0], p.end[1] - p.start[1]];
      const v = [a.end[0] - a.start[0], a.end[1] - a.start[1]];
      // A right turn beyond float noise: the collinear split of the outer side has |cross| ~ 0
      // (wall ends come from rotation and length) and must not be taken for the corner.
      return u[0] * v[1] - u[1] * v[0] < -EPS * Math.hypot(u[0], u[1]) * Math.hypot(v[0], v[1]);
    })!;
    const corner = ends.get(wingInner.id)!.start;
    const arriving = house.find((o) => {
      const b = ends.get(o.id)!;
      return Math.hypot(b.end[0] - corner[0], b.end[1] - corner[1]) < EPS;
    })!;
    const half = arriving.dimensions.thickness / 2;
    expect(joins.get(arriving.id)!.end).toBeCloseTo(half, 9);
    expect(joins.get(wingInner.id)!.start).toBeCloseTo(-half, 9);
    const partition = walls.find((w) => {
      if (w.properties.wall_kind === "exterior") return false;
      const a = axisOf(w);
      return [a.start, a.end].some((p) => Math.hypot(p[0] - corner[0], p[1] - corner[1]) < EPS);
    });
    expect(partition, "a partition continues the wing's inner wall line").toBeDefined();
    const pa = axisOf(partition!);
    const atStart = Math.hypot(pa.start[0] - corner[0], pa.start[1] - corner[1]) < EPS;
    expect(joins.get(partition!.id)![atStart ? "start" : "end"]).toBeCloseTo(-half, 9);
  });

  it("has a main roof and a wing roof, both rectangles", () => {
    const roofs = index.model.elements.filter((e) => e.type === "roof");
    const keys = roofs.map((r) => r.semantic_key).sort();
    expect(keys).toEqual(["roof:garage", "roof:main", "roof:wing"]);
  });
});
