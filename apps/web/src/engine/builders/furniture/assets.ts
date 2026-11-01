// Furniture asset resolution. Geometry builders always emit the procedural placeholder (it is
// the pick proxy, the bounds and the fallback). The viewer draws a CC0 glTF model instead when
// one is available (V2): an explicitly registered asset (by `asset_id`), else the model of the
// manifest (data/materials/models.json) for that `asset_id` or furniture kind — fitted to the
// element's width x depth x height, so the BuildingModel stays the source of truth.
import { furnitureModel, type ModelEntry } from "../../materials/models";
import type { Furniture } from "../../model/types";

export interface GltfAsset {
  url: string;
  /** Uniform scale to meters and offset so the asset's base center sits at the origin. */
  scale: number;
  offset: [number, number, number];
}

export type FurnitureSource =
  | { type: "procedural" }
  | { type: "gltf"; asset: GltfAsset }
  | { type: "model"; model: ModelEntry };

const ASSETS = new Map<string, GltfAsset>();

export function registerFurnitureAsset(assetId: string, asset: GltfAsset): void {
  ASSETS.set(assetId, asset);
}

export function furnitureSource(el: Furniture): FurnitureSource {
  const id = el.properties.asset_id;
  const asset = id ? ASSETS.get(id) : undefined;
  if (asset) return { type: "gltf", asset };
  const model = furnitureModel(el.properties.furniture_kind, id);
  return model ? { type: "model", model } : { type: "procedural" };
}
