// Pure helpers for resizing a room on the plan (docs/3d-engine.md §20.2). They describe the
// room's sides for the gesture (direction, which walls a side runs along, whether it can move);
// the resize itself is the typed `resize_room` operation, applied and validated by the server,
// which repeats these checks (apps/api/app/modules/building/operations/rooms.py).
import { type P2, segmentOverlap, signedArea } from "../math/polygon";
import { axisOf } from "../math/transform";
import type { ModelIndex } from "../model/model-index";
import { EPS, type Room, type Wall } from "../model/types";
import type { Compass } from "./wall-edit";
import { roomOutline } from "./symbols";

/** movable: interior walls over the whole side; the others are refused by the server. */
export type SideKind = "movable" | "exterior" | "open" | "partly";

export interface RoomSide {
  index: number;
  start: P2;
  end: P2;
  /** Unit normal pointing out of the room: the direction of a positive `delta_m`. */
  outward: P2;
  walls: Wall[];
  kind: SideKind;
  compass: Compass;
  length: number;
}

const COMPASS: [P2, Compass][] = [
  [[0, 1], "north"],
  [[1, 0], "east"],
  [[0, -1], "south"],
  [[-1, 0], "west"],
];

export function compassOf([x, y]: P2): Compass {
  let best: Compass = "north";
  let bestDot = -Infinity;
  for (const [[cx, cy], name] of COMPASS) {
    const d = cx * x + cy * y;
    if (d > bestDot) {
      bestDot = d;
      best = name;
    }
  }
  return best;
}

export function roomSides(index: ModelIndex, room: Room): RoomSide[] {
  const ring = roomOutline(room);
  const ccw = signedArea(ring) > 0;
  const walls = (index.elementsByLevel.get(room.level_id ?? "") ?? [])
    .filter((e): e is Wall => e.type === "wall")
    .sort((a, b) => a.id.localeCompare(b.id));
  return ring.map((start, i) => {
    const end = ring[(i + 1) % ring.length];
    const length = Math.hypot(end[0] - start[0], end[1] - start[1]);
    const ux = length > EPS ? (end[0] - start[0]) / length : 0;
    const uy = length > EPS ? (end[1] - start[1]) / length : 0;
    // Outward is to the right of the direction of travel on a counter-clockwise ring.
    const outward: P2 = ccw ? [uy, -ux] : [-uy, ux];
    let covered = 0;
    const along: Wall[] = [];
    for (const w of walls) {
      const { start: a, end: b } = axisOf(w);
      const overlap = segmentOverlap([a, b], [start, end]);
      if (overlap > EPS) {
        along.push(w);
        covered += overlap;
      }
    }
    const kind: SideKind =
      along.length === 0
        ? "open"
        : covered < length - EPS
          ? "partly"
          : along.some((w) => w.properties.wall_kind === "exterior")
            ? "exterior"
            : "movable";
    return {
      index: i,
      start,
      end,
      outward,
      walls: along,
      kind,
      compass: compassOf(outward),
      length,
    };
  });
}

/** Why a side cannot be resized (the server gives the same reasons), or null. */
export function sideRefusal(room: Room, side: RoomSide): string | null {
  const where = `The ${side.compass} side of ${room.name}`;
  switch (side.kind) {
    case "movable":
      return null;
    case "exterior":
      return `${where} is an exterior wall; rooms can be resized at interior walls for now.`;
    case "open":
      return `${where} is an open boundary without a wall; resizing it is not supported yet.`;
    case "partly":
      return `${where} is only partly a wall; resizing it is not supported yet.`;
  }
}

/** Signed delta for a pointer movement in model meters: + moves the side outwards. */
export function deltaFromDrag(side: RoomSide, [dx, dy]: P2): number {
  return dx * side.outward[0] + dy * side.outward[1];
}

/** The room outline with one side moved by `delta` (gesture outline only, model coordinates). */
export function movedSideOutline(room: Room, side: RoomSide, delta: number): P2[] {
  const ring = roomOutline(room);
  const n = ring.length;
  const [ox, oy] = side.outward;
  return ring.map((p, i) =>
    i === side.index || i === (side.index + 1) % n ? [p[0] + delta * ox, p[1] + delta * oy] : p,
  );
}

/** Overall width (x) and depth (y) of a room outline, for the live readout. */
export function roomExtent(room: Room): { width: number; depth: number } {
  const ring = roomOutline(room);
  const xs = ring.map((p) => p[0]);
  const ys = ring.map((p) => p[1]);
  return {
    width: Math.max(...xs) - Math.min(...xs),
    depth: Math.max(...ys) - Math.min(...ys),
  };
}

/**
 * The side of `room` (in a model after an edit) that `moved` became, found by geometry: the
 * side facing the same way whose segment holds the moved midpoint. Null if it is gone.
 */
export function relocateSide(
  index: ModelIndex,
  roomId: string,
  moved: RoomSide,
  delta: number,
): number | null {
  const room = index.elementsById.get(roomId);
  if (room?.type !== "room") return null;
  const mid: P2 = [
    (moved.start[0] + moved.end[0]) / 2 + delta * moved.outward[0],
    (moved.start[1] + moved.end[1]) / 2 + delta * moved.outward[1],
  ];
  for (const side of roomSides(index, room)) {
    const same = side.outward[0] * moved.outward[0] + side.outward[1] * moved.outward[1] > 0.99;
    if (!same) continue;
    const [ax, ay] = side.start;
    const [bx, by] = side.end;
    const cross = (bx - ax) * (mid[1] - ay) - (by - ay) * (mid[0] - ax);
    const t = ((mid[0] - ax) * (bx - ax) + (mid[1] - ay) * (by - ay)) / (side.length ** 2 || 1);
    if (Math.abs(cross) < 1e-3 * Math.max(side.length, 1) && t >= -1e-6 && t <= 1 + 1e-6)
      return side.index;
  }
  return null;
}
