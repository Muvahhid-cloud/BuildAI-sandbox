// What the canvas shows while there is no model yet: the bounds the camera frames and the
// plot outline, sized from the floor area once the AI has stated it. Pure. These are interim
// hints for the waiting view only — never geometry of the building.
import { Box3, Vector3 } from "three";

export interface PlotConfig {
  /** Proportion (width : depth) assumed for the footprint. */
  plotAspect: number;
  /** Margin around the assumed footprint (meters). */
  plotMargin: number;
}

export interface Plot {
  /** Half extents of the plot outline (meters). */
  halfWidth: number;
  halfDepth: number;
}

/** The plot outline for a stated floor area over a number of storeys (1 if not yet known). */
export function plotFor(
  floorAreaM2: number | null,
  storeys: number | null,
  cfg: PlotConfig,
): Plot | null {
  if (floorAreaM2 === null || !(floorAreaM2 > 0)) return null;
  const footprint = floorAreaM2 / Math.max(storeys ?? 1, 1);
  const width = Math.sqrt(footprint * cfg.plotAspect);
  const depth = footprint / width;
  return { halfWidth: width / 2 + cfg.plotMargin, halfDepth: depth / 2 + cfg.plotMargin };
}

/** The view of the empty site while waiting: a calm three-quarter view of the sheet. */
export function waitingPose(bounds: Box3): {
  position: { x: number; y: number; z: number };
  target: { x: number; y: number; z: number };
} {
  const { min, max } = bounds;
  const cx = (min.x + max.x) / 2;
  const cy = (min.y + max.y) / 2;
  const size = Math.max(max.x - min.x, max.y - min.y, max.z - min.z, 1);
  return {
    position: { x: cx + 0.85 * size, y: cy - 1.15 * size, z: 0.82 * size },
    target: { x: cx, y: cy, z: 0.4 },
  };
}

/** Model-space bounds framed while waiting (a typical house volume at the origin corner). */
export function waitingBounds(size: { width: number; depth: number; height: number }): Box3 {
  return new Box3(new Vector3(0, 0, 0), new Vector3(size.width, size.depth, size.height));
}
