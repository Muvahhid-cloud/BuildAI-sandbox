import { Matrix4, Vector2, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { type BuiltMesh, MeshBuilder } from "./mesh-builder";

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
