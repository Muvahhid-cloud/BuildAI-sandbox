// Browser TextureSource: loads library textures from MATERIAL_ASSET_BASE (served copies of
// data/materials, see scripts/sync-materials.mjs). Only files listed in the served
// manifest.json are requested, so an empty texture slot (ASSETS.md "TODO") costs no request
// and the material simply keeps its flat library color.
import { Texture, TextureLoader } from "three";

import { MATERIAL_ASSET_BASE } from "./library";
import type { TextureSource } from "./material-cache";

export function createBrowserTextureSource(base: string = MATERIAL_ASSET_BASE): TextureSource {
  const loader = new TextureLoader();
  let manifest: Promise<ReadonlySet<string>> | null = null;
  const available = () =>
    (manifest ??= fetch(`${base}manifest.json`)
      .then((r) => (r.ok ? (r.json() as Promise<{ files?: unknown }>) : { files: [] }))
      .then((m) => new Set(Array.isArray(m.files) ? m.files.map(String) : []))
      .catch(() => new Set<string>()));
  return {
    load(path: string, onLoad: (texture: Texture) => void): Texture {
      const texture = new Texture();
      void available().then((files) => {
        if (!files.has(path)) return;
        loader.load(
          `${base}${path}`,
          (loaded) => {
            texture.image = loaded.image;
            texture.needsUpdate = true;
            onLoad(texture);
          },
          undefined,
          () => console.info(`[materials] texture failed to load, using flat color: ${path}`),
        );
      });
      return texture;
    },
  };
}
