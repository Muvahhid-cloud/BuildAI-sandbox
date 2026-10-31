// Deterministic procedural mesh construction.
//
// Every face is given with an OUTWARD normal hint; the builder fixes the winding to match, so
// callers never reason about vertex order. Faces are grouped by material key, producing one
// BufferGeometry (with one group per material) per element part. Normals are flat, UVs are
// planar in meters (1 UV unit = 1 m) so textures tile consistently later.
import {
  BufferGeometry,
  Float32BufferAttribute,
  Matrix3,
  Matrix4,
  ShapeUtils,
  Vector2,
  Vector3,
} from "three";

import { EPS } from "../model/types";

export type V3 = [number, number, number];

/** Per-face materials of an axis-aligned box: +x, -x, +y, -y, +z, -z. */
export interface BoxFaces {
  px: string;
  nx: string;
  py: string;
  ny: string;
  pz: string;
  nz: string;
}

export interface BuiltMesh {
  geometry: BufferGeometry;
  /** Material key of each geometry group, in group order. */
  materials: string[];
}

interface GroupData {
  positions: number[];
  normals: number[];
  uvs: number[];
}

const IDENTITY = new Matrix4();

export class MeshBuilder {
  private readonly groups = new Map<string, GroupData>();

  get isEmpty(): boolean {
    return this.groups.size === 0;
  }

  /** Planar polygon face (convex or concave, no holes). */
  face(points: Vector3[], material: string, outward: Vector3): void {
    if (points.length < 3) return;
    const n = newellNormal(points);
    if (n.lengthSq() < EPS * EPS) return; // degenerate
    const pts = n.dot(outward) < 0 ? [...points].reverse() : points;
    const normal = n.dot(outward) < 0 ? n.negate() : n;
    if (pts.length === 3 || pts.length === 4) {
      this.tri(pts[0], pts[1], pts[2], normal, material);
      if (pts.length === 4) this.tri(pts[0], pts[2], pts[3], normal, material);
      return;
    }
    const { u, v } = planeAxes(normal);
    const flat = pts.map((p) => new Vector2(p.dot(u), p.dot(v)));
    const tris = ShapeUtils.triangulateShape(flat, []);
    for (const [a, b, c] of tris) this.triFixed(pts[a], pts[b], pts[c], normal, material);
  }

  /** Axis-aligned box of `size` centered at `center`, then transformed by `matrix`. */
  box(size: V3, center: V3, materials: string | BoxFaces, matrix: Matrix4 = IDENTITY): void {
    const [sx, sy, sz] = size;
    if (sx < EPS || sy < EPS || sz < EPS) return;
    const m: BoxFaces =
      typeof materials === "string"
        ? {
            px: materials,
            nx: materials,
            py: materials,
            ny: materials,
            pz: materials,
            nz: materials,
          }
        : materials;
    const [cx, cy, cz] = center;
    const hx = sx / 2;
    const hy = sy / 2;
    const hz = sz / 2;
    const c = (x: number, y: number, z: number) =>
      new Vector3(cx + x * hx, cy + y * hy, cz + z * hz).applyMatrix4(matrix);
    const nm = new Matrix3().getNormalMatrix(matrix);
    const dir = (x: number, y: number, z: number) =>
      new Vector3(x, y, z).applyMatrix3(nm).normalize();
    this.face([c(1, -1, -1), c(1, 1, -1), c(1, 1, 1), c(1, -1, 1)], m.px, dir(1, 0, 0));
    this.face([c(-1, -1, -1), c(-1, -1, 1), c(-1, 1, 1), c(-1, 1, -1)], m.nx, dir(-1, 0, 0));
    this.face([c(-1, 1, -1), c(-1, 1, 1), c(1, 1, 1), c(1, 1, -1)], m.py, dir(0, 1, 0));
    this.face([c(-1, -1, -1), c(1, -1, -1), c(1, -1, 1), c(-1, -1, 1)], m.ny, dir(0, -1, 0));
    this.face([c(-1, -1, 1), c(1, -1, 1), c(1, 1, 1), c(-1, 1, 1)], m.pz, dir(0, 0, 1));
    this.face([c(-1, -1, -1), c(-1, 1, -1), c(1, 1, -1), c(1, -1, -1)], m.nz, dir(0, 0, -1));
  }

  /**
   * Vertical prism: polygon (with holes) in the XY plane extruded from z0 to z1.
   * Outline and holes may have any orientation.
   */
  prism(
    outline: Vector2[],
    holes: Vector2[][],
    z0: number,
    z1: number,
    materials: { top: string; bottom: string; side: string },
    matrix: Matrix4 = IDENTITY,
  ): void {
    const contour = ShapeUtils.isClockWise(outline) ? [...outline].reverse() : outline;
    const holesCW = holes.map((h) => (ShapeUtils.isClockWise(h) ? h : [...h].reverse()));
    const all = [...contour, ...holesCW.flat()];
    const tris = ShapeUtils.triangulateShape(contour, holesCW);
    const nm = new Matrix3().getNormalMatrix(matrix);
    const at = (p: Vector2, z: number) => new Vector3(p.x, p.y, z).applyMatrix4(matrix);
    const up = new Vector3(0, 0, 1).applyMatrix3(nm).normalize();
    const down = up.clone().negate();
    for (const [a, b, c] of tris) {
      this.face([at(all[a], z1), at(all[b], z1), at(all[c], z1)], materials.top, up);
      this.face([at(all[a], z0), at(all[b], z0), at(all[c], z0)], materials.bottom, down);
    }
    // Side walls. CCW contour: outward normal of edge (dx, dy) is (dy, -dx). Holes are CW,
    // so the same formula points into the hole, i.e. out of the solid.
    for (const ring of [contour, ...holesCW]) {
      for (let i = 0; i < ring.length; i++) {
        const p = ring[i];
        const q = ring[(i + 1) % ring.length];
        const out = new Vector3(q.y - p.y, -(q.x - p.x), 0).applyMatrix3(nm).normalize();
        this.face([at(p, z0), at(q, z0), at(q, z1), at(p, z1)], materials.side, out);
      }
    }
  }

  /**
   * Profile in the local XZ plane (points as [x, z]) extruded along local Y from y0 to y1.
   * Used for stairs.
   */
  extrudeXZ(
    profile: [number, number][],
    y0: number,
    y1: number,
    material: string,
    matrix: Matrix4 = IDENTITY,
  ): void {
    const shape = profile.map(([x, z]) => new Vector2(x, z));
    const ccw = ShapeUtils.isClockWise(shape) ? [...shape].reverse() : shape;
    const nm = new Matrix3().getNormalMatrix(matrix);
    const at = (p: Vector2, y: number) => new Vector3(p.x, y, p.y).applyMatrix4(matrix);
    const capOut0 = new Vector3(0, -1, 0).applyMatrix3(nm).normalize();
    const capOut1 = capOut0.clone().negate();
    for (const [a, b, c] of ShapeUtils.triangulateShape(ccw, [])) {
      this.face([at(ccw[a], y0), at(ccw[b], y0), at(ccw[c], y0)], material, capOut0);
      this.face([at(ccw[a], y1), at(ccw[b], y1), at(ccw[c], y1)], material, capOut1);
    }
    for (let i = 0; i < ccw.length; i++) {
      const p = ccw[i];
      const q = ccw[(i + 1) % ccw.length];
      // 2D outward normal of a CCW (x, z) edge is (dz, -dx) -> 3D (dz, 0, -dx).
      const out = new Vector3(q.y - p.y, 0, -(q.x - p.x)).applyMatrix3(nm).normalize();
      this.face([at(p, y0), at(q, y0), at(q, y1), at(p, y1)], material, out);
    }
  }

  build(): BuiltMesh {
    const keys = [...this.groups.keys()].sort();
    const positions: number[] = [];
    const normals: number[] = [];
    const uvs: number[] = [];
    const geometry = new BufferGeometry();
    let start = 0;
    keys.forEach((key, i) => {
      const g = this.groups.get(key)!;
      positions.push(...g.positions);
      normals.push(...g.normals);
      uvs.push(...g.uvs);
      const count = g.positions.length / 3;
      geometry.addGroup(start, count, i);
      start += count;
    });
    geometry.setAttribute("position", new Float32BufferAttribute(positions, 3));
    geometry.setAttribute("normal", new Float32BufferAttribute(normals, 3));
    geometry.setAttribute("uv", new Float32BufferAttribute(uvs, 2));
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();
    return { geometry, materials: keys };
  }

  private group(material: string): GroupData {
    let g = this.groups.get(material);
    if (!g) {
      g = { positions: [], normals: [], uvs: [] };
      this.groups.set(material, g);
    }
    return g;
  }

  /** Triangle whose winding must be checked against `normal`. */
  private triFixed(a: Vector3, b: Vector3, c: Vector3, normal: Vector3, material: string) {
    const n = new Vector3().subVectors(b, a).cross(new Vector3().subVectors(c, a));
    if (n.dot(normal) < 0) this.tri(a, c, b, normal, material);
    else this.tri(a, b, c, normal, material);
  }

  private tri(a: Vector3, b: Vector3, c: Vector3, normal: Vector3, material: string) {
    const g = this.group(material);
    const { u, v } = planeAxes(normal);
    for (const p of [a, b, c]) {
      g.positions.push(p.x, p.y, p.z);
      g.normals.push(normal.x, normal.y, normal.z);
      g.uvs.push(p.dot(u), p.dot(v));
    }
  }
}

/** Newell's method: robust polygon normal (not normalized to zero if degenerate). */
function newellNormal(pts: Vector3[]): Vector3 {
  const n = new Vector3();
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    const q = pts[(i + 1) % pts.length];
    n.x += (p.y - q.y) * (p.z + q.z);
    n.y += (p.z - q.z) * (p.x + q.x);
    n.z += (p.x - q.x) * (p.y + q.y);
  }
  return n.lengthSq() > 0 ? n.normalize() : n;
}

/** Two orthonormal in-plane axes for planar UV projection. */
function planeAxes(normal: Vector3): { u: Vector3; v: Vector3 } {
  const ref = Math.abs(normal.z) > 0.9 ? new Vector3(1, 0, 0) : new Vector3(0, 0, 1);
  const u = new Vector3().crossVectors(ref, normal).normalize();
  const v = new Vector3().crossVectors(normal, u).normalize();
  return { u, v };
}
