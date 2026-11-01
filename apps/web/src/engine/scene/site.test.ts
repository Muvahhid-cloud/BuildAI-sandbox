import { Box3, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { MATERIAL_PRESETS } from "../materials/library";
import { openingMatrix } from "../math/transform";
import { parseBuildingModel } from "../model/parse";
import {
  demoModelJson,
  generatedLModelJson,
  generatedModelJson,
  generatedTModelJson,
} from "../test-fixtures";
import { buildScene } from "./build-scene";
import { buildSiteMesh, groundDiscGeometry, planSite, siteRadius } from "./site";

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

describe("site plan (V2)", () => {
  const cases = [
    ["demo", demoModelJson],
    ["generated", generatedModelJson],
    ["generated L", generatedLModelJson],
    ["generated T", generatedTModelJson],
  ] as const;

  const planOf = (json: ReturnType<typeof demoModelJson>) => {
    const index = parseBuildingModel(json);
    return {
      index,
      plan: planSite(index, buildScene(index).bounds),
      bounds: buildScene(index).bounds,
    };
  };

  it.each(cases)("is deterministic and independent of element order (%s)", (_, json) => {
    const a = planOf(json()).plan;
    const b = planOf(json()).plan;
    expect(b).toEqual(a);
    const reversed = json();
    reversed.elements = [...reversed.elements].reverse();
    expect(planOf(reversed).plan).toEqual(a);
    const mesh = (p: typeof a) =>
      Array.from(buildSiteMesh(p).geometry.getAttribute("position").array);
    expect(mesh(planOf(json()).plan)).toEqual(mesh(a));
  });

  it.each(cases)("leads a path from the entrance door to the street (%s)", (_, json) => {
    const { index, plan } = planOf(json());
    const entrance = [...index.elementsById.values()].find(
      (e) => e.type === "door" && e.properties.door_kind === "entrance",
    )!;
    const path = plan.strips.find((s) => s.kind === "path")!;
    expect(path.doorId).toBe(entrance.id);
    const host = index.hostOf.get(entrance.id)!;
    if (host.type !== "wall" || entrance.type !== "door") throw new Error("fixture");
    // Starts at the centre of the door on the facade face, ends on the street edge.
    const m = openingMatrix(entrance, host, index);
    const door = new Vector3(entrance.dimensions.width / 2, -host.dimensions.thickness / 2, 0);
    door.applyMatrix4(m);
    expect(path.points[0][0]).toBeCloseTo(door.x, 3);
    expect(path.points[0][1]).toBeCloseTo(door.y, 3);
    expect(path.points.at(-1)![1]).toBe(plan.streetY);
    expect(path.width).toBeGreaterThanOrEqual(entrance.dimensions.width);
  });

  it.each(cases)("adds a driveway only for a garage door (%s)", (_, json) => {
    const { index, plan } = planOf(json());
    const garages = [...index.elementsById.values()].filter(
      (e) => e.type === "door" && e.properties.door_kind === "garage",
    );
    const driveways = plan.strips.filter((s) => s.kind === "driveway");
    expect(driveways.map((d) => d.doorId).sort()).toEqual(garages.map((g) => g.id).sort());
    for (const d of driveways) expect(d.points.at(-1)![1]).toBe(plan.streetY);
  });

  it.each(cases)("keeps plants off the building, the path and the driveway (%s)", (_, json) => {
    const { plan, bounds } = planOf(json());
    expect(plan.plants.some((p) => p.kind === "tree")).toBe(true);
    for (const p of plan.plants) {
      const inside =
        p.x > bounds.min.x && p.x < bounds.max.x && p.y > bounds.min.y && p.y < bounds.max.y;
      expect(inside, `${p.kind} ${p.slot}`).toBe(false);
      for (const s of plan.strips) {
        for (let i = 0; i + 1 < s.points.length; i++) {
          const [[ax, ay], [bx, by]] = [s.points[i], s.points[i + 1]];
          const k = Math.max(
            0,
            Math.min(
              1,
              ((p.x - ax) * (bx - ax) + (p.y - ay) * (by - ay)) /
                ((bx - ax) ** 2 + (by - ay) ** 2 || 1),
            ),
          );
          const dist = Math.hypot(p.x - (ax + k * (bx - ax)), p.y - (ay + k * (by - ay)));
          expect(dist, `${p.kind} ${p.slot} vs ${s.kind}`).toBeGreaterThan(s.width / 2 + 0.5);
        }
      }
      expect(p.height).toBeGreaterThan(0.5);
    }
  });

  it("leaves the fence open where the path and the driveway reach the street", () => {
    const { plan } = planOf(generatedModelJson());
    for (const s of plan.strips) {
      const x = s.points.at(-1)![0];
      const blocked = plan.fence.some(([[a], [b]]) => x > a - 1e-9 && x < b + 1e-9);
      expect(blocked, s.kind).toBe(false);
    }
    expect(plan.fence.length).toBeGreaterThanOrEqual(2);
  });

  it("draws paving with UVs in meters and the fence from library materials", () => {
    const { plan } = planOf(demoModelJson());
    const mesh = buildSiteMesh(plan);
    expect(mesh.materials).toEqual(["site_paving", "wood"]);
    for (const id of mesh.materials) expect(MATERIAL_PRESETS.has(id), id).toBe(true);
    const pos = mesh.geometry.getAttribute("position");
    const uv = mesh.geometry.getAttribute("uv");
    for (let i = 0; i < 30; i += 3) {
      const dPos = Math.hypot(
        pos.getX(i) - pos.getX(i + 1),
        pos.getY(i) - pos.getY(i + 1),
        pos.getZ(i) - pos.getZ(i + 1),
      );
      const dUv = Math.hypot(uv.getX(i) - uv.getX(i + 1), uv.getY(i) - uv.getY(i + 1));
      expect(dUv).toBeCloseTo(dPos, 4);
    }
  });
});
