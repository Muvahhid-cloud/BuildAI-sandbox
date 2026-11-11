// The pieces of the build reveal: small blocks laid on the surfaces of the elements, like
// bricks on a wall plane. Pure (no GPU, no clock): targets are sampled on the geometry the
// viewer draws with a PRNG seeded by the model hash, snapped to courses in the surface plane;
// every piece starts at the base of its own element, directly under its target, and rises.
import { Color, Matrix4, Quaternion, Vector3 } from "three";

import type { ConstructionSchedule, StepExtent } from "./order";
import { sampleSurfaces, type SurfaceSource } from "./sampling";

/** One renderable part of an item: geometry, placement and the color of each material group. */
export interface PiecePart extends SurfaceSource {
  /** sRGB hex per geometry material group (the element's real library colors). */
  colors: readonly string[];
}

/** Everything that assembles as one unit (an element, the site, a plant). */
export interface PieceItem {
  key: string;
  parts: readonly PiecePart[];
  /** Relative piece density (1 = full share; less for small details and hidden layers). */
  density?: number;
}

export interface PieceConfig {
  /** Hard ceiling of the piece count (one instanced draw call). */
  maxPieces: number;
  /** Fewest pieces an item gets, so small elements still assemble. */
  minPerItem: number;
  /** Largest share of a surface that pieces cover. */
  fill: number;
  /** Piece edge: `perRootArea × √(item area)`, within [min, max] meters. */
  min: number;
  max: number;
  perRootArea: number;
  /** Height of a course on vertical surfaces, as a share of the edge (brick proportion). */
  course: number;
  /** Thickness as a share of the edge. */
  thickness: number;
  /** Share of its cell a piece fills (the rest is the joint). */
  joint: number;
  /** Largest horizontal distance between a piece's start and its target (meters). */
  startJitter: number;
}

export interface ItemRange {
  /** First piece and number of pieces of the item. */
  offset: number;
  count: number;
  /** Lowest and highest piece target: the element's base and top. */
  baseZ: number;
  topZ: number;
  /** Sampled surface area (m²) and the piece edge chosen for it. */
  area: number;
  edge: number;
}

export interface PieceTargets {
  count: number;
  /** xyz per piece, model space (Z-up): where the piece ends up. */
  target: Float32Array;
  /** Rotation (xyzw) that lays the piece on its surface: x/y in the plane, z along the normal. */
  quat: Float32Array;
  /** Piece size (in-plane x, in-plane y, thickness), meters. */
  scale: Float32Array;
  /** Linear RGB of the element's library color at the piece. */
  color: Float32Array;
  /** Three random numbers in [0, 1) per piece (start jitter x/y, arrival jitter). */
  seeds: Float32Array;
  ranges: ReadonlyMap<string, ItemRange>;
}

/** Normals with z below this face down. */
const DOWN = -0.5;

const edgeFor = (area: number, cfg: PieceConfig) =>
  Math.min(Math.max(cfg.perRootArea * Math.sqrt(area), cfg.min), cfg.max);

/**
 * Piece targets for the items, in the given order. The count adapts to the total surface (at
 * most `maxPieces`): each item gets a share by its area. Same items + same seed = same pieces.
 */
export function samplePieces(
  items: readonly PieceItem[],
  seed: string,
  cfg: PieceConfig,
): PieceTargets {
  // First pass: area and piece edge per item, to share the budget. Surfaces that face down
  // (soffits, undersides) get no pieces: nothing is laid from below.
  const drafts = items.map((item) => {
    const probe = sampleSurfaces(item.parts, 0, "");
    const edge = edgeFor(probe.area, cfg);
    const { corners, cumulative } = probe.triangles;
    let cells = 0; // pieces that would cover the item completely
    let laid = 0; // area that takes pieces
    for (let i = 0; i < cumulative.length; i++) {
      const area = cumulative[i]! - (i > 0 ? cumulative[i - 1]! : 0);
      const o = i * 9;
      const ux = corners[o + 3]! - corners[o]!;
      const uy = corners[o + 4]! - corners[o + 1]!;
      const vx = corners[o + 6]! - corners[o]!;
      const vy = corners[o + 7]! - corners[o + 1]!;
      const nz = (ux * vy - uy * vx) / (2 * area);
      if (nz < DOWN) continue;
      laid += area;
      cells += area / (edge * edge * (Math.abs(nz) < 0.5 ? cfg.course : 1));
    }
    const share = probe.area > 0 ? laid / probe.area : 0;
    return { item, area: probe.area, edge, share, cells, full: cells * (item.density ?? 1) };
  });
  const full = drafts.reduce((s, d) => s + d.full, 0);
  const budget = Math.max(cfg.maxPieces - cfg.minPerItem * items.length, 0);
  const fill = full > 0 ? Math.min(cfg.fill, budget / full) : 0;

  const target: number[] = [];
  const quat: number[] = [];
  const scale: number[] = [];
  const color: number[] = [];
  const seeds: number[] = [];
  const ranges = new Map<string, ItemRange>();
  const n = new Vector3();
  const t = new Vector3();
  const b = new Vector3();
  const axis = new Vector3();
  const basis = new Matrix4();
  const q = new Quaternion();
  const tint = new Color();
  const tints = new Map<string, [number, number, number]>();
  let count = 0;

  for (const d of drafts) {
    if (!(d.area > 0) || !(d.share > 0)) continue;
    const room = cfg.maxPieces - count;
    if (room <= 0) break;
    const want = Math.min(Math.max(Math.round(d.full * fill), cfg.minPerItem), room);
    // Several points can fall into one cell and points on downward faces are dropped, so more
    // are drawn to reach the item's share (random occupancy: n = -cells × ln(1 - coverage)).
    const coverage = Math.min(want / Math.max(d.cells, 1), 0.9);
    const draw = Math.ceil(Math.max(want, -d.cells * Math.log(1 - coverage)) / d.share);
    const sample = sampleSurfaces(d.item.parts, draw, `${seed}:${d.item.key}`);
    const { corners, source, material } = sample.triangles;
    const used = new Set<string>();
    const offset = count;
    let baseZ = Infinity;
    let topZ = -Infinity;
    for (let i = 0; i < draw && count - offset < want; i++) {
      const tri = sample.triangle[i]!;
      const o = tri * 9;
      // Surface normal from the triangle's winding.
      t.set(
        corners[o + 3]! - corners[o]!,
        corners[o + 4]! - corners[o + 1]!,
        corners[o + 5]! - corners[o + 2]!,
      );
      b.set(
        corners[o + 6]! - corners[o]!,
        corners[o + 7]! - corners[o + 1]!,
        corners[o + 8]! - corners[o + 2]!,
      );
      n.crossVectors(t, b).normalize();
      if (n.z < DOWN) continue;
      // In-plane x: the part's own x axis laid into the surface (its y or z axis for a face
      // across x), so pieces run along walls and with the element — never at a random angle.
      const part = d.item.parts[source[tri]!]!;
      for (let column = 0; column < 3; column++) {
        axis.setFromMatrixColumn(part.matrix, column).normalize();
        t.copy(axis).addScaledVector(n, -axis.dot(n));
        if (t.lengthSq() > 0.12) break;
      }
      t.normalize();
      b.crossVectors(n, t);
      const vertical = Math.abs(n.z) < 0.5;
      const cw = d.edge;
      const ch = vertical ? d.edge * cfg.course : d.edge;
      // Snap to courses in the surface plane (running bond on vertical surfaces).
      const px = sample.positions[i * 3]!;
      const py = sample.positions[i * 3 + 1]!;
      const pz = sample.positions[i * 3 + 2]!;
      const u = px * t.x + py * t.y + pz * t.z;
      const v = px * b.x + py * b.y + pz * b.z;
      const row = Math.round(v / ch);
      const shift = vertical && row % 2 !== 0 ? 0.5 : 0;
      const col = Math.round(u / cw - shift);
      const du = (col + shift) * cw - u;
      const dv = row * ch - v;
      const thick = d.edge * cfg.thickness;
      const x = px + du * t.x + dv * b.x + n.x * thick * 0.5;
      const y = py + du * t.y + dv * b.y + n.y * thick * 0.5;
      const z = pz + du * t.z + dv * b.z + n.z * thick * 0.5;
      const cell = `${Math.round(x * 1000)},${Math.round(y * 1000)},${Math.round(z * 1000)}`;
      if (used.has(cell)) continue; // one piece per cell
      used.add(cell);

      target.push(x, y, z);
      basis.makeBasis(t, b, n);
      q.setFromRotationMatrix(basis);
      quat.push(q.x, q.y, q.z, q.w);
      scale.push(cw * cfg.joint, ch * cfg.joint, thick);
      const hex = part.colors[material[tri]!] ?? part.colors[0] ?? "#ffffff";
      let rgb = tints.get(hex);
      if (!rgb) {
        tint.set(hex);
        rgb = [tint.r, tint.g, tint.b];
        tints.set(hex, rgb);
      }
      color.push(rgb[0], rgb[1], rgb[2]);
      seeds.push(sample.seeds[i * 4]!, sample.seeds[i * 4 + 1]!, sample.seeds[i * 4 + 2]!);
      if (z < baseZ) baseZ = z;
      if (z > topZ) topZ = z;
      count++;
    }
    if (count > offset) {
      ranges.set(d.item.key, {
        offset,
        count: count - offset,
        baseZ,
        topZ,
        area: d.area,
        edge: d.edge,
      });
    }
  }
  return {
    count,
    target: new Float32Array(target),
    quat: new Float32Array(quat),
    scale: new Float32Array(scale),
    color: new Float32Array(color),
    seeds: new Float32Array(seeds),
    ranges,
  };
}

/** Height of each item's pieces, for the schedule. */
export function pieceExtents(pieces: PieceTargets): Map<string, StepExtent> {
  const out = new Map<string, StepExtent>();
  for (const [key, r] of pieces.ranges) out.set(key, { height: r.topZ - r.baseZ });
  return out;
}

export interface PieceMotion {
  /** xyz per piece: where it starts — at its element's base, directly under its target. */
  start: Float32Array;
  /** Per piece: departure time, arrival time, time it starts to shrink away (seconds). */
  time: Float32Array;
}

/**
 * Start points and times of every piece. A piece leaves the base of its own element (within
 * `startJitter` of the point under its target) and rises straight up; lower pieces arrive
 * first (departure = element start + relative height × spread + a small jitter).
 */
export function animatePieces(
  pieces: PieceTargets,
  schedule: ConstructionSchedule,
  cfg: { rise: number; jitter: number; startJitter: number },
): PieceMotion {
  const start = new Float32Array(pieces.count * 3);
  const time = new Float32Array(pieces.count * 3);
  for (const [key, r] of pieces.ranges) {
    const timing = schedule.timings.get(key);
    const height = r.topZ - r.baseZ;
    for (let i = r.offset; i < r.offset + r.count; i++) {
      const z = pieces.target[i * 3 + 2]!;
      // Jitter inside a disc of radius startJitter.
      const angle = pieces.seeds[i * 3]! * 2 * Math.PI;
      const radius = Math.sqrt(pieces.seeds[i * 3 + 1]!) * cfg.startJitter;
      start[i * 3] = pieces.target[i * 3]! + Math.cos(angle) * radius;
      start[i * 3 + 1] = pieces.target[i * 3 + 1]! + Math.sin(angle) * radius;
      start[i * 3 + 2] = r.baseZ;
      if (!timing) {
        // Not scheduled: never shown.
        time[i * 3] = time[i * 3 + 1] = time[i * 3 + 2] = -1;
        continue;
      }
      // Relative height inside the element (a flat element lands at once).
      const level = height > 1e-3 ? Math.min(Math.max((z - r.baseZ) / height, 0), 1) : 0;
      const depart = timing.start + level * timing.spread + pieces.seeds[i * 3 + 2]! * cfg.jitter;
      time[i * 3] = depart;
      time[i * 3 + 1] = depart + cfg.rise;
      time[i * 3 + 2] = timing.vanish;
    }
  }
  return { start, time };
}
