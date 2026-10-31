// THE coordinate-conversion boundary (docs/3d-engine.md §3).
//
// BuildingModel: right-handed, Z-up, meters (plan = XY, +X east, +Y north).
// Three.js world: right-handed, Y-up.
//
// All building geometry is emitted in MODEL space and placed under one root group rotated by
// MODEL_ROOT_ROTATION. Anything that lives directly in world space (camera, lights, ground,
// clipping planes) converts through modelToWorld / worldToModel below — nowhere else.
import { Vector3 } from "three";

export interface XYZ {
  x: number;
  y: number;
  z: number;
}

/** Euler XYZ for the model root group: rotating -90° about X maps model +Z onto world +Y. */
export const MODEL_ROOT_ROTATION: [number, number, number] = [-Math.PI / 2, 0, 0];

/** model (x, y, z) -> world (x, z, -y) */
export function modelToWorld(p: XYZ): Vector3 {
  return new Vector3(p.x, p.z, -p.y);
}

/** world (x, y, z) -> model (x, -z, y) */
export function worldToModel(v: XYZ): XYZ {
  return { x: v.x, y: -v.z, z: v.y };
}
