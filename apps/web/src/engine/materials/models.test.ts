import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

import { Box3, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { FURNITURE_PLACEHOLDERS } from "../builders/furniture/placeholders";
import { fitToDimensions, fitToHeight, furnitureModel, MODELS, modelFiles } from "./models";

// Vitest runs from apps/web.
const MATERIALS_DIR = resolve(process.cwd(), "../../data/materials");

/** Corners of a model's glTF bounds mapped through `m`. */
function mappedBox(id: string, m: import("three").Matrix4): Box3 {
  const b = MODELS.get(id)!.bounds;
  const box = new Box3();
  for (const x of [b.min[0], b.max[0]])
    for (const y of [b.min[1], b.max[1]])
      for (const z of [b.min[2], b.max[2]]) box.expandByPoint(new Vector3(x, y, z).applyMatrix4(m));
  return box;
}

describe("model manifest (data/materials/models.json)", () => {
  it("ships every model as a self-contained, meshopt-compressed GLB recorded in ASSETS.md", () => {
    const assets = readFileSync(`${MATERIALS_DIR}/ASSETS.md`, "utf-8");
    let total = 0;
    for (const file of modelFiles()) {
      const path = `${MATERIALS_DIR}/${file}`;
      expect(existsSync(path), file).toBe(true);
      const bytes = readFileSync(path);
      expect(bytes.toString("ascii", 0, 4), file).toBe("glTF");
      expect(bytes.readUInt32LE(4), file).toBe(2);
      const jsonLength = bytes.readUInt32LE(12);
      const json = JSON.parse(bytes.toString("utf-8", 20, 20 + jsonLength)) as {
        extensionsUsed?: string[];
        buffers?: { uri?: string }[];
        images?: { uri?: string }[];
      };
      expect(json.extensionsUsed, file).toContain("EXT_meshopt_compression");
      // Self-contained: no external buffers or images (no runtime downloads).
      expect(
        (json.buffers ?? []).every((b) => !b.uri),
        file,
      ).toBe(true);
      expect(
        (json.images ?? []).every((i) => !i.uri),
        file,
      ).toBe(true);
      expect(assets, file).toContain(`\`${file}\``);
      total += statSync(path).size;
    }
    expect(total).toBeLessThan(40 * 1024 * 1024);
  });

  it("maps furniture kinds to models and keeps the placeholder where there is none", () => {
    expect(furnitureModel("sofa")?.id).toBe("sofa_02");
    expect(furnitureModel("chair")?.id).toBe("dining_chair_02");
    expect(furnitureModel("desk")?.id).toBe("wooden_table_02");
    for (const kind of [
      "toilet",
      "basin",
      "bathtub",
      "shower",
      "kitchen_counter",
      "fridge",
    ] as const)
      expect(furnitureModel(kind), kind).toBeNull();
    // asset_id naming a furniture model wins over the kind; vegetation ids never apply.
    expect(furnitureModel("desk", "side_table_01")?.id).toBe("side_table_01");
    expect(furnitureModel("desk", "tree_small_02")?.id).toBe("wooden_table_02");
    // Every mapped kind is a real furniture kind of the schema.
    for (const m of MODELS.values())
      for (const k of m.kinds) expect(Object.keys(FURNITURE_PLACEHOLDERS), k).toContain(k);
  });
});

describe("model fitting", () => {
  it("fits every furniture model exactly to the element's width x depth x height", () => {
    for (const m of MODELS.values()) {
      if (m.use !== "furniture") continue;
      for (const dims of [
        { width: 2.4, depth: 0.95, height: 0.8 },
        { width: 0.45, depth: 0.5, height: 0.9 },
      ]) {
        const box = mappedBox(m.id, fitToDimensions(m, dims));
        expect(box.min.x, m.id).toBeCloseTo(-dims.width / 2, 6);
        expect(box.max.x, m.id).toBeCloseTo(dims.width / 2, 6);
        expect(box.min.y, m.id).toBeCloseTo(-dims.depth / 2, 6);
        expect(box.max.y, m.id).toBeCloseTo(dims.depth / 2, 6);
        expect(box.min.z, m.id).toBeCloseTo(0, 6);
        expect(box.max.z, m.id).toBeCloseTo(dims.height, 6);
      }
    }
  });

  it("turns glTF Y-up into model Z-up with the front (+Z after yaw) facing -y", () => {
    const sofa = MODELS.get("sofa_02")!;
    const m = fitToDimensions(sofa, { width: 2, depth: 1, height: 1 });
    const up = new Vector3(0, 1, 0).transformDirection(m);
    const front = new Vector3(0, 0, 1).transformDirection(m);
    expect(up.z).toBeCloseTo(1, 6);
    expect(front.y).toBeCloseTo(-1, 6);
    // A determinant > 0: the fit never mirrors a model.
    expect(m.determinant()).toBeGreaterThan(0);
  });

  it("scales vegetation proportionally to the requested height", () => {
    const tree = MODELS.get("tree_small_02")!;
    const box = mappedBox(tree.id, fitToHeight(tree, 5));
    expect(box.min.z).toBeCloseTo(0, 6);
    expect(box.max.z).toBeCloseTo(5, 6);
    const b = tree.bounds;
    const s = 5 / (b.max[1] - b.min[1]);
    expect(box.max.x - box.min.x).toBeCloseTo((b.max[0] - b.min[0]) * s, 5);
  });
});
