import { EPS } from "../model/types";

export type P2 = [number, number];

export function signedArea(pts: readonly P2[]): number {
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % pts.length];
    a += x0 * y1 - x1 * y0;
  }
  return a / 2;
}

export function ensureCCW(pts: readonly P2[]): P2[] {
  return signedArea(pts) < 0 ? [...pts].reverse() : [...pts];
}

export function bbox(pts: readonly P2[]) {
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  return {
    minX: Math.min(...xs),
    minY: Math.min(...ys),
    maxX: Math.max(...xs),
    maxY: Math.max(...ys),
  };
}

/** Area-weighted centroid of a simple polygon. */
export function centroid(pts: readonly P2[]): P2 {
  const a = signedArea(pts);
  if (Math.abs(a) < EPS) return [pts[0][0], pts[0][1]];
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % pts.length];
    const f = x0 * y1 - x1 * y0;
    cx += (x0 + x1) * f;
    cy += (y0 + y1) * f;
  }
  return [cx / (6 * a), cy / (6 * a)];
}

/** Length of the collinear overlap between two segments (0 when not collinear). */
export function segmentOverlap(a: [P2, P2], b: [P2, P2]): number {
  const [[ax0, ay0], [ax1, ay1]] = a;
  const len = Math.hypot(ax1 - ax0, ay1 - ay0);
  if (len < EPS) return 0;
  const ux = (ax1 - ax0) / len;
  const uy = (ay1 - ay0) / len;
  for (const [px, py] of b) {
    if (Math.abs((px - ax0) * uy - (py - ay0) * ux) > EPS) return 0;
  }
  const t0 = (b[0][0] - ax0) * ux + (b[0][1] - ay0) * uy;
  const t1 = (b[1][0] - ax0) * ux + (b[1][1] - ay0) * uy;
  return Math.max(0, Math.min(len, Math.max(t0, t1)) - Math.max(0, Math.min(t0, t1)));
}

/** Distance from point p to segment ab. */
export function distanceToSegment(p: P2, a: P2, b: P2): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t =
    len2 < EPS ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

/**
 * Inset a CCW rectilinear polygon, moving each edge inward by its own distance.
 * Vertex i joins edge (i-1 -> i) and edge (i -> i+1); for axis-aligned edges the new vertex
 * takes x from the vertical edge and y from the horizontal one.
 */
export function insetRectilinear(pts: readonly P2[], insets: readonly number[]): P2[] {
  const n = pts.length;
  // Inward normal of a CCW edge (dx, dy) is (-dy, dx).
  const shifted = pts.map((_, i) => {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % n];
    const len = Math.hypot(x1 - x0, y1 - y0) || 1;
    const nx = -(y1 - y0) / len;
    const ny = (x1 - x0) / len;
    return { x: x0 + nx * insets[i], y: y0 + ny * insets[i], vertical: Math.abs(x1 - x0) < EPS };
  });
  return pts.map((_, i) => {
    const prev = shifted[(i - 1 + n) % n];
    const cur = shifted[i];
    const vertical = prev.vertical ? prev : cur;
    const horizontal = prev.vertical ? cur : prev;
    return [vertical.x, horizontal.y] as P2;
  });
}
