import { Euler, Matrix4, Quaternion, Vector3 } from "three";

import type { ModelIndex } from "../model/model-index";
import type { BuildingElement, Opening, Wall } from "../model/types";

/** Element-local -> model space: T(position + level elevation) · R(rotation, XYZ). */
export function elementMatrix(el: BuildingElement, index: ModelIndex): Matrix4 {
  const elevation = el.level_id ? (index.levelsById.get(el.level_id)?.elevation ?? 0) : 0;
  const { position: p, rotation: r } = el;
  return new Matrix4().compose(
    new Vector3(p.x, p.y, elevation + p.z),
    new Quaternion().setFromEuler(new Euler(r.x, r.y, r.z, "XYZ")),
    new Vector3(1, 1, 1),
  );
}

/** Across-thickness range [v0, v1] of a wall for its alignment (v = +normal/left side). */
export function wallThicknessRange(wall: Wall): [number, number] {
  const t = wall.dimensions.thickness;
  switch (wall.properties.alignment) {
    case "left":
      return [0, t];
    case "right":
      return [-t, 0];
    default:
      return [-t / 2, t / 2];
  }
}

/**
 * Openings are positioned in host-wall-local coordinates (x = offset along the axis,
 * z = sill). Their frame: wall frame · T(x, center of thickness, z).
 */
export function openingMatrix(opening: Opening, host: Wall, index: ModelIndex): Matrix4 {
  const [v0, v1] = wallThicknessRange(host);
  return elementMatrix(host, index).multiply(
    new Matrix4().makeTranslation(opening.position.x, (v0 + v1) / 2, opening.position.z),
  );
}

export function axisOf(wall: Wall): { start: [number, number]; end: [number, number] } {
  const { x, y } = wall.position;
  const a = wall.rotation.z;
  const L = wall.dimensions.length;
  return { start: [x, y], end: [x + L * Math.cos(a), y + L * Math.sin(a)] };
}
