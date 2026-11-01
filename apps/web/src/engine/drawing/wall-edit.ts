// Pure helpers for moving a wall on the plan (docs/3d-engine.md §20). They only describe the
// gesture (direction, snapping, the outline shown while dragging); the move itself is a typed
// operation applied and validated by the server.
import type { P2 } from "../math/polygon";
import { wallThicknessRange } from "../math/transform";
import type { ModelIndex } from "../model/model-index";
import type { BuildingElement, Wall } from "../model/types";
import { mapPts, rect } from "./plan-math";

/** Drag snap and keyboard nudge step (m). */
export const WALL_SNAP_M = 0.05;

export type Compass = "north" | "east" | "south" | "west";

/**
 * Walls that can be dragged on the plan: interior walls, and (D2.5) exterior walls, which move
 * their whole facade with the slabs and roof. The server refuses what cannot follow.
 */
export function isMovableWall(el: BuildingElement | undefined): el is Wall {
  return el?.type === "wall" && el.properties.wall_kind !== "partition";
}

/** Whether moving this wall moves a facade (every storey, slabs and roof follow). */
export function isFacade(wall: Wall): boolean {
  return wall.properties.wall_kind === "exterior";
}

/**
 * Eaves outlines of every roof in plan (model meters), for the dashed overlay while a facade is
 * edited: the roof outline is roof-local, placed by the roof's position and rotation.
 */
export function roofOutlines(index: ModelIndex): P2[][] {
  const out: P2[][] = [];
  for (const el of index.model.elements) {
    if (el.type !== "roof") continue;
    const c = Math.cos(el.rotation.z);
    const s = Math.sin(el.rotation.z);
    out.push(
      el.properties.outline.map(
        (p) => [el.position.x + c * p.x - s * p.y, el.position.y + s * p.x + c * p.y] as P2,
      ),
    );
  }
  return out;
}

/** Unit normal of the wall's left face: the direction of a positive `offset_m`. */
export function wallNormal(wall: Wall): P2 {
  return [-Math.sin(wall.rotation.z), Math.cos(wall.rotation.z)];
}

/** Snap to the drag step and to whole millimeters. */
export function snapOffset(offset: number, step = WALL_SNAP_M): number {
  const snapped = Math.round(offset / step) * step;
  return Math.round(snapped * 1000) / 1000 || 0;
}

/** Signed offset for a pointer movement given in model meters (dx east, dy north). */
export function offsetFromDrag(wall: Wall, [dx, dy]: P2): number {
  const [nx, ny] = wallNormal(wall);
  return dx * nx + dy * ny;
}

/** The compass direction a positive offset moves the wall (walls are axis-aligned in v1). */
export function positiveDirection(wall: Wall): Compass {
  const [nx, ny] = wallNormal(wall);
  if (Math.abs(nx) > Math.abs(ny)) return nx > 0 ? "east" : "west";
  return ny > 0 ? "north" : "south";
}

/** The offset that moves the wall `distance` meters towards `direction` (0 if across it). */
export function offsetTowards(wall: Wall, direction: Compass, distance: number): number {
  const positive = positiveDirection(wall);
  if (positive === direction) return distance;
  const opposite: Record<Compass, Compass> = {
    north: "south",
    south: "north",
    east: "west",
    west: "east",
  };
  return opposite[positive] === direction ? -distance : 0;
}

/** The two directions a wall can move in, negative side first. */
export function moveDirections(wall: Wall): [Compass, Compass] {
  const p = positiveDirection(wall);
  return p === "north" || p === "south" ? ["south", "north"] : ["west", "east"];
}

/** Outline of the wall body shifted by `offset` (model plan coordinates). */
export function movedWallOutline(wall: Wall, offset: number): P2[] {
  const [v0, v1] = wallThicknessRange(wall);
  const [nx, ny] = wallNormal(wall);
  const frame = {
    x: wall.position.x + offset * nx,
    y: wall.position.y + offset * ny,
    angle: wall.rotation.z,
  };
  return mapPts(frame, rect(0, v0, wall.dimensions.length, v1));
}
