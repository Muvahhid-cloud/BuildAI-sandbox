import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { MATERIAL_ASSET_BASE } from "@/engine/materials/library";

import { RENDER } from "./render-settings";

// Vitest runs from apps/web.
const MATERIALS_DIR = resolve(process.cwd(), "../../data/materials");

describe("render settings", () => {
  it("lights the scene from a local HDRI that is shipped and recorded in ASSETS.md", () => {
    expect(RENDER.hdriUrl.startsWith(MATERIAL_ASSET_BASE)).toBe(true); // no runtime CDN
    const file = RENDER.hdriUrl.slice(MATERIAL_ASSET_BASE.length);
    expect(file).toMatch(/^hdri\/[a-z0-9_]+\.(hdr|exr)$/);
    expect(existsSync(`${MATERIALS_DIR}/${file}`)).toBe(true);
    expect(readFileSync(`${MATERIALS_DIR}/ASSETS.md`, "utf-8")).toContain(`\`${file}\``);
  });
});
