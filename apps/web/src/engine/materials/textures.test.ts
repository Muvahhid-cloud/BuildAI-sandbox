import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { MeshPhysicalMaterial, NoColorSpace, SRGBColorSpace, Texture } from "three";
import { describe, expect, it } from "vitest";

import { buildScene } from "../scene/build-scene";
import { demoIndex, generatedModelJson } from "../test-fixtures";
import { parseBuildingModel } from "../model/parse";
import {
  libraryTextureFiles,
  MATERIAL_PRESETS,
  materialPreset,
  SITE_GROUND_MATERIAL,
} from "./library";
import { MaterialCache, type TextureSource, textureRepeat } from "./material-cache";

// Vitest runs from apps/web.
const MATERIALS_DIR = `${resolve(process.cwd(), "../../data/materials")}/`;

/** Records requests; `resolve` delivers images like a browser loader would (asynchronously). */
function fakeSource(available: (path: string) => boolean = () => true) {
  const requests: string[] = [];
  const pending: (() => void)[] = [];
  const source: TextureSource = {
    load(path, onLoad) {
      requests.push(path);
      const texture = new Texture();
      if (available(path)) {
        pending.push(() => {
          texture.image = { width: 4, height: 4 };
          onLoad(texture);
        });
      }
      return texture;
    },
  };
  return {
    source,
    requests,
    resolve: () => {
      for (const fn of pending.splice(0)) fn();
    },
  };
}

describe("material library textures", () => {
  it("gives every requested surface family PBR maps and a real-world tile size", () => {
    for (const id of [
      "brick",
      "exterior_wall",
      "interior_wall",
      "parquet",
      "floor",
      "tile",
      "roof",
      "concrete",
      SITE_GROUND_MATERIAL,
    ]) {
      const t = materialPreset(id).textures;
      expect(t, id).toBeDefined();
      expect(t!.normal && t!.roughness, id).toBeTruthy();
      // Painted interior plaster keeps its flat (paint) colour: relief maps only.
      if (id !== "interior_wall") expect(t!.albedo, id).toBeTruthy();
      expect(t!.tile_size_m[0]).toBeGreaterThan(0.1);
      expect(t!.tile_size_m[1]).toBeLessThan(10);
    }
  });

  it("keeps a flat fallback color for every preset", () => {
    for (const m of MATERIAL_PRESETS.values()) expect(m.color).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it("references only files under data/materials/textures that ASSETS.md accounts for", () => {
    const assets = readFileSync(`${MATERIALS_DIR}ASSETS.md`, "utf-8");
    for (const file of libraryTextureFiles()) {
      expect(file).toMatch(/^textures\/[a-z_]+\/(albedo|normal|roughness)\.jpg$/);
      const folder = file.split("/").slice(0, 2).join("/");
      expect(assets, folder).toContain(`${folder}/`);
    }
  });

  it("ships every referenced texture file and HDRI (no slot is TODO any more)", () => {
    for (const file of libraryTextureFiles()) {
      expect(existsSync(`${MATERIALS_DIR}${file}`), file).toBe(true);
    }
    expect(readFileSync(`${MATERIALS_DIR}ASSETS.md`, "utf-8")).not.toMatch(/\|\s*TODO\s*\|/);
  });

  it("ships every texture file that ASSETS.md lists as present", () => {
    const assets = readFileSync(`${MATERIALS_DIR}ASSETS.md`, "utf-8");
    for (const file of libraryTextureFiles()) {
      const folder = file.split("/").slice(0, 2).join("/");
      const row = assets.split("\n").find((l) => l.includes(`\`${folder}/\``));
      if (row && !row.includes("TODO"))
        expect(existsSync(`${MATERIALS_DIR}${file}`), file).toBe(true);
    }
  });

  it("covers every material of the demo and the generated house", () => {
    const scenes = [buildScene(demoIndex()), buildScene(parseBuildingModel(generatedModelJson()))];
    const ids = new Set(
      scenes.flatMap((s) => s.descriptors.flatMap((d) => d.materials.map((k) => k.split("@")[0]))),
    );
    for (const id of ids) expect(MATERIAL_PRESETS.has(id), id).toBe(true);
  });
});

describe("MaterialCache textures", () => {
  it("uses flat library colors when no texture source is set", () => {
    const cache = new MaterialCache();
    const brick = cache.get("brick");
    expect(brick.map).toBeNull();
    expect(`#${brick.color.getHexString()}`).toBe(materialPreset("brick").color);
  });

  it("applies albedo/normal/roughness with repeat = 1 / tile size once loaded", () => {
    const fake = fakeSource();
    const cache = new MaterialCache(fake.source);
    let changes = 0;
    cache.onChange(() => changes++);
    const brick = cache.get("brick");
    // Until the images arrive the flat color stays.
    expect(brick.map).toBeNull();
    expect(`#${brick.color.getHexString()}`).toBe(materialPreset("brick").color);
    fake.resolve();
    const t = materialPreset("brick").textures!;
    const [ru, rv] = textureRepeat(t.tile_size_m);
    expect(brick.map).not.toBeNull();
    expect(brick.normalMap).not.toBeNull();
    expect(brick.roughnessMap).not.toBeNull();
    expect(brick.map!.repeat.x).toBeCloseTo(ru);
    expect(brick.map!.repeat.y).toBeCloseTo(rv);
    expect(brick.map!.colorSpace).toBe(SRGBColorSpace);
    expect(brick.normalMap!.colorSpace).toBe(NoColorSpace);
    expect(`#${brick.color.getHexString()}`).toBe("#ffffff"); // map carries the color
    expect(changes).toBe(3);
  });

  it("shares one texture per file and tile size across materials and variants", () => {
    const fake = fakeSource();
    const cache = new MaterialCache(fake.source);
    cache.get("parquet");
    cache.get("parquet", "selected");
    cache.get("decking"); // same files, same tile size
    expect(fake.requests).toHaveLength(3);
    fake.resolve();
    expect(cache.get("parquet").map).toBe(cache.get("decking").map);
    expect(cache.get("parquet", "selected").map).toBe(cache.get("parquet").map);
    expect(`#${cache.get("decking").color.getHexString()}`).toBe(
      materialPreset("decking").textures!.tint,
    );
  });

  it("keeps the flat color when a texture file is missing", () => {
    const fake = fakeSource((p) => !p.includes("albedo"));
    const cache = new MaterialCache(fake.source);
    const roof = cache.get("roof");
    fake.resolve();
    expect(roof.map).toBeNull();
    expect(roof.normalMap).not.toBeNull();
    expect(`#${roof.color.getHexString()}`).toBe(materialPreset("roof").color);
  });

  it("multiplies a K3 display color with the albedo map", () => {
    const fake = fakeSource();
    const cache = new MaterialCache(fake.source);
    const yellow = cache.get("exterior_wall@#e8c547");
    fake.resolve();
    expect(yellow.map).not.toBeNull();
    expect(`#${yellow.color.getHexString()}`).toBe("#e8c547");
  });

  it("does not texture ghosted materials", () => {
    const fake = fakeSource();
    const cache = new MaterialCache(fake.source);
    cache.get("brick", "ghost");
    expect(fake.requests).toHaveLength(0);
  });

  it("renders glass as reflective, tinted, transparent physical glazing", () => {
    const glass = new MaterialCache().get("glass");
    expect(glass).toBeInstanceOf(MeshPhysicalMaterial);
    expect(glass.transparent).toBe(true);
    expect(glass.opacity).toBeLessThan(0.5);
    expect(glass.roughness).toBeLessThan(0.1);
    expect(glass.envMapIntensity).toBeGreaterThan(1);
    expect(`#${glass.color.getHexString()}`).not.toBe("#ffffff");
  });

  it("drops textures and materials on dispose", () => {
    const fake = fakeSource();
    const cache = new MaterialCache(fake.source);
    cache.get("brick");
    expect(cache.textureCount).toBe(3);
    cache.dispose();
    expect(cache.textureCount).toBe(0);
    expect(cache.size).toBe(0);
  });
});
