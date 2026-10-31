// 2D drawing primitives (docs/3d-engine.md §19). A plan drawing is derived data: every group
// maps to at most one BuildingModel element and nothing here is ever stored or edited.
//
// Coordinates are MODEL plan coordinates (meters, +X east, +Y north). Pen widths and text
// sizes are PAPER millimeters at the drawing scale; the renderer converts.
import type { P2 } from "../math/polygon";

/** Line styles. Widths/colors live in the renderer (svg.ts), so every output looks the same. */
export type Pen =
  | "cut" // outline of cut construction (walls)
  | "outline" // visible edges below the cut plane: slabs, terraces, stair outline
  | "thin" // openings, door leaves, window frames
  | "fine" // door swing arcs, stair treads
  | "hidden" // dashed: open-plan boundaries, voids, overhead
  | "hatch" // terrace/balcony decking
  | "furniture"
  | "dim" // dimension and extension lines
  | "none";

/** `solid` = poché of cut walls; `hit` = invisible pointer target (interactive view only). */
export type Fill = "solid" | "paper" | "hit" | "none";

export type TextRole = "room" | "area" | "dim" | "note";

/** Text sizes in paper mm. */
export const TEXT_MM = { room: 3.0, area: 2.5, dim: 2.2, note: 2.0 } as const;

export type DrawItem =
  | { kind: "poly"; pts: P2[]; closed: boolean; pen: Pen; fill: Fill }
  | { kind: "circle"; center: P2; r: number; pen: Pen; fill: Fill }
  | {
      kind: "text";
      at: P2;
      text: string;
      role: TextRole;
      /** Paper mm (already fitted to the room / segment). */
      size: number;
      anchor: "start" | "middle" | "end";
      /** Reading direction in radians (0 = along +X; dimension text on vertical lines: π/2). */
      angle: number;
    };

export type GroupRole =
  "room" | "slab" | "furniture" | "stair" | "railing" | "wall" | "opening" | "label" | "dimension";

export interface DrawGroup {
  /** The model element this group draws (null for annotations: dimensions). */
  elementId: string | null;
  role: GroupRole;
  items: DrawItem[];
}

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export interface PlanDrawing {
  levelId: string;
  levelName: string;
  /** Drawing scale denominator the text was fitted for (100 = 1:100). */
  scale: number;
  /** Groups in paint order. */
  groups: DrawGroup[];
  /** The building on this level (walls, slabs, rooms) — without annotations. */
  extent: Bounds;
  /** Everything drawn, incl. dimension chains. */
  bounds: Bounds;
}

export function poly(pts: P2[], pen: Pen, closed = false, fill: Fill = "none"): DrawItem {
  return { kind: "poly", pts, closed, pen, fill };
}

export function line(a: P2, b: P2, pen: Pen): DrawItem {
  return poly([a, b], pen);
}

export function emptyBounds(): Bounds {
  return { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
}

export function extendBounds(b: Bounds, [x, y]: P2): void {
  b.minX = Math.min(b.minX, x);
  b.minY = Math.min(b.minY, y);
  b.maxX = Math.max(b.maxX, x);
  b.maxY = Math.max(b.maxY, y);
}

export function itemPoints(item: DrawItem): P2[] {
  switch (item.kind) {
    case "poly":
      return item.pts;
    case "circle":
      return [
        [item.center[0] - item.r, item.center[1] - item.r],
        [item.center[0] + item.r, item.center[1] + item.r],
      ];
    case "text":
      return [item.at];
  }
}

export function boundsOf(groups: readonly DrawGroup[]): Bounds {
  const b = emptyBounds();
  for (const g of groups)
    for (const it of g.items) for (const p of itemPoints(it)) extendBounds(b, p);
  return b;
}
