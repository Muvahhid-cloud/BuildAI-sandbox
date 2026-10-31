// Pure helpers for adding a wall on the plan (add_wall, docs/building-model.md §5.5). They only
// describe the gesture — which room the pointer is in, the snapped point, the line the new wall
// would follow across the room (to draw while placing); dividing the room, the new wall and its
// door are made and validated by the server.
import type { P2 } from "../math/polygon";
import type { ModelIndex } from "../model/model-index";
import type { Room, RoomType } from "../model/types";
import { newOpening } from "./opening-edit";
import { insidePolygon } from "./plan-math";
import { roomOutline } from "./symbols";

export type WallDirection = "east_west" | "north_south";

/** Snap of the point a new wall goes through (m). */
export const WALL_PLACE_SNAP_M = 0.05;
/** Wall thickness drawn while placing when the level has no interior wall to take it from. */
const FALLBACK_THICKNESS_M = 0.12;

/** What a new wall will be: the choices of the "+ Wall" controls. */
export interface NewWall {
  direction: WallDirection;
  /** Put an interior door in the middle of the new wall (so the new room can be reached). */
  door: boolean;
  doorWidth: number;
  doorHeight: number;
  /** Type of the smaller part; null keeps the room's type. */
  newRoomType: RoomType | null;
}

/** A new wall's defaults: a door sized like the model's interior doors. */
export function newWall(index: ModelIndex, direction: WallDirection = "north_south"): NewWall {
  const door = newOpening(index, "door", "interior");
  return {
    direction,
    door: true,
    doorWidth: door.width,
    doorHeight: door.height,
    newRoomType: null,
  };
}

export function snapPoint([x, y]: P2, step = WALL_PLACE_SNAP_M): P2 {
  const r = (v: number) => Math.round(Math.round(v / step) * step * 1000) / 1000 || 0;
  return [r(x), r(y)];
}

/** The room of the level that holds the point (the first by id when rooms touch). */
export function roomAt(index: ModelIndex, levelId: string, point: P2): Room | null {
  const rooms = (index.elementsByLevel.get(levelId) ?? [])
    .filter((e): e is Room => e.type === "room")
    .sort((a, b) => a.id.localeCompare(b.id));
  return rooms.find((r) => insidePolygon(point, roomOutline(r))) ?? null;
}

/**
 * The segment a new wall through `point` would follow across the (rectilinear) room: from the
 * boundary on one side to the boundary on the other, in the arm of the room that holds the point.
 */
export function wallAcross(room: Room, [px, py]: P2, direction: WallDirection): [P2, P2] | null {
  const ring = roomOutline(room);
  const ew = direction === "east_west";
  const crossings: number[] = [];
  for (let i = 0; i < ring.length; i++) {
    const [ax, ay] = ring[i];
    const [bx, by] = ring[(i + 1) % ring.length];
    // East-west lines cross the north-south edges, and the other way round.
    const [c0, c1, along] = ew ? [ay, by, ax] : [ax, bx, ay];
    const at = ew ? py : px;
    if (c0 === c1) continue;
    if (Math.min(c0, c1) <= at && at < Math.max(c0, c1)) crossings.push(along);
  }
  crossings.sort((a, b) => a - b);
  const p = ew ? px : py;
  for (let i = 0; i + 1 < crossings.length; i += 2) {
    const [lo, hi] = [crossings[i], crossings[i + 1]];
    if (lo <= p && p <= hi) {
      return ew
        ? [
            [lo, py],
            [hi, py],
          ]
        : [
            [px, lo],
            [px, hi],
          ];
    }
  }
  return null;
}

/** Thickness of the level's interior walls (for drawing the new wall while placing). */
export function interiorThickness(index: ModelIndex, levelId: string): number {
  const wall = (index.elementsByLevel.get(levelId) ?? [])
    .filter((e) => e.type === "wall" && e.properties.wall_kind !== "exterior")
    .sort((a, b) => a.semantic_key.localeCompare(b.semantic_key))[0];
  return wall?.type === "wall" ? wall.dimensions.thickness : FALLBACK_THICKNESS_M;
}

/** Plan outline of a wall body of `thickness` along a → b. */
export function wallBody([a, b]: [P2, P2], thickness: number): P2[] {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const nx = (-dy / len) * (thickness / 2);
  const ny = (dx / len) * (thickness / 2);
  return [
    [a[0] + nx, a[1] + ny],
    [b[0] + nx, b[1] + ny],
    [b[0] - nx, b[1] - ny],
    [a[0] - nx, a[1] - ny],
  ];
}
