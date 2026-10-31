// Centralized material presets, loaded from the shared library (data/materials/library.json),
// which the API also uses to validate material ids. Components never define materials.
import library from "@data/materials/library.json";
import { z } from "zod";

const HEX_COLOR = /^#[0-9a-f]{6}$/i;
/** Relative to data/materials (served under MATERIAL_ASSET_BASE); no "..", no absolute paths. */
const ASSET_PATH = /^(textures|hdri)\/[a-z0-9_\-/]+\.(jpg|jpeg|png|webp)$/;

const texturesSchema = z.object({
  albedo: z.string().regex(ASSET_PATH).optional(),
  normal: z.string().regex(ASSET_PATH).optional(),
  roughness: z.string().regex(ASSET_PATH).optional(),
  /** Real-world size of one texture tile in meters [u, v]; UVs are generated in meters. */
  tile_size_m: z.tuple([z.number().positive(), z.number().positive()]),
  /** Color multiplied with the albedo map (the flat `color` is used only without a map). */
  tint: z.string().regex(HEX_COLOR).optional(),
});

const presetSchema = z.object({
  id: z.string(),
  name: z.string(),
  category: z.string(),
  color: z.string().regex(HEX_COLOR),
  roughness: z.number().min(0).max(1),
  metalness: z.number().min(0).max(1),
  opacity: z.number().gt(0).max(1).optional(),
  /** "glass": reflective, slightly tinted glazing (physical material, no transmission pass). */
  shading: z.enum(["standard", "glass"]).optional(),
  /** Multiplier of the environment (HDRI) reflections. */
  env_intensity: z.number().min(0).max(4).optional(),
  textures: texturesSchema.optional(),
});

export type MaterialPreset = z.infer<typeof presetSchema>;
export type MaterialTextures = z.infer<typeof texturesSchema>;

const parsed = z.object({ materials: z.array(presetSchema) }).parse(library);

export const MATERIAL_PRESETS: ReadonlyMap<string, MaterialPreset> = new Map(
  parsed.materials.map((m) => [m.id, m]),
);

/** URL prefix under which data/materials/{textures,hdri} are served (scripts/sync-materials.mjs). */
export const MATERIAL_ASSET_BASE = "/materials/";

/** Rendered for unknown material ids — deliberately loud (magenta) and reported in the UI. */
export const MISSING_MATERIAL: MaterialPreset = {
  id: "__missing__",
  name: "Missing material",
  category: "error",
  color: "#ff00ff",
  roughness: 0.5,
  metalness: 0,
};

/** Library material of the site ground (not a BuildingModel element). */
export const SITE_GROUND_MATERIAL = "site_grass";

export function materialPreset(id: string): MaterialPreset {
  return MATERIAL_PRESETS.get(id) ?? MISSING_MATERIAL;
}

export function materialName(id: string | null | undefined): string {
  if (!id) return "—";
  return MATERIAL_PRESETS.get(id)?.name ?? `Unknown (${id})`;
}

/** Every texture file the library references (sorted, unique), relative to data/materials. */
export function libraryTextureFiles(): string[] {
  const files = new Set<string>();
  for (const m of MATERIAL_PRESETS.values()) {
    const t = m.textures;
    if (!t) continue;
    for (const f of [t.albedo, t.normal, t.roughness]) if (f) files.add(f);
  }
  return [...files].sort();
}
