import { describe, expect, it } from "vitest";

import { bySemanticKey, demoIndex } from "../test-fixtures";
import type { Wall } from "../model/types";
import { computeWallJoins, wallPanels } from "./wall-layout";

describe("wallPanels", () => {
  it("covers the wall area minus openings exactly, without overlaps", () => {
    const openings = [
      { u0: 1, u1: 2, z0: 0, z1: 2.1 }, // door
      { u0: 3, u1: 4.5, z0: 0.9, z1: 2.3 }, // window
    ];
    const panels = wallPanels(0, 6, 2.8, openings);
    const area = panels.reduce((s, p) => s + (p.u1 - p.u0) * (p.z1 - p.z0), 0);
    const openingArea = 1 * 2.1 + 1.5 * 1.4;
    expect(area).toBeCloseTo(6 * 2.8 - openingArea, 9);
    expect(panels.map((p) => p.kind)).toEqual(["full", "lintel", "full", "sill", "lintel", "full"]);
  });

  it("clamps openings to the wall and handles openings at the ends", () => {
    const panels = wallPanels(0, 3, 2.5, [{ u0: -0.5, u1: 1, z0: 0, z1: 2.5 }]);
    expect(panels).toEqual([{ kind: "full", u0: 1, u1: 3, z0: 0, z1: 2.5 }]);
  });

  it("returns one full panel for a wall without openings", () => {
    expect(wallPanels(-0.15, 12.15, 2.8, [])).toEqual([
      { kind: "full", u0: -0.15, u1: 12.15, z0: 0, z1: 2.8 },
    ]);
  });
});

describe("computeWallJoins (demo house)", () => {
  const index = demoIndex();
  const walls = index.model.elements.filter((e): e is Wall => e.type === "wall");
  const joins = computeWallJoins(walls);
  const join = (key: string) => joins.get(bySemanticKey(index.model, key).id)!;

  it("closes exterior corners as a pinwheel (arriving wall extends, leaving wall trims)", () => {
    for (const side of ["S", "E", "N", "W"]) {
      expect(join(`wall:G-${side}`)).toEqual({ start: -0.15, end: 0.15 });
      expect(join(`wall:F-${side}`)).toEqual({ start: -0.15, end: 0.15 });
    }
  });

  it("trims interior walls at T-junctions to the face of the wall they meet", () => {
    expect(join("wall:G-I2").start).toBeCloseTo(-0.15); // meets the south facade
    expect(join("wall:G-I3").end).toBeCloseTo(-0.06); // meets interior wall G-I5
  });

  it("closes interior L-corners", () => {
    expect(join("wall:G-I2").end).toBeCloseTo(0.06); // G-I2 ends where G-I3 starts
    expect(join("wall:G-I3").start).toBeCloseTo(-0.06);
  });

  it("is independent of input order", () => {
    const reversed = computeWallJoins([...walls].reverse());
    expect([...reversed.entries()].sort()).toEqual([...joins.entries()].sort());
  });
});
