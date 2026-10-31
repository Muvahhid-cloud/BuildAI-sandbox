// Browser TextureSource: loads library textures from MATERIAL_ASSET_BASE (served copies of
// data/materials, see scripts/sync-materials.mjs). Missing files are reported once and leave
// the material on its flat library color.
import { type Texture, TextureLoader } from "three";

import { MATERIAL_ASSET_BASE } from "./library";
import type { TextureSource } from "./material-cache";

export function createBrowserTextureSource(base: string = MATERIAL_ASSET_BASE): TextureSource {
  const loader = new TextureLoader();
  const reported = new Set<string>();
  return {
    load(path: string, onLoad: (texture: Texture) => void): Texture {
      return loader.load(`${base}${path}`, onLoad, undefined, () => {
        if (reported.has(path)) return;
        reported.add(path);
        console.info(`[materials] texture not available, using flat color: ${path}`);
      });
    },
  };
}
