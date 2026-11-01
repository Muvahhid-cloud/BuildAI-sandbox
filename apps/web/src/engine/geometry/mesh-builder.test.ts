import { Matrix4, Vector2, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { type BuiltMesh, MeshBuilder, planeAxes } from "./mesh-builder";

/** Every triangle's winding must agree with its stored (outward) normal. */
function expectConsistentWinding({ geometry }: BuiltMesh) {
  const pos = geometry.getAttribute("position");
  const nor = geometry.getAttribute("normal");
  for (let i = 0; i < pos.count; i += 3) {
    const a = new Vector3().fromBufferAttribute(pos, i);
    const b = new Vector3().fromBufferAttribute(pos, i + 1);
    const c = new Vector3().fromBufferAttribute(pos, i + 2);
    const n = new Vector3().fromBufferAttribute(nor, i);
    const geometric = b.sub(a).cross(c.sub(a));
    expect(geometric.dot(n)).toBeGreaterThan(0);
  }
}

describe("MeshBuilder", () => {
  it("builds a box with outward normals and one group per material", () => {
    const mb = new MeshBuilder();
    mb.box([2, 1, 3], [0, 0, 1.5], { px: "a", nx: "a", py: "b", ny: "c", pz: "a", nz: "a" });
    const mesh = mb.build();
    expect(mesh.materials).toEqual(["a", "b", "c"]);
    expect(mesh.geometry.groups.map((g) => g.count)).toEqual([24, 6, 6]);
    expect(mesh.geometry.boundingBox!.min.toArray()).toEqual([-1, -0.5, 0]);
    expect(mesh.geometry.boundingBox!.max.toArray()).toEqual([1, 0.5, 3]);
    expectConsistentWinding(mesh);
  });

  it("keeps winding consistent under rotation + mirroring-free transforms", () => {
    const mb = new MeshBuilder();
    mb.box([1, 1, 1], [0, 0, 0], "m", new Matrix4().makeRotationY(-0.6).setPosition(3, 1, 2));
    expectConsistentWinding(mb.build());
  });

  it("extrudes a slab with a hole", () => {
    const mb = new MeshBuilder();
    const outline = [new Vector2(0, 0), new Vector2(4, 0), new Vector2(4, 4), new Vector2(0, 4)];
    const hole = [new Vector2(1, 1), new Vector2(2, 1), new Vector2(2, 2), new Vector2(1, 2)];
    mb.prism(outline, [hole], -0.2, 0, { top: "t", bottom: "b", side: "s" });
    const mesh = mb.build();
    expectConsistentWinding(mesh);
    // Top area = 16 - 1: sum triangle areas of the "t" group.
    const group = mesh.geometry.groups[mesh.materials.indexOf("t")];
    const pos = mesh.geometry.getAttribute("position");
    let area = 0;
    for (let i = group.start; i < group.start + group.count; i += 3) {
      const a = new Vector3().fromBufferAttribute(pos, i);
      const b = new Vector3().fromBufferAttribute(pos, i + 1);
      const c = new Vector3().fromBufferAttribute(pos, i + 2);
      area += b.sub(a).cross(c.sub(a)).length() / 2;
    }
    expect(area).toBeCloseTo(15, 6);
  });

  it("skips degenerate boxes", () => {
    const mb = new MeshBuilder();
    mb.box([0, 1, 1], [0, 0, 0], "m");
    expect(mb.isEmpty).toBe(true);
  });
});

describe("MeshBuilder UVs (meters)", () => {
  function uvExtent(mesh: BuiltMesh, group: number): { du: number; dv: number } {
    const uv = mesh.geometry.getAttribute("uv");
    const g = mesh.geometry.groups[group];
    let [u0, u1, v0, v1] = [Infinity, -Infinity, Infinity, -Infinity];
    for (let i = g.start; i < g.start + g.count; i++) {
      u0 = Math.min(u0, uv.getX(i));
      u1 = Math.max(u1, uv.getX(i));
      v0 = Math.min(v0, uv.getY(i));
      v1 = Math.max(v1, uv.getY(i));
    }
    return { du: u1 - u0, dv: v1 - v0 };
  }

  it("maps 1 UV unit to 1 meter on every face of a box", () => {
    const mb = new MeshBuilder();
    // A wall-like box: 4.2 m long, 0.3 m thick, 2.8 m high.
    mb.box([4.2, 0.3, 2.8], [2.1, 0, 1.4], {
      px: "e",
      nx: "x",
      py: "f",
      ny: "g",
      pz: "t",
      nz: "u",
    });
    const mesh = mb.build(); // groups sorted: e, f, g, t, u, x
    for (const face of [1, 2]) {
      const { du, dv } = uvExtent(mesh, face);
      expect(du).toBeCloseTo(4.2, 5); // along the wall
      expect(dv).toBeCloseTo(2.8, 5); // up the wall
    }
    const ends = uvExtent(mesh, 0);
    expect(ends.du).toBeCloseTo(0.3);
    expect(ends.dv).toBeCloseTo(2.8);
    const top = uvExtent(mesh, 3);
    expect([top.du, top.dv].map((x) => +x.toFixed(4)).sort()).toEqual([0.3, 4.2]);
  });

  it("keeps UVs in meters under element rotation", () => {
    const mb = new MeshBuilder();
    mb.box([3, 0.2, 2], [0, 0, 0], "m", new Matrix4().makeRotationZ(0.7));
    const mesh = mb.build();
    const uv = mesh.geometry.getAttribute("uv");
    const pos = mesh.geometry.getAttribute("position");
    // Distances between vertices of one triangle equal their UV distances.
    for (let i = 0; i < pos.count; i += 3) {
      const a = new Vector3().fromBufferAttribute(pos, i);
      const b = new Vector3().fromBufferAttribute(pos, i + 1);
      const dUv = Math.hypot(uv.getX(i) - uv.getX(i + 1), uv.getY(i) - uv.getY(i + 1));
      expect(dUv).toBeCloseTo(a.distanceTo(b), 5);
    }
  });

  it("runs u level along a sloped roof face (texture rows parallel to the eave)", () => {
    for (const n of [new Vector3(0, -0.42, 0.906), new Vector3(0.42, 0, 0.906)]) {
      const { u, v } = planeAxes(n.normalize());
      expect(Math.abs(u.z)).toBeLessThan(1e-9); // horizontal
      expect(v.z).toBeGreaterThan(0); // up the slope
    }
    const flat = planeAxes(new Vector3(0, 0, 1));
    expect(Math.abs(flat.u.z) + Math.abs(flat.v.z)).toBeLessThan(1e-9);
  });
});
