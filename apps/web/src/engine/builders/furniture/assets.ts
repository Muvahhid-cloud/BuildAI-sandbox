// Furniture asset resolution. Phase 1 renders every piece with procedural placeholder
// geometry. To use real models later, register GLB/glTF assets here by the element's
// `properties.asset_id`; the viewer then loads the asset (e.g. drei useGLTF) instead of the
// placeholder, keeping the same element id, transform and selection behaviour.
import type { Furniture } from "../../model/types";

export interface GltfAsset {
  url: string;
  /** Uniform scale to meters and offset so the asset's base center sits at the origin. */
  scale: number;
  offset: [number, number, number];
}

export type FurnitureSource = { type: "procedural" } | { type: "gltf"; asset: GltfAsset };

const ASSETS = new Map<string, GltfAsset>();

export function registerFurnitureAsset(assetId: string, asset: GltfAsset): void {
  ASSETS.set(assetId, asset);
}

export function furnitureSource(el: Furniture): FurnitureSource {
  const id = el.properties.asset_id;
  const asset = id ? ASSETS.get(id) : undefined;
  return asset ? { type: "gltf", asset } : { type: "procedural" };
}
