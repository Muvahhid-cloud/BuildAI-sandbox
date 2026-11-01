// Site context around the building (not part of the BuildingModel): the ground disc. Pure and
// deterministic. The disc lies in its local XY plane; the viewer lays it flat in world space.
import { type Box3, CircleGeometry, Vector3 } from "three";

/** Ground disc radius for a model's bounds (meters): generous, so the horizon stays distant. */
export function siteRadius(bounds: Box3): number {
  const r = Math.max(bounds.getSize(new Vector3()).length() / 2, 5);
  return Math.max(60, r * 6);
}

/**
 * Disc of `radius` meters whose UVs are the local position in meters (1 UV unit = 1 m), like
 * every building mesh, so the library's `tile_size_m` applies unchanged.
 */
export function groundDiscGeometry(radius: number, segments = 96): CircleGeometry {
  const g = new CircleGeometry(radius, segments);
  const pos = g.getAttribute("position");
  const uv = g.getAttribute("uv");
  for (let i = 0; i < pos.count; i++) uv.setXY(i, pos.getX(i), pos.getY(i));
  uv.needsUpdate = true;
  return g;
}
