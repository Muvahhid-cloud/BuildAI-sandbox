// Centralized material presets, loaded from the shared library (data/materials/library.json),
// which the API also uses to validate material ids. Components never define materials.
import library from "@data/materials/library.json";
import { z } from "zod";

const presetSchema = z.object({
  id: z.string(),
  name: z.string(),
  category: z.string(),
  color: z.string().regex(/^#[0-9a-f]{6}$/i),
  roughness: z.number().min(0).max(1),
  metalness: z.number().min(0).max(1),
  opacity: z.number().gt(0).max(1).optional(),
});

export type MaterialPreset = z.infer<typeof presetSchema>;

const parsed = z.object({ materials: z.array(presetSchema) }).parse(library);

export const MATERIAL_PRESETS: ReadonlyMap<string, MaterialPreset> = new Map(
  parsed.materials.map((m) => [m.id, m]),
);

/** Rendered for unknown material ids — deliberately loud (magenta) and reported in the UI. */
export const MISSING_MATERIAL: MaterialPreset = {
  id: "__missing__",
  name: "Missing material",
  category: "error",
  color: "#ff00ff",
  roughness: 0.5,
  metalness: 0,
};

export function materialPreset(id: string): MaterialPreset {
  return MATERIAL_PRESETS.get(id) ?? MISSING_MATERIAL;
}

export function materialName(id: string | null | undefined): string {
  if (!id) return "—";
  return MATERIAL_PRESETS.get(id)?.name ?? `Unknown (${id})`;
}
