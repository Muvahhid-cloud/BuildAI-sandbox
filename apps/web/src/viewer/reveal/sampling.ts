// Target points of the build reveal's pieces: sampled on the triangles of the geometry the viewer draws
// (the scene's render descriptors), area-weighted, with a seeded PRNG. Pure: no GPU, no clock.
import type { BufferGeometry, Matrix4 } from "three";

import { seededRandom } from "./prng";

/** What sampling needs of a render descriptor (engine/builders/types.ts). */
export interface SurfaceSource {
  geometry: BufferGeometry;
  /** Element-local -> model space. */
  matrix: Matrix4;
}

export interface SurfaceSample {
  /** xyz per point, model space (Z-up, meters). */
  positions: Float32Array;
  /** Four random numbers in [0, 1) per point (start jitter, arrival jitter). */
  seeds: Float32Array;
  /** Index into `triangles` of the triangle each point lies on. */
  triangle: Uint32Array;
  /** The triangles that were sampled (corners, source and material of each). */
  triangles: Triangles;
  /** Model-space height range of the sampled surfaces. */
  minZ: number;
  maxZ: number;
  /** Total sampled surface area (m²). */
  area: number;
}

export interface Triangles {
  /** 9 numbers per triangle: three model-space corners. */
  corners: Float32Array;
  /** Index of the source each triangle comes from. */
  source: Uint32Array;
  /** Material index of the triangle's geometry group (0 without groups). */
  material: Uint16Array;
  /** Running total of triangle areas (area-weighted choice by binary search). */
  cumulative: Float64Array;
}

/** Every triangle of the sources in model space, with cumulative areas. Degenerate ones drop out. */
export function collectTriangles(sources: readonly SurfaceSource[]): Triangles {
  let count = 0;
  for (const s of sources) {
    const index = s.geometry.getIndex();
    const position = s.geometry.getAttribute("position");
    if (!position) continue;
    count += Math.floor((index ? index.count : position.count) / 3);
  }
  const corners = new Float32Array(count * 9);
  const cumulative = new Float64Array(count);
  const source = new Uint32Array(count);
  const material = new Uint16Array(count);
  let n = 0;
  let total = 0;
  const p = [0, 0, 0, 0, 0, 0, 0, 0, 0];
  for (let si = 0; si < sources.length; si++) {
    const s = sources[si]!;
    const index = s.geometry.getIndex();
    const position = s.geometry.getAttribute("position");
    if (!position) continue;
    const groups = s.geometry.groups;
    const e = s.matrix.elements;
    const tris = Math.floor((index ? index.count : position.count) / 3);
    for (let t = 0; t < tris; t++) {
      for (let c = 0; c < 3; c++) {
        const i = index ? index.getX(t * 3 + c) : t * 3 + c;
        const x = position.getX(i);
        const y = position.getY(i);
        const z = position.getZ(i);
        p[c * 3] = e[0]! * x + e[4]! * y + e[8]! * z + e[12]!;
        p[c * 3 + 1] = e[1]! * x + e[5]! * y + e[9]! * z + e[13]!;
        p[c * 3 + 2] = e[2]! * x + e[6]! * y + e[10]! * z + e[14]!;
      }
      const ux = p[3]! - p[0]!;
      const uy = p[4]! - p[1]!;
      const uz = p[5]! - p[2]!;
      const vx = p[6]! - p[0]!;
      const vy = p[7]! - p[1]!;
      const vz = p[8]! - p[2]!;
      const area = 0.5 * Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx);
      if (!(area > 1e-10)) continue;
      corners.set(p, n * 9);
      source[n] = si;
      const group = groups.find((g) => t * 3 >= g.start && t * 3 < g.start + g.count);
      material[n] = group?.materialIndex ?? 0;
      total += area;
      cumulative[n] = total;
      n++;
    }
  }
  return {
    corners: corners.subarray(0, n * 9),
    cumulative: cumulative.subarray(0, n),
    source: source.subarray(0, n),
    material: material.subarray(0, n),
  };
}

/**
 * `count` points on the surfaces of `sources`, each triangle chosen with probability
 * proportional to its area and each point uniform inside its triangle. The same sources (in
 * the same order) and the same `seed` give identical output. No surfaces: zero points.
 */
export function sampleSurfaces(
  sources: readonly SurfaceSource[],
  count: number,
  seed: string,
): SurfaceSample {
  const collected = collectTriangles(sources);
  const { corners, cumulative } = collected;
  const triangles = cumulative.length;
  const total = triangles > 0 ? cumulative[triangles - 1]! : 0;
  const n = triangles > 0 ? Math.max(0, Math.floor(count)) : 0;
  const positions = new Float32Array(n * 3);
  const seeds = new Float32Array(n * 4);
  const triangle = new Uint32Array(n);
  const random = seededRandom(seed);
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (let i = 0; i < n; i++) {
    const pick = random() * total;
    let lo = 0;
    let hi = triangles - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (cumulative[mid]! < pick) lo = mid + 1;
      else hi = mid;
    }
    // Uniform in the triangle: reflect (u, v) into the lower half of the unit square.
    let u = random();
    let v = random();
    if (u + v > 1) {
      u = 1 - u;
      v = 1 - v;
    }
    const w = 1 - u - v;
    const o = lo * 9;
    const x = w * corners[o]! + u * corners[o + 3]! + v * corners[o + 6]!;
    const y = w * corners[o + 1]! + u * corners[o + 4]! + v * corners[o + 7]!;
    const z = w * corners[o + 2]! + u * corners[o + 5]! + v * corners[o + 8]!;
    positions.set([x, y, z], i * 3);
    triangle[i] = lo;
    seeds.set([random(), random(), random(), random()], i * 4);
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }
  if (n === 0) {
    minZ = 0;
    maxZ = 0;
  }
  return { positions, seeds, triangle, triangles: collected, minZ, maxZ, area: total };
}
