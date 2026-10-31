import { describe, expect, it } from "vitest";

import { fnv1a } from "../builders/common";
import { parseBuildingModel } from "../model/parse";
import { demoIndex, demoModelJson, typedDemoModelJson } from "../test-fixtures";
import { buildScene, disposeScene, type SceneGraph } from "./build-scene";

/** Hash of everything that ends up on the GPU: keys, materials, matrices, buffers. */
function sceneHash(scene: SceneGraph): string {
  const parts: string[] = [];
  for (const d of scene.descriptors) {
    parts.push(d.key, d.materials.join(","), d.matrix.elements.map((v) => v.toFixed(6)).join(","));
    for (const name of ["position", "normal", "uv"]) {
      const attr = d.geometry.getAttribute(name);
      parts.push(Array.from(attr.array as Float32Array, (v) => v.toFixed(5)).join(","));
    }
  }
  return fnv1a(parts.join("|"));
}

describe("buildScene", () => {
  const index = demoIndex();
  const scene = buildScene(index);

  it("is deterministic: same model => identical geometry", () => {
    expect(sceneHash(buildScene(demoIndex()))).toBe(sceneHash(scene));
  });

  it("type metadata never changes geometry (builders are unchanged by K2)", () => {
    expect(sceneHash(buildScene(parseBuildingModel(typedDemoModelJson())))).toBe(sceneHash(scene));
  });

  it("does not depend on the order of elements in the document", () => {
    const shuffled = demoModelJson();
    shuffled.elements.reverse();
    expect(sceneHash(buildScene(parseBuildingModel(shuffled)))).toBe(sceneHash(scene));
  });

  it("maps every element to >= 1 render descriptor and back", () => {
    for (const el of index.model.elements) {
      const parts = scene.byElement.get(el.id) ?? [];
      expect(parts.length, `${el.type} ${el.name}`).toBeGreaterThan(0);
      for (const d of parts) {
        expect(d.elementId).toBe(el.id);
        expect(d.layer).toBe(el.layer);
        expect(d.levelId).toBe(el.level_id);
      }
    }
    const keys = scene.descriptors.map((d) => d.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const d of scene.descriptors) expect(index.elementsById.has(d.elementId)).toBe(true);
  });

  it("shares geometry between identical furniture", () => {
    const chairs = scene.descriptors.filter(
      (d) => index.elementsById.get(d.elementId)?.name.startsWith("Chair ") && d.part === "body",
    );
    expect(chairs.length).toBe(6);
    expect(new Set(chairs.map((d) => d.geometry)).size).toBe(1);
    expect(scene.stats.geometries).toBeLessThan(scene.stats.meshes);
  });

  it("computes model-space bounds of the whole house", () => {
    expect(scene.bounds.min.x).toBeCloseTo(-0.65, 2);
    expect(scene.bounds.max.y).toBeCloseTo(11.6, 1); // balcony
    expect(scene.bounds.max.z).toBeGreaterThan(6.5); // roof ridge
  });

  it("reuses unchanged geometry on rebuild and only rebuilds what changed", () => {
    const edited = demoModelJson();
    const sofa = edited.elements.find((e) => e.semantic_key === "furniture:sofa")!;
    sofa.material_id = "fabric_light";
    const next = buildScene(parseBuildingModel(edited), undefined, scene);
    const changed = next.descriptors.filter((d) => {
      const before = scene.descriptors.find((p) => p.key === d.key);
      return before?.geometry !== d.geometry;
    });
    expect(changed.map((d) => d.elementId)).toEqual([sofa.id]);
    disposeScene(scene, next); // must not dispose geometry still used by `next`
    expect(next.descriptors.every((d) => d.geometry.getAttribute("position").count > 0)).toBe(true);
  });
});
