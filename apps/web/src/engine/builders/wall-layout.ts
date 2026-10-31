// Pure wall geometry rules: corner joins and panel decomposition (docs/3d-engine.md §4).
import { axisOf } from "../math/transform";
import { distanceToSegment, type P2 } from "../math/polygon";
import { EPS, type Wall } from "../model/types";

/** How far each wall end moves along the axis: > 0 extends, < 0 trims. */
export interface WallJoin {
  start: number;
  end: number;
}

type End = "start" | "end";

/**
 * Deterministic join rules between walls of the same level:
 *  - T-junction (this end lies inside another wall's axis): trim by half that wall's thickness.
 *  - L-corner (ends meet): the wall arriving ("end") extends by half the other's thickness,
 *    the wall leaving ("start") trims by the same amount — a pinwheel that closes corners
 *    without overlapping volumes. If both walls start (or both end) there, the wall with the
 *    smaller id extends.
 *  - Collinear continuation: no change.
 */
export function computeWallJoins(walls: readonly Wall[]): Map<string, WallJoin> {
  const sorted = [...walls].sort((a, b) => a.id.localeCompare(b.id));
  const axes = new Map(sorted.map((w) => [w.id, axisOf(w)]));
  const joins = new Map<string, WallJoin>();
  for (const w of sorted) {
    const join: WallJoin = { start: 0, end: 0 };
    const axis = axes.get(w.id)!;
    for (const end of ["start", "end"] as const) {
      const p = axis[end];
      const candidates: number[] = [];
      for (const o of sorted) {
        if (o.id === w.id || o.level_id !== w.level_id) continue;
        const oa = axes.get(o.id)!;
        if (distanceToSegment(p, oa.start, oa.end) > EPS) continue;
        const half = o.dimensions.thickness / 2;
        const oEnd: End | null = near(p, oa.start) ? "start" : near(p, oa.end) ? "end" : null;
        if (oEnd === null) {
          candidates.push(-half); // T-junction
          continue;
        }
        if (collinear(axis, oa)) continue;
        // Inside corner of an L footprint: an interior wall continues the line of an exterior
        // wall through the corner. The exterior walls close the corner between themselves
        // (pinwheel) and ignore the interior wall; the interior wall stops at the exterior
        // wall's inner face, like a T-junction. (Rectangular plans have no such corner.)
        if (isExterior(w) && !isExterior(o)) continue;
        if (!isExterior(w) && isExterior(o)) {
          candidates.push(-half);
          continue;
        }
        const extend = end !== oEnd ? end === "end" : w.id < o.id;
        candidates.push(extend ? half : -half);
      }
      const trims = candidates.filter((c) => c < 0);
      join[end] = trims.length > 0 ? Math.min(...trims) : Math.max(0, ...candidates);
    }
    joins.set(w.id, join);
  }
  return joins;
}

function isExterior(w: Wall): boolean {
  return w.properties.wall_kind === "exterior";
}

function near(a: P2, b: P2): boolean {
  return Math.hypot(a[0] - b[0], a[1] - b[1]) < EPS;
}

function collinear(a: { start: P2; end: P2 }, b: { start: P2; end: P2 }): boolean {
  const ax = a.end[0] - a.start[0];
  const ay = a.end[1] - a.start[1];
  const bx = b.end[0] - b.start[0];
  const by = b.end[1] - b.start[1];
  return Math.abs(ax * by - ay * bx) < EPS * Math.hypot(ax, ay) * Math.hypot(bx, by);
}

export interface OpeningSpan {
  u0: number;
  u1: number;
  z0: number;
  z1: number;
}

export interface WallPanel {
  kind: "full" | "sill" | "lintel";
  u0: number;
  u1: number;
  z0: number;
  z1: number;
}

/**
 * Panel decomposition (no CSG): the wall [u0, u1] x [0, height] minus rectangular openings is
 * covered by full-height panels between openings plus a sill panel below and a lintel panel
 * above each opening. Openings are clamped to the wall; overlapping openings are merged.
 */
export function wallPanels(
  u0: number,
  u1: number,
  height: number,
  openings: readonly OpeningSpan[],
): WallPanel[] {
  const panels: WallPanel[] = [];
  const spans = openings
    .map((o) => ({
      u0: Math.max(o.u0, u0),
      u1: Math.min(o.u1, u1),
      z0: Math.max(0, o.z0),
      z1: Math.min(height, o.z1),
    }))
    .filter((o) => o.u1 - o.u0 > EPS && o.z1 - o.z0 > EPS)
    .sort((a, b) => a.u0 - b.u0 || a.z0 - b.z0);
  let cursor = u0;
  for (const o of spans) {
    const start = Math.max(o.u0, cursor);
    if (start - cursor > EPS)
      panels.push({ kind: "full", u0: cursor, u1: start, z0: 0, z1: height });
    if (o.u1 - start > EPS) {
      if (o.z0 > EPS) panels.push({ kind: "sill", u0: start, u1: o.u1, z0: 0, z1: o.z0 });
      if (height - o.z1 > EPS)
        panels.push({ kind: "lintel", u0: start, u1: o.u1, z0: o.z1, z1: height });
    }
    cursor = Math.max(cursor, o.u1);
  }
  if (u1 - cursor > EPS) panels.push({ kind: "full", u0: cursor, u1, z0: 0, z1: height });
  return panels;
}
