import { describe, expect, it } from "vitest";

import { buildScene } from "../scene/build-scene";
import { demoIndex } from "../test-fixtures";
import { MATERIAL_PRESETS } from "./library";
import { coloredMaterialKey, MaterialCache, parseMaterialKey } from "./material-cache";
import { furnitureSource, registerFurnitureAsset } from "../builders/furniture/assets";

describe("material library", () => {
  it("contains the required presets", () => {
    for (const id of [
      "concrete",
      "brick",
      "glass",
      "wood",
      "roof",
      "floor",
      "interior_wall",
      "exterior_wall",
    ]) {
      expect(MATERIAL_PRESETS.has(id), id).toBe(true);
    }
  });

  it("covers every material used by the demo geometry", () => {
    const used = new Set(buildScene(demoIndex()).descriptors.flatMap((d) => d.materials));
    for (const id of used) expect(MATERIAL_PRESETS.has(id), id).toBe(true);
  });
});

describe("MaterialCache", () => {
  it("reuses one material instance per (id, variant)", () => {
    const cache = new MaterialCache();
    expect(cache.get("brick")).toBe(cache.get("brick"));
    expect(cache.get("brick", "selected")).not.toBe(cache.get("brick"));
    expect(cache.size).toBe(2);
    cache.dispose();
    expect(cache.size).toBe(0);
  });

  it("makes glass transparent and ghosts non-writing to depth", () => {
    const cache = new MaterialCache();
    expect(cache.get("glass").transparent).toBe(true);
    const ghost = cache.get("brick", "ghost");
    expect(ghost.transparent).toBe(true);
    expect(ghost.depthWrite).toBe(false);
  });

  it("reports unknown material ids instead of hiding them", () => {
    const cache = new MaterialCache();
    cache.get("unobtainium");
    expect(cache.missingIds).toEqual(["unobtainium"]);
  });

  it("draws a display color over a library preset without changing the material (K3)", () => {
    const cache = new MaterialCache();
    const key = coloredMaterialKey("exterior_wall", "#e8c547");
    expect(key).toBe("exterior_wall@#e8c547");
    expect(parseMaterialKey(key)).toEqual({ id: "exterior_wall", color: "#e8c547" });
    const yellow = cache.get(key);
    const plain = cache.get("exterior_wall");
    expect(`#${yellow.color.getHexString()}`).toBe("#e8c547");
    expect(yellow.roughness).toBe(plain.roughness);
    expect(yellow.metalness).toBe(plain.metalness);
    expect(yellow).not.toBe(plain);
    expect(cache.missingIds).toEqual([]); // the id is still the library id
    expect(coloredMaterialKey("exterior_wall", null)).toBe("exterior_wall");
    expect(coloredMaterialKey("exterior_wall", "yellow")).toBe("exterior_wall"); // hex only
  });
});

describe("furniture assets", () => {
  it("uses procedural placeholders unless a GLB asset is registered", () => {
    const sofa = demoIndex().model.elements.find((e) => e.type === "furniture")!;
    if (sofa.type !== "furniture") throw new Error("fixture");
    expect(furnitureSource(sofa)).toEqual({ type: "procedural" });
    registerFurnitureAsset("sofa-v1", { url: "/assets/sofa.glb", scale: 1, offset: [0, 0, 0] });
    const withAsset = { ...sofa, properties: { ...sofa.properties, asset_id: "sofa-v1" } };
    expect(furnitureSource(withAsset).type).toBe("gltf");
  });
});
