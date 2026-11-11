import { BoxGeometry, BufferAttribute, BufferGeometry, Matrix4 } from "three";
import { describe, expect, it } from "vitest";

import { buildScene } from "@/engine/scene/build-scene";
import { demoIndex } from "@/engine/test-fixtures";

import { hashString, mulberry32, seededRandom } from "./prng";
import { collectTriangles, sampleSurfaces, type SurfaceSource } from "./sampling";

/** A triangle in the plane z = `z` with the given corners (x, y). */
function triangle(corners: [number, number][], z = 0): SurfaceSource {
  const geometry = new BufferGeometry();
  geometry.setAttribute(
    "position",
    new BufferAttribute(new Float32Array(corners.flatMap(([x, y]) => [x, y, z])), 3),
  );
  return { geometry, matrix: new Matrix4() };
}

/** Distance from p to the triangle (a, b, c): 0 for a point on it. */
function distanceToTriangle(p: number[], t: Float32Array, o: number): number {
  const a = [t[o]!, t[o + 1]!, t[o + 2]!];
  const u = [t[o + 3]! - a[0]!, t[o + 4]! - a[1]!, t[o + 5]! - a[2]!];
  const v = [t[o + 6]! - a[0]!, t[o + 7]! - a[1]!, t[o + 8]! - a[2]!];
  const w = [p[0]! - a[0]!, p[1]! - a[1]!, p[2]! - a[2]!];
  const dot = (x: number[], y: number[]) => x[0]! * y[0]! + x[1]! * y[1]! + x[2]! * y[2]!;
  const uu = dot(u, u);
  const uv = dot(u, v);
  const vv = dot(v, v);
  const wu = dot(w, u);
  const wv = dot(w, v);
  const den = uu * vv - uv * uv;
  const s = (vv * wu - uv * wv) / den;
  const r = (uu * wv - uv * wu) / den;
  if (s < -1e-4 || r < -1e-4 || s + r > 1 + 1e-4) return Infinity; // outside the triangle
  const q = [
    a[0]! + s * u[0]! + r * v[0]!,
    a[1]! + s * u[1]! + r * v[1]!,
    a[2]! + s * u[2]! + r * v[2]!,
  ];
  return Math.hypot(p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!);
}

describe("seeded random numbers", () => {
  it("gives the same sequence for the same key and a different one for another key", () => {
    const a = seededRandom("model-hash-1");
    const b = seededRandom("model-hash-1");
    const c = seededRandom("model-hash-2");
    const seqA = Array.from({ length: 5 }, a);
    expect(Array.from({ length: 5 }, b)).toEqual(seqA);
    expect(Array.from({ length: 5 }, c)).not.toEqual(seqA);
    expect(seqA.every((x) => x >= 0 && x < 1)).toBe(true);
  });

  it("hashes text to 32 bits and spreads values evenly", () => {
    expect(hashString("")).toBe(0x811c9dc5);
    expect(hashString("a")).not.toBe(hashString("b"));
    const random = mulberry32(42);
    let sum = 0;
    for (let i = 0; i < 20000; i++) sum += random();
    expect(sum / 20000).toBeCloseTo(0.5, 1);
  });
});

describe("surface sampling", () => {
  const big = triangle([
    [0, 0],
    [4, 0],
    [0, 4],
  ]); // area 8
  const small = triangle(
    [
      [10, 0],
      [11, 0],
      [10, 2],
    ],
    3,
  ); // area 1

  it("returns exactly the requested number of points, with four seeds each", () => {
    const sample = sampleSurfaces([big, small], 1234, "seed");
    expect(sample.positions).toHaveLength(1234 * 3);
    expect(sample.seeds).toHaveLength(1234 * 4);
    expect(sample.area).toBeCloseTo(9);
    expect([...sample.seeds].every((s) => s >= 0 && s < 1)).toBe(true);
  });

  it("is deterministic for a seed and changes with it", () => {
    const a = sampleSurfaces([big, small], 500, "model-hash");
    const b = sampleSurfaces([big, small], 500, "model-hash");
    const c = sampleSurfaces([big, small], 500, "another-hash");
    expect(b.positions).toEqual(a.positions);
    expect(b.seeds).toEqual(a.seeds);
    expect(c.positions).not.toEqual(a.positions);
  });

  it("puts every point on a triangle of the sources", () => {
    const sample = sampleSurfaces([big, small], 2000, "on-surface");
    const { corners } = collectTriangles([big, small]);
    for (let i = 0; i < 2000; i++) {
      const p = [...sample.positions.subarray(i * 3, i * 3 + 3)];
      const d = Math.min(distanceToTriangle(p, corners, 0), distanceToTriangle(p, corners, 9));
      expect(d).toBeLessThan(1e-4);
    }
    expect(sample.minZ).toBe(0);
    expect(sample.maxZ).toBe(3);
  });

  it("weights triangles by area", () => {
    const n = 18000;
    const sample = sampleSurfaces([big, small], n, "area");
    let onSmall = 0;
    for (let i = 0; i < n; i++) if (sample.positions[i * 3 + 2]! > 1) onSmall++;
    // The small triangle has 1/9 of the area.
    expect(onSmall / n).toBeGreaterThan(1 / 9 - 0.012);
    expect(onSmall / n).toBeLessThan(1 / 9 + 0.012);
  });

  it("applies the element matrix and reads indexed geometry", () => {
    const box: SurfaceSource = {
      geometry: new BoxGeometry(2, 2, 2), // indexed, centred on the origin
      matrix: new Matrix4().makeTranslation(10, 20, 30),
    };
    const sample = sampleSurfaces([box], 3000, "box");
    expect(sample.area).toBeCloseTo(24);
    for (let i = 0; i < 3000; i++) {
      const [x, y, z] = sample.positions.subarray(i * 3, i * 3 + 3);
      const d = [Math.abs(x! - 10), Math.abs(y! - 20), Math.abs(z! - 30)];
      expect(Math.max(...d)).toBeCloseTo(1, 4); // on the surface of the moved box
    }
  });

  it("returns nothing for no surfaces and skips degenerate triangles", () => {
    expect(sampleSurfaces([], 100, "x").positions).toHaveLength(0);
    const line = triangle([
      [0, 0],
      [1, 0],
      [2, 0],
    ]);
    expect(collectTriangles([line]).cumulative).toHaveLength(0);
    expect(sampleSurfaces([line], 100, "x").positions).toHaveLength(0);
  });

  it("samples the real scene deterministically, inside the building's bounds", () => {
    const scene = buildScene(demoIndex());
    const a = sampleSurfaces(scene.descriptors, 20_000, "demo-model-hash");
    const b = sampleSurfaces(scene.descriptors, 20_000, "demo-model-hash");
    expect(a.positions).toHaveLength(20_000 * 3);
    expect(b.positions).toEqual(a.positions);
    const { min, max } = scene.bounds;
    for (let i = 0; i < a.positions.length; i += 3) {
      expect(a.positions[i]!).toBeGreaterThanOrEqual(min.x - 1e-3);
      expect(a.positions[i]!).toBeLessThanOrEqual(max.x + 1e-3);
      expect(a.positions[i + 2]!).toBeGreaterThanOrEqual(min.z - 1e-3);
      expect(a.positions[i + 2]!).toBeLessThanOrEqual(max.z + 1e-3);
    }
    expect(a.maxZ - a.minZ).toBeGreaterThan(5); // two storeys and a roof
  });

  it("reports the triangle, source and material group of every point", () => {
    const box = new BoxGeometry(2, 2, 2); // six groups, material index 0..5
    const flat = triangle([
      [0, 0],
      [1, 0],
      [0, 1],
    ]);
    const s = sampleSurfaces([flat, { geometry: box, matrix: new Matrix4() }], 500, "groups");
    const { source, material } = s.triangles;
    const seen = new Set<number>();
    for (let i = 0; i < 500; i++) {
      const t = s.triangle[i]!;
      expect(
        distanceToTriangle([...s.positions.subarray(i * 3, i * 3 + 3)], s.triangles.corners, t * 9),
      ).toBeLessThan(1e-4);
      if (source[t] === 0) expect(material[t]).toBe(0);
      else seen.add(material[t]!);
    }
    expect([...seen].sort()).toEqual([0, 1, 2, 3, 4, 5]);
  });
});
