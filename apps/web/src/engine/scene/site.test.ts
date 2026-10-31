import { Box3, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { groundDiscGeometry, siteRadius } from "./site";

describe("site ground", () => {
  it("has UVs in meters (equal to the local position)", () => {
    const g = groundDiscGeometry(50, 32);
    const pos = g.getAttribute("position");
    const uv = g.getAttribute("uv");
    for (let i = 0; i < pos.count; i++) {
      expect(uv.getX(i)).toBeCloseTo(pos.getX(i));
      expect(uv.getY(i)).toBeCloseTo(pos.getY(i));
    }
    let maxU = 0;
    for (let i = 0; i < uv.count; i++) maxU = Math.max(maxU, uv.getX(i));
    expect(maxU).toBeCloseTo(50);
  });

  it("is deterministic and scales with the building", () => {
    const small = new Box3(new Vector3(0, 0, 0), new Vector3(10, 10, 6));
    const big = new Box3(new Vector3(0, 0, 0), new Vector3(40, 30, 9));
    expect(siteRadius(small)).toBe(60);
    expect(siteRadius(big)).toBeGreaterThan(60);
    const a = groundDiscGeometry(60).getAttribute("uv").array;
    const b = groundDiscGeometry(60).getAttribute("uv").array;
    expect(Array.from(a)).toEqual(Array.from(b));
  });
});
