// CC0 glTF models (data/materials/models.json): which model draws which furniture kind, and the
// pure transforms that fit a model to the BuildingModel's dimensions. No I/O here — the viewer
// loads the files; the engine only decides what goes where and how big it is.
import models from "@data/materials/models.json";
import { Matrix4, Vector3 } from "three";
import { z } from "zod";

import type { FurnitureKind } from "@buildai/schema";

const vec3 = z.tuple([z.number(), z.number(), z.number()]);

const modelSchema = z.object({
  id: z.string().regex(/^[a-z0-9_]+$/),
  name: z.string(),
  file: z.string().regex(/^models\/[a-z0-9_]+\.glb$/),
  use: z.enum(["furniture", "tree", "bush"]),
  kinds: z.array(z.string()),
  yaw_deg: z.union([z.literal(0), z.literal(90), z.literal(180), z.literal(270)]),
  bounds: z.object({ min: vec3, max: vec3 }),
});

export type ModelEntry = z.infer<typeof modelSchema>;

const parsed = z.object({ models: z.array(modelSchema) }).parse(models);

export const MODELS: ReadonlyMap<string, ModelEntry> = new Map(parsed.models.map((m) => [m.id, m]));

const BY_KIND = new Map<string, ModelEntry>();
for (const m of parsed.models) for (const k of m.kinds) if (!BY_KIND.has(k)) BY_KIND.set(k, m);

/** Model for a furniture piece: its `asset_id` when that names a model, else its kind's model. */
export function furnitureModel(kind: FurnitureKind, assetId?: string | null): ModelEntry | null {
  const byId = assetId ? MODELS.get(assetId) : undefined;
  if (byId && byId.use === "furniture") return byId;
  return BY_KIND.get(kind) ?? null;
}

export function modelsFor(use: ModelEntry["use"]): ModelEntry[] {
  return parsed.models.filter((m) => m.use === use);
}

/**
 * glTF (Y-up, front +Z after yaw) -> furniture-local frame (Z-up, width x, depth y, front -y,
 * origin = base centre). A rotation, so no mirroring.
 */
function toLocal(yawDeg: number): Matrix4 {
  const yaw = new Matrix4().makeRotationY((yawDeg * Math.PI) / 180);
  // (x, y, z)_gltf -> (x, -z, y)_local
  const axes = new Matrix4().set(1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1);
  return axes.multiply(yaw);
}

function localBounds(m: ModelEntry): { min: Vector3; max: Vector3 } {
  const r = toLocal(m.yaw_deg);
  const min = new Vector3(Infinity, Infinity, Infinity);
  const max = new Vector3(-Infinity, -Infinity, -Infinity);
  const [a, b] = [m.bounds.min, m.bounds.max];
  for (const x of [a[0], b[0]])
    for (const y of [a[1], b[1]])
      for (const zz of [a[2], b[2]]) {
        const p = new Vector3(x, y, zz).applyMatrix4(r);
        min.min(p);
        max.max(p);
      }
  return { min, max };
}

/**
 * Matrix that maps the model (glTF space) onto exactly `width x depth x height` meters in the
 * furniture frame: the BuildingModel's dimensions decide the size, the model only the look.
 */
export function fitToDimensions(
  m: ModelEntry,
  dims: { width: number; depth: number; height: number },
): Matrix4 {
  const { min, max } = localBounds(m);
  const size = new Vector3().subVectors(max, min);
  const center = new Vector3((min.x + max.x) / 2, (min.y + max.y) / 2, min.z);
  return new Matrix4()
    .makeScale(dims.width / size.x, dims.depth / size.y, dims.height / size.z)
    .multiply(new Matrix4().makeTranslation(-center.x, -center.y, -center.z))
    .multiply(toLocal(m.yaw_deg));
}

/** Proportional fit (vegetation): base centre at the origin, scaled to `height` meters, Z-up. */
export function fitToHeight(m: ModelEntry, height: number, rotation = 0): Matrix4 {
  const { min, max } = localBounds(m);
  const s = height / (max.z - min.z);
  return new Matrix4()
    .makeRotationZ(rotation)
    .multiply(new Matrix4().makeScale(s, s, s))
    .multiply(new Matrix4().makeTranslation(-(min.x + max.x) / 2, -(min.y + max.y) / 2, -min.z))
    .multiply(toLocal(m.yaw_deg));
}

/** Every model file the manifest references (relative to data/materials). */
export function modelFiles(): string[] {
  return parsed.models.map((m) => m.file).sort();
}
