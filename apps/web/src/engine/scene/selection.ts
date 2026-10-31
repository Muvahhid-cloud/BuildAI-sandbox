// Mesh <-> BuildingModel mapping for picking. Meshes carry only ids in userData.
import type { Object3D } from "three";

export interface ElementUserData {
  elementId: string;
  part: string;
}

export function elementUserData(elementId: string, part: string): ElementUserData {
  return { elementId, part };
}

/** Walk up from a hit object to the first ancestor tagged with an element id. */
export function resolveElementId(object: Object3D | null): string | null {
  for (let o: Object3D | null = object; o; o = o.parent) {
    const id = (o.userData as Partial<ElementUserData>).elementId;
    if (typeof id === "string") return id;
  }
  return null;
}
