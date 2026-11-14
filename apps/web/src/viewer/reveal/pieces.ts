// The pieces of the construction: thin flat slices that settle on an element's surfaces just
// ahead of its growing front and are gone as soon as the front has passed them — courses being
// laid, never a cloud that turns into a wall. Pure (no GPU, no clock): targets are sampled on
// the geometry the viewer draws (area-weighted, PRNG seeded by the model hash) and snapped to
// courses in the surface plane; a slice lies flat on its surface (thin axis = surface normal,
// long axis horizontal) and is drawn in the real material of the face it lies on.
import { Matrix4, Quaternion, Vector3 } from "three";

import { type ConstructionSchedule, frontTime } from "./order";
import { sampleSurfaces, type SurfaceSource } from "./sampling";

/** One renderable part of an item: geometry, placement and its material keys. */
export interface PiecePart extends SurfaceSource {
  /** Library material key per geometry material group (what the real mesh is drawn with). */
  materials: readonly string[];
}

/** Everything that grows as one unit (an element, the site). */
export interface PieceItem {
  key: string;
  parts: readonly PiecePart[];
  /** Relative piece density (1 = full share; less for small details and hidden layers). */
  density?: number;
}

export interface PieceConfig {
  /** Hard ceiling of the piece count. */
  maxPieces: number;
  /** Fewest pieces an item gets, so small elements are visibly built too. */
  minPerItem: number;
  /** Largest share of a surface that pieces cover. */
  fill: number;
  /** A slice at full size: long (horizontal) × short × thick, meters. */
  length: number;
  height: number;
  thickness: number;
  /** Scaled to the element: `perRootArea × √(item surface)`, within [minScale, 1]. */
  perRootArea: number;
  minScale: number;
  /** Share of its cell a slice fills (the rest is the joint). */
  joint: number;
}

/** A run of pieces drawn with one material (one instanced draw call). */
export interface PieceBatch {
  material: string;
  offset: number;
  count: number;
}

export interface PieceTargets {
  count: number;
  /** xyz per piece, model space (Z-up): the centre of the slice where it lies. */
  target: Float32Array;
  /** Rotation (xyzw): local x = long axis, y = short axis, z = surface normal. */
  quat: Float32Array;
  /** Slice size (long, short, thick), meters. */
  scale: Float32Array;
  /** Texture coordinates of the slice centre in meters (the surface's own projection). */
  uv: Float32Array;
  /** One random number in [0, 1) per piece. */
  seed: Float32Array;
  /** Index into `keys`: the item each piece belongs to. */
  item: Uint32Array;
  keys: readonly string[];
  /** Pieces are grouped by material: each batch is a contiguous run. */
  batches: readonly PieceBatch[];
  /** Number of pieces per item key. */
  counts: ReadonlyMap<string, number>;
}

/** Normals with z below this face down: nothing is laid from below. */
const DOWN = -0.5;
/** Normals with |z| above this are floors, slab tops and flat roofs. */
const FLAT = 0.9;
/**
 * A flat face this close to the element's top is reached by the front all at once, at the
 * very end: pieces there would only flash, so it gets none (the element's sides carry them).
 */
const TOP_FACE = 0.02;

/** Size factor of an item's slices for its surface area. */
export function pieceScale(area: number, cfg: PieceConfig): number {
  return Math.min(Math.max(cfg.perRootArea * Math.sqrt(area), cfg.minScale), 1);
}

interface Draft {
  x: number;
  y: number;
  z: number;
  q: [number, number, number, number];
  s: [number, number, number];
  u: number;
  v: number;
  seed: number;
  item: number;
}

/**
 * Piece targets for the items, in the given order. The count adapts to the total surface (at
 * most `maxPieces`): each item gets a share by its area and density. Same items + same seed =
 * same pieces.
 */
export function samplePieces(
  items: readonly PieceItem[],
  seed: string,
  cfg: PieceConfig,
): PieceTargets {
  // First pass: area and slice size per item, to share the budget.
  const drafts = items.map((item) => {
    const probe = sampleSurfaces(item.parts, 0, "");
    const size = pieceScale(probe.area, cfg);
    const cell = cfg.length * size * cfg.height * size;
    const { corners, cumulative } = probe.triangles;
    let top = -Infinity;
    for (let i = 2; i < corners.length; i += 3) top = Math.max(top, corners[i]!);
    let laid = 0; // area that takes pieces
    for (let i = 0; i < cumulative.length; i++) {
      const area = cumulative[i]! - (i > 0 ? cumulative[i - 1]! : 0);
      const o = i * 9;
      const ux = corners[o + 3]! - corners[o]!;
      const uy = corners[o + 4]! - corners[o + 1]!;
      const vx = corners[o + 6]! - corners[o]!;
      const vy = corners[o + 7]! - corners[o + 1]!;
      if (!(area > 0)) continue;
      const nz = (ux * vy - uy * vx) / (2 * area);
      if (nz < DOWN || (nz > FLAT && corners[o + 2]! > top - TOP_FACE)) continue;
      laid += area;
    }
    const cells = laid / cell;
    const share = probe.area > 0 ? laid / probe.area : 0;
    return { item, area: probe.area, size, share, cells, top, full: cells * (item.density ?? 1) };
  });
  const full = drafts.reduce((s, d) => s + d.full, 0);
  const budget = Math.max(cfg.maxPieces - cfg.minPerItem * items.length, 0);
  const fill = full > 0 ? Math.min(cfg.fill, budget / full) : 0;

  const byMaterial = new Map<string, Draft[]>();
  const counts = new Map<string, number>();
  const keys: string[] = [];
  const n = new Vector3();
  const t = new Vector3();
  const b = new Vector3();
  const axis = new Vector3();
  const up = new Vector3(0, 0, 1);
  const basis = new Matrix4();
  const q = new Quaternion();
  let count = 0;

  for (const d of drafts) {
    const index = keys.push(d.item.key) - 1;
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
    const cw = cfg.length * d.size;
    const ch = cfg.height * d.size;
    const thick = cfg.thickness * d.size;
    let placed = 0;
    for (let i = 0; i < draw && placed < want; i++) {
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
      if (n.z < DOWN || (n.z > FLAT && corners[o + 2]! > d.top - TOP_FACE)) continue;
      const part = d.item.parts[source[tri]!]!;
      if (Math.abs(n.z) > FLAT) {
        // A flat surface: the long axis runs with the element (its own x axis in the plane).
        for (let column = 0; column < 3; column++) {
          axis.setFromMatrixColumn(part.matrix, column).normalize();
          t.copy(axis).addScaledVector(n, -axis.dot(n));
          if (t.lengthSq() > 0.12) break;
        }
        t.normalize();
      } else {
        // Walls and slopes: the long axis is horizontal, so courses run level.
        t.crossVectors(up, n).normalize();
      }
      b.crossVectors(n, t);
      // Snap to courses in the surface plane (running bond: every other course is shifted).
      const px = sample.positions[i * 3]!;
      const py = sample.positions[i * 3 + 1]!;
      const pz = sample.positions[i * 3 + 2]!;
      const u = px * t.x + py * t.y + pz * t.z;
      const v = px * b.x + py * b.y + pz * b.z;
      const row = Math.round(v / ch);
      const shift = row % 2 !== 0 ? 0.5 : 0;
      const col = Math.round(u / cw - shift);
      const su = (col + shift) * cw;
      const sv = row * ch;
      const x = px + (su - u) * t.x + (sv - v) * b.x + n.x * thick * 0.5;
      const y = py + (su - u) * t.y + (sv - v) * b.y + n.y * thick * 0.5;
      const z = pz + (su - u) * t.z + (sv - v) * b.z + n.z * thick * 0.5;
      const cell = `${Math.round(x * 1000)},${Math.round(y * 1000)},${Math.round(z * 1000)}`;
      if (used.has(cell)) continue; // one piece per cell
      used.add(cell);

      basis.makeBasis(t, b, n);
      q.setFromRotationMatrix(basis);
      const key = part.materials[material[tri]!] ?? part.materials[0] ?? "";
      let list = byMaterial.get(key);
      if (!list) byMaterial.set(key, (list = []));
      list.push({
        x,
        y,
        z,
        q: [q.x, q.y, q.z, q.w],
        s: [cw * cfg.joint, ch * cfg.joint, thick],
        u: su,
        v: sv,
        seed: sample.seeds[i * 4]!,
        item: index,
      });
      placed++;
    }
    count += placed;
    if (placed > 0) counts.set(d.item.key, placed);
  }

  const target = new Float32Array(count * 3);
  const quat = new Float32Array(count * 4);
  const scale = new Float32Array(count * 3);
  const uv = new Float32Array(count * 2);
  const seeds = new Float32Array(count);
  const item = new Uint32Array(count);
  const batches: PieceBatch[] = [];
  let at = 0;
  for (const [material, list] of byMaterial) {
    batches.push({ material, offset: at, count: list.length });
    for (const p of list) {
      target.set([p.x, p.y, p.z], at * 3);
      quat.set(p.q, at * 4);
      scale.set(p.s, at * 3);
      uv.set([p.u, p.v], at * 2);
      seeds[at] = p.seed;
      item[at] = p.item;
      at++;
    }
  }
  return { count, target, quat, scale, uv, seed: seeds, item, keys, batches, counts };
}

/** A piece that is never shown (its item is not scheduled). */
export const NEVER = 1e9;

export interface PieceMotionConfig {
  /** Largest time a piece is early at the front (a little irregularity; seconds). */
  jitter: number;
}

/**
 * When the growing front of its element reaches each piece (seconds; `NEVER` for an item
 * that is not scheduled). A piece settles onto the front just before that moment and sinks
 * into the surface right after it, so pieces exist only at the growing front.
 */
export function animatePieces(pieces: PieceTargets, schedule: ConstructionSchedule): Float32Array {
  const time = new Float32Array(pieces.count);
  for (let i = 0; i < pieces.count; i++) {
    const timing = schedule.timings.get(pieces.keys[pieces.item[i]!]!);
    time[i] = timing ? frontTime(timing, pieces.target[i * 3 + 2]!) : NEVER;
  }
  return time;
}

export interface PieceMotionConfig {
  /** Distance a piece comes from (above and outside its place), meters. */
  approach: number;
  /** Time it takes to settle (ease-out), pressing the last `settleDrop` meters into place. */
  settle: number;
  settleDrop: number;
  /** Time it takes to sink into the surface once the front has passed. */
  absorb: number;
  /** A piece is in place up to this long before the front reaches it (× its seed). */
  early: number;
}

/**
 * Where a piece is `elapsed` seconds into the build — the same arithmetic as the vertex
 * shader (gpu.ts), for tests. `front` is the moment the front reaches it: the piece is
 * `visible` only around that moment; `offset` is its distance from its place (meters),
 * `size` its scale (0..1).
 */
export function pieceState(
  front: number,
  seed: number,
  elapsed: number,
  cfg: PieceMotionConfig,
): { visible: boolean; offset: number; size: number } {
  const appear = front - seed * cfg.early - cfg.settle;
  const k = Math.min(Math.max((elapsed - appear) / cfg.settle, 0), 1);
  const visible = elapsed >= appear && elapsed < front + cfg.absorb;
  const ease = 1 - (1 - k) ** 3;
  const smooth = (a: number, c: number, x: number) => {
    const s = Math.min(Math.max((x - a) / (c - a), 0), 1);
    return s * s * (3 - 2 * s);
  };
  const out = 1 - smooth(front, front + cfg.absorb, elapsed);
  return {
    visible,
    offset: cfg.approach * (1 - ease) + cfg.settleDrop * (1 - smooth(0.7, 1, k)),
    size: visible ? smooth(0, 0.35, k) * out : 0,
  };
}
