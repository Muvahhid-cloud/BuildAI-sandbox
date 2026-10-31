// Small, pure 2D helpers for plan drawings (model plan coordinates, meters).
import type { P2 } from "../math/polygon";
import { bbox } from "../math/polygon";
import { EPS } from "../model/types";

/** A local 2D frame: origin + rotation about Z (an element's position / rotation.z). */
export interface Frame2 {
  x: number;
  y: number;
  angle: number;
}

export function toModel(f: Frame2, [u, v]: P2): P2 {
  const c = Math.cos(f.angle);
  const s = Math.sin(f.angle);
  return [f.x + u * c - v * s, f.y + u * s + v * c];
}

export function mapPts(f: Frame2, pts: readonly P2[]): P2[] {
  return pts.map((p) => toModel(f, p));
}

/** Axis-aligned rectangle [u0,u1]×[v0,v1] in a local frame, as a closed point list. */
export function rect(u0: number, v0: number, u1: number, v1: number): P2[] {
  return [
    [u0, v0],
    [u1, v0],
    [u1, v1],
    [u0, v1],
  ];
}

/** Circular arc as a polyline (renderer-independent; arcs are short in plans). */
export function arcPts(center: P2, r: number, a0: number, a1: number, segments = 16): P2[] {
  const pts: P2[] = [];
  for (let i = 0; i <= segments; i++) {
    const a = a0 + ((a1 - a0) * i) / segments;
    pts.push([center[0] + r * Math.cos(a), center[1] + r * Math.sin(a)]);
  }
  return pts;
}

export function ellipsePts(center: P2, rx: number, ry: number, segments = 24): P2[] {
  const pts: P2[] = [];
  for (let i = 0; i < segments; i++) {
    const a = (2 * Math.PI * i) / segments;
    pts.push([center[0] + rx * Math.cos(a), center[1] + ry * Math.sin(a)]);
  }
  return pts;
}

/** Even-odd point-in-polygon test (points on an edge count as inside). */
export function insidePolygon([x, y]: P2, pts: readonly P2[]): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i];
    const [xj, yj] = pts[j];
    if (onSegment([x, y], pts[j], pts[i])) return true;
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function onSegment([x, y]: P2, [ax, ay]: P2, [bx, by]: P2): boolean {
  const cross = (bx - ax) * (y - ay) - (by - ay) * (x - ax);
  if (Math.abs(cross) > EPS) return false;
  return (
    x >= Math.min(ax, bx) - EPS &&
    x <= Math.max(ax, bx) + EPS &&
    y >= Math.min(ay, by) - EPS &&
    y <= Math.max(ay, by) + EPS
  );
}

/** Distance from a point to the polygon's boundary. */
export function distanceToBoundary([x, y]: P2, pts: readonly P2[]): number {
  let d = Infinity;
  for (let i = 0; i < pts.length; i++) {
    const [ax, ay] = pts[i];
    const [bx, by] = pts[(i + 1) % pts.length];
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 < EPS ? 0 : Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / len2));
    d = Math.min(d, Math.hypot(x - (ax + t * dx), y - (ay + t * dy)));
  }
  return d;
}

/**
 * Where a room label goes: the bounding-box center when it lies well inside (rectangles),
 * otherwise the point of a fixed grid farthest from the boundary (L-shaped rooms).
 * Deterministic: a fixed grid, ties keep the first point in scan order.
 */
export function labelPoint(pts: readonly P2[]): P2 {
  const b = bbox(pts);
  const center: P2 = [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
  const half = Math.min(b.maxX - b.minX, b.maxY - b.minY) / 2;
  if (insidePolygon(center, pts) && distanceToBoundary(center, pts) > half * 0.6) return center;
  const n = 24;
  let best = center;
  let bestD = -1;
  for (let i = 1; i < n; i++) {
    for (let j = 1; j < n; j++) {
      const p: P2 = [b.minX + ((b.maxX - b.minX) * i) / n, b.minY + ((b.maxY - b.minY) * j) / n];
      if (!insidePolygon(p, pts)) continue;
      const d = distanceToBoundary(p, pts);
      if (d > bestD + EPS) {
        bestD = d;
        best = p;
      }
    }
  }
  return best;
}

/**
 * Parallel hatch lines clipped to a simple polygon. `angle` = 0 hatches with vertical lines
 * (lines of constant x), π/2 with horizontal ones. Lines start half a spacing in from the
 * bounding box, so they never pass exactly through rectilinear vertices.
 */
export function hatchLines(pts: readonly P2[], spacing: number, vertical = true): [P2, P2][] {
  const b = bbox(pts);
  const out: [P2, P2][] = [];
  const lo = vertical ? b.minX : b.minY;
  const hi = vertical ? b.maxX : b.maxY;
  for (let c = lo + spacing / 2; c < hi - EPS; c += spacing) {
    const hits: number[] = [];
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i];
      const z = pts[(i + 1) % pts.length];
      const [a0, a1, z0, z1] = vertical ? [a[0], a[1], z[0], z[1]] : [a[1], a[0], z[1], z[0]];
      if ((a0 <= c && c < z0) || (z0 <= c && c < a0))
        hits.push(a1 + ((c - a0) * (z1 - a1)) / (z0 - a0));
    }
    hits.sort((p, q) => p - q);
    for (let k = 0; k + 1 < hits.length; k += 2) {
      out.push(
        vertical
          ? [
              [c, hits[k]],
              [c, hits[k + 1]],
            ]
          : [
              [hits[k], c],
              [hits[k + 1], c],
            ],
      );
    }
  }
  return out;
}

export interface LabelPlacement {
  at: P2;
  vertical: boolean;
}

interface Box {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

function boxFits(cx: number, cy: number, hw: number, hh: number, pts: readonly P2[]): boolean {
  const probes: P2[] = [
    [cx - hw, cy - hh],
    [cx + hw, cy - hh],
    [cx + hw, cy + hh],
    [cx - hw, cy + hh],
    [cx, cy - hh],
    [cx, cy + hh],
    [cx - hw, cy],
    [cx + hw, cy],
  ];
  if (!probes.every((p) => insidePolygon(p, pts))) return false;
  // No boundary vertex may poke into the box (rectilinear rooms with notches).
  return !pts.some(
    ([x, y]) => x > cx - hw + EPS && x < cx + hw - EPS && y > cy - hh + EPS && y < cy + hh - EPS,
  );
}

function boxHits(
  cx: number,
  cy: number,
  hw: number,
  hh: number,
  obstacles: readonly Box[],
): boolean {
  return obstacles.some(
    (o) => o.minX < cx + hw && o.maxX > cx - hw && o.minY < cy + hh && o.maxY > cy - hh,
  );
}

/**
 * Where a label block of `width` × `height` (meters, unrotated) goes in a room: inside the
 * outline and clear of `obstacles` (furniture) if possible, horizontal before vertical.
 * Among equal candidates the one farthest from the walls (capped) and then nearest the
 * room's center wins. Fixed grid, strict comparisons: deterministic. Null when nothing fits.
 */
export function placeLabel(
  pts: readonly P2[],
  width: number,
  height: number,
  obstacles: readonly Box[],
): LabelPlacement | null {
  const b = bbox(pts);
  const cx0 = (b.minX + b.maxX) / 2;
  const cy0 = (b.minY + b.maxY) / 2;
  const n = 32;
  let best: { rank: number; score: number; center: number; at: LabelPlacement } | null = null;
  for (const vertical of [false, true]) {
    const hw = (vertical ? height : width) / 2 + 0.05;
    const hh = (vertical ? width : height) / 2 + 0.05;
    for (let i = 0; i <= n; i++) {
      for (let j = 0; j <= n; j++) {
        const x = b.minX + ((b.maxX - b.minX) * i) / n;
        const y = b.minY + ((b.maxY - b.minY) * j) / n;
        if (!boxFits(x, y, hw, hh, pts)) continue;
        const clear = !boxHits(x, y, hw, hh, obstacles);
        const rank = (clear ? 2 : 0) + (vertical ? 0 : 1);
        const score = Math.min(distanceToBoundary([x, y], pts), 0.8);
        const center = Math.hypot(x - cx0, y - cy0);
        if (
          !best ||
          rank > best.rank ||
          (rank === best.rank && score > best.score + EPS) ||
          (rank === best.rank && Math.abs(score - best.score) <= EPS && center < best.center - EPS)
        ) {
          best = { rank, score, center, at: { at: [x, y], vertical } };
        }
      }
    }
  }
  return best?.at ?? null;
}

/** Approximate text width in paper mm for a sans-serif face (used to fit labels). */
export function textWidthMm(text: string, size: number): number {
  return text.length * size * 0.56;
}
