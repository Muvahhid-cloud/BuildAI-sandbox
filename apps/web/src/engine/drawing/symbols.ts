// Plan symbols for furniture, openings and stairs. Each function returns items in MODEL plan
// coordinates; shapes come only from the element's own dimensions (no fixed catalog sizes).
import type { FurnitureKind } from "@buildai/schema";

import type { P2 } from "../math/polygon";
import { axisOf, wallThicknessRange } from "../math/transform";
import type { ModelIndex } from "../model/model-index";
import type { Door, Furniture, Room, Stair, Wall, Window } from "../model/types";
import { arcPts, ellipsePts, type Frame2, insidePolygon, mapPts, rect, toModel } from "./plan-math";
import { type DrawItem, line, poly } from "./primitives";

// ---------------------------------------------------------------- furniture

type LocalItem =
  { kind: "poly"; pts: P2[]; closed: boolean } | { kind: "circle"; c: P2; r: number };

const box = (u0: number, v0: number, u1: number, v1: number): LocalItem => ({
  kind: "poly",
  pts: rect(u0, v0, u1, v1),
  closed: true,
});
const seg = (a: P2, b: P2): LocalItem => ({ kind: "poly", pts: [a, b], closed: false });
const ring = (c: P2, r: number): LocalItem => ({ kind: "circle", c, r });

type Symbol = (w: number, d: number) => LocalItem[];

/** Outline + seat/back/arms. Local frame: center origin, front faces -y, back is +y. */
function seat(arm: number): Symbol {
  return (w, d) => {
    const back = Math.min(0.22, d * 0.25);
    const items = [
      box(-w / 2, -d / 2, w / 2, d / 2),
      seg([-w / 2, d / 2 - back], [w / 2, d / 2 - back]),
    ];
    if (arm > 0) {
      items.push(seg([-w / 2 + arm, -d / 2], [-w / 2 + arm, d / 2 - back]));
      items.push(seg([w / 2 - arm, -d / 2], [w / 2 - arm, d / 2 - back]));
    }
    return items;
  };
}

const plain: Symbol = (w, d) => [box(-w / 2, -d / 2, w / 2, d / 2)];

const FURNITURE_SYMBOLS: Record<FurnitureKind, Symbol> = {
  sofa: seat(0.18),
  armchair: seat(0.16),
  coffee_table: plain,
  dining_table: plain,
  desk: plain,
  nightstand: plain,
  kitchen_island: plain,
  chair: (w, d) => [
    box(-w / 2, -d / 2, w / 2, d / 2),
    seg([-w / 2, d / 2 - 0.06], [w / 2, d / 2 - 0.06]),
  ],
  tv_unit: (w, d) => [box(-w / 2, -d / 2, w / 2, d / 2), seg([-w * 0.375, 0], [w * 0.375, 0])],
  bed: (w, d) => {
    const items = [box(-w / 2, -d / 2, w / 2, d / 2)];
    const pw = Math.min(0.7, w / 2 - 0.1);
    for (const sx of w > 1.2 ? [-1, 1] : [0]) {
      const cx = sx * (w / 4);
      items.push(box(cx - pw / 2, d / 2 - 0.55, cx + pw / 2, d / 2 - 0.15));
    }
    // Folded-back cover: a line across and the corner of the fold.
    const fold = d / 2 - 0.7;
    items.push(seg([-w / 2, fold], [w / 2, fold]));
    items.push({
      kind: "poly",
      pts: [
        [-w / 2, fold],
        [w / 2 - 0.05, fold - 0.45],
        [w / 2, fold],
      ],
      closed: false,
    });
    return items;
  },
  wardrobe: (w, d) => {
    const items = [box(-w / 2, -d / 2, w / 2, d / 2), seg([-w / 2, 0], [w / 2, 0])];
    const n = Math.max(2, Math.floor(w / 0.12));
    for (let i = 1; i < n; i++) {
      const u = -w / 2 + (i * w) / n;
      items.push(seg([u, -d * 0.3], [u, d * 0.3]));
    }
    return items;
  },
  bookshelf: (w, d) => [box(-w / 2, -d / 2, w / 2, d / 2), seg([-w / 2, -d / 2], [w / 2, d / 2])],
  kitchen_counter: (w, d) => {
    const items = [box(-w / 2, -d / 2, w / 2, d / 2)];
    // Sink where the 3D placeholder puts it, hob at the other end when the run is long enough.
    const sx = w * 0.15;
    items.push(box(sx - 0.3, -0.2, sx + 0.3, 0.2), box(sx - 0.26, -0.16, sx - 0.02, 0.16));
    if (w >= 1.6) {
      const hx = -w / 2 + 0.45;
      for (const [dx, dy] of [
        [-0.15, -0.12],
        [0.15, -0.12],
        [-0.15, 0.12],
        [0.15, 0.12],
      ] as P2[])
        items.push(ring([hx + dx, dy], 0.08));
    }
    return items;
  },
  fridge: (w, d) => [
    box(-w / 2, -d / 2, w / 2, d / 2),
    seg([-w / 2, -d / 2 + 0.06], [w / 2, -d / 2 + 0.06]),
  ],
  toilet: (w, d) => [
    box(-w / 2, d / 2 - d * 0.28, w / 2, d / 2),
    { kind: "poly", pts: ellipsePts([0, -d * 0.12], w * 0.38, d * 0.34), closed: true },
  ],
  basin: (w, d) => [box(-w / 2, -d / 2, w / 2, d / 2), ring([0, -d * 0.05], Math.min(w, d) * 0.32)],
  bathtub: (w, d) => [
    box(-w / 2, -d / 2, w / 2, d / 2),
    box(-w / 2 + 0.07, -d / 2 + 0.07, w / 2 - 0.07, d / 2 - 0.07),
    ring([-w / 2 + 0.25, 0], 0.03),
  ],
  shower: (w, d) => [
    box(-w / 2, -d / 2, w / 2, d / 2),
    seg([-w / 2, -d / 2], [w / 2, d / 2]),
    ring([w / 2 - 0.15, d / 2 - 0.15], 0.05),
  ],
};

export function furnitureItems(item: Furniture): DrawItem[] {
  const f: Frame2 = { x: item.position.x, y: item.position.y, angle: item.rotation.z };
  const { width: w, depth: d } = item.dimensions;
  return FURNITURE_SYMBOLS[item.properties.furniture_kind](w, d).map((it) =>
    it.kind === "circle"
      ? { kind: "circle", center: toModel(f, it.c), r: it.r, pen: "furniture", fill: "none" }
      : poly(mapPts(f, it.pts), "furniture", it.closed, it.closed ? "paper" : "none"),
  );
}

// ---------------------------------------------------------------- openings

/** A wall's local frame: u along the axis from its start, v across (+v = left face). */
export function wallFrame(wall: Wall): Frame2 {
  return { x: wall.position.x, y: wall.position.y, angle: wall.rotation.z };
}

const GLASS_GAP = 0.03;

/**
 * Window in the wall gap: both wall faces, the jambs and a double glazing line, the drawing
 * convention of architectural plans at 1:100.
 */
export function windowItems(win: Window, host: Wall): DrawItem[] {
  const f = wallFrame(host);
  const [v0, v1] = wallThicknessRange(host);
  const u0 = win.position.x;
  const u1 = u0 + win.dimensions.width;
  const vm = (v0 + v1) / 2;
  return [
    poly(mapPts(f, rect(u0, v0, u1, v1)), "thin", true, "paper"),
    line(toModel(f, [u0, vm - GLASS_GAP]), toModel(f, [u1, vm - GLASS_GAP]), "thin"),
    line(toModel(f, [u0, vm + GLASS_GAP]), toModel(f, [u1, vm + GLASS_GAP]), "thin"),
  ];
}

/**
 * Which side of the host wall a door opens to (+1 = left face, -1 = right face). The model
 * stores the hinge side (`swing`) but not the direction, so the drawing uses a convention:
 * the leaf opens into the room the door `connects` to (front door into the entrance,
 * bedroom doors into the bedroom). Without such a room it opens to the left face, which is
 * the interior of counter-clockwise exterior walls.
 */
export function doorOpensTo(door: Door, host: Wall, index: ModelIndex): 1 | -1 {
  const f = wallFrame(host);
  const [v0, v1] = wallThicknessRange(host);
  const um = door.position.x + door.dimensions.width / 2;
  for (const rel of door.relationships) {
    if (rel.kind !== "connects") continue;
    const room = index.elementsById.get(rel.target_id);
    if (room?.type !== "room") continue;
    const outline = roomOutline(room);
    if (insidePolygon(toModel(f, [um, v1 + 0.3]), outline)) return 1;
    if (insidePolygon(toModel(f, [um, v0 - 0.3]), outline)) return -1;
  }
  return 1;
}

export function doorItems(door: Door, host: Wall, index: ModelIndex): DrawItem[] {
  const f = wallFrame(host);
  const [v0, v1] = wallThicknessRange(host);
  const u0 = door.position.x;
  const w = door.dimensions.width;
  const u1 = u0 + w;
  const items: DrawItem[] = [];
  // Jambs close the cut wall at both sides of the opening.
  items.push(line(toModel(f, [u0, v0]), toModel(f, [u0, v1]), "thin"));
  items.push(line(toModel(f, [u1, v0]), toModel(f, [u1, v1]), "thin"));

  const { door_kind: kind, swing } = door.properties;
  if (swing === "sliding" || kind === "sliding" || kind === "garage") {
    if (kind === "garage") {
      // Overhead / sectional door: the panel in the opening, its travel shown dashed.
      const vm = (v0 + v1) / 2;
      items.push(poly(mapPts(f, rect(u0, vm - 0.025, u1, vm + 0.025)), "thin", true, "paper"));
      const s = doorOpensTo(door, host, index);
      const vi = s > 0 ? v1 : v0;
      items.push(poly(mapPts(f, rect(u0, vi, u1, vi + s * Math.min(2.4, w))), "hidden", true));
      return items;
    }
    // Two panels on offset tracks, overlapping in the middle.
    const pw = w / 2 + 0.04;
    const vm = (v0 + v1) / 2;
    items.push(poly(mapPts(f, rect(u0, vm - 0.05, u0 + pw, vm - 0.01)), "thin", true, "paper"));
    items.push(poly(mapPts(f, rect(u1 - pw, vm + 0.01, u1, vm + 0.05)), "thin", true, "paper"));
    return items;
  }

  const s = doorOpensTo(door, host, index);
  const face = s > 0 ? v1 : v0;
  const leaves: [number, number, number][] =
    swing === "double"
      ? [
          [u0, w / 2, 1],
          [u1, w / 2, -1],
        ]
      : swing === "right"
        ? [[u1, w, -1]]
        : [[u0, w, 1]];
  for (const [hu, lw, dir] of leaves) {
    const hinge = toModel(f, [hu, face]);
    const tip = toModel(f, [hu, face + s * lw]);
    const closed = toModel(f, [hu + dir * lw, face]);
    items.push(line(hinge, tip, "thin"));
    const a0 = Math.atan2(tip[1] - hinge[1], tip[0] - hinge[0]);
    let a1 = Math.atan2(closed[1] - hinge[1], closed[0] - hinge[0]);
    // The swing is the quarter turn between the open leaf and the closed position.
    if (a1 - a0 > Math.PI) a1 -= 2 * Math.PI;
    if (a0 - a1 > Math.PI) a1 += 2 * Math.PI;
    items.push(poly(arcPts(hinge, lw, a0, a1), "fine"));
  }
  return items;
}

// ---------------------------------------------------------------- stairs

/**
 * Straight flight. Local frame (as the 3D builder): x along the run from the first riser,
 * y across the width. The lower floor shows the treads and an "UP" arrow from the first
 * riser; the upper floor shows the same flight seen through the void with "DN".
 */
export function stairItems(stair: Stair, onUpperLevel: boolean): DrawItem[] {
  const f: Frame2 = { x: stair.position.x, y: stair.position.y, angle: stair.rotation.z };
  const { width, run_length: run } = stair.dimensions;
  const { risers, tread_depth: t } = stair.properties;
  const items: DrawItem[] = [poly(mapPts(f, rect(0, 0, run, width)), "outline", true, "paper")];
  for (let i = 1; i < risers - 1 && i * t < run - 1e-6; i++) {
    items.push(line(toModel(f, [i * t, 0]), toModel(f, [i * t, width]), "fine"));
  }
  const y = width / 2;
  const from = onUpperLevel ? run - 0.15 : 0.15;
  const to = onUpperLevel ? 0.25 : run - 0.25;
  const dir = Math.sign(to - from);
  items.push(line(toModel(f, [from, y]), toModel(f, [to, y]), "thin"));
  items.push(
    poly(
      [
        toModel(f, [to - dir * 0.18, y - 0.09]),
        toModel(f, [to, y]),
        toModel(f, [to - dir * 0.18, y + 0.09]),
      ],
      "thin",
    ),
  );
  items.push(circleAt(toModel(f, [from, y]), 0.04));
  return items;
}

function circleAt(center: P2, r: number): DrawItem {
  return { kind: "circle", center, r, pen: "thin", fill: "none" };
}

// ---------------------------------------------------------------- rooms

/** Room boundary (wall centerlines) in model plan coordinates. */
export function roomOutline(room: Room): P2[] {
  const f: Frame2 = { x: room.position.x, y: room.position.y, angle: room.rotation.z };
  return mapPts(
    f,
    room.properties.boundary.map((p) => [p.x, p.y] as P2),
  );
}

/** A wall's axis as a segment in plan. */
export function wallAxis(wall: Wall): [P2, P2] {
  const { start, end } = axisOf(wall);
  return [start, end];
}
