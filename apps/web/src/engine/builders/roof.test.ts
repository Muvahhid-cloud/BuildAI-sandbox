import { type BufferGeometry, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { parseBuildingModel } from "../model/parse";
import { buildScene } from "../scene/build-scene";
import { generatedModelJson, generatedTModelJson } from "../test-fixtures";
import { ROOF_TRIM, roofEnclosure } from "./roof";

function vertices(geometry: BufferGeometry, group: number): Vector3[] {
  const pos = geometry.getAttribute("position");
  const g = geometry.groups[group];
  const out: Vector3[] = [];
  for (let i = g.start; i < g.start + g.count; i++)
    out.push(new Vector3().fromBufferAttribute(pos, i));
  return out;
}

describe("roof detailing (V3)", () => {
  it("closes gable ends with the supporting wall's finishes, under the roof", () => {
    const index = parseBuildingModel(generatedTModelJson());
    const scene = buildScene(index);
    const gables = [...index.elementsById.values()].filter(
      (e) => e.type === "roof" && e.properties.roof_type === "gable",
    );
    expect(gables.length).toBeGreaterThan(0);
    for (const roof of gables) {
      if (roof.type !== "roof") continue;
      const enc = roofEnclosure(roof, index)!;
      expect(enc).not.toBeNull();
      const d = scene.byElement.get(roof.id)![0];
      expect(d.materials).toContain(enc.outer);
      expect(d.materials).toContain(ROOF_TRIM);
      // The infill (facade finish) stays below the roof covering, never above the ridge.
      const covering = vertices(d.geometry, d.materials.indexOf(roof.material_id!));
      const infill = vertices(d.geometry, d.materials.indexOf(enc.outer));
      const ridge = Math.max(...covering.map((v) => v.z));
      expect(Math.max(...infill.map((v) => v.z))).toBeLessThan(ridge);
      // Starts at the wall top: the roof underside above the wall's outer face.
      const slope = Math.tan((roof.properties.pitch_deg * Math.PI) / 180);
      const wallTop = roof.dimensions.overhang * slope - roof.dimensions.thickness;
      expect(Math.min(...infill.map((v) => v.z))).toBeCloseTo(wallTop, 5);
      expect(infill.length % 3).toBe(0);
    }
  });

  it("carries the facade up into flat-roof parapets with a trim coping", () => {
    const index = parseBuildingModel(generatedModelJson());
    const scene = buildScene(index);
    const flat = [...index.elementsById.values()].filter(
      (e) =>
        e.type === "roof" && e.properties.roof_type === "flat" && e.properties.parapet_height > 0,
    );
    expect(flat.length).toBeGreaterThan(0);
    for (const roof of flat) {
      if (roof.type !== "roof") continue;
      const enc = roofEnclosure(roof, index)!;
      const d = scene.byElement.get(roof.id)![0];
      expect(d.materials).toEqual(expect.arrayContaining([enc.outer, ROOF_TRIM, roof.material_id]));
      // Coping is the highest part of the roof element.
      const trimTop = Math.max(
        ...vertices(d.geometry, d.materials.indexOf(ROOF_TRIM)).map((v) => v.z),
      );
      expect(trimTop).toBeCloseTo(roof.properties.parapet_height, 6);
    }
  });

  it("is deterministic", () => {
    const a = buildScene(parseBuildingModel(generatedTModelJson()));
    const b = buildScene(parseBuildingModel(generatedTModelJson()));
    for (const [i, d] of a.descriptors.entries()) {
      if (d.key.includes("roof")) continue;
      expect(b.descriptors[i].geometryKey).toBe(d.geometryKey);
    }
    const roofs = (s: typeof a) =>
      s.descriptors
        .filter((d) => s.index.elementsById.get(d.elementId)?.type === "roof")
        .map((d) => Array.from(d.geometry.getAttribute("position").array).join(","));
    expect(roofs(b)).toEqual(roofs(a));
  });
});
