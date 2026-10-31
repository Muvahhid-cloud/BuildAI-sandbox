import { Group, Mesh } from "three";
import { describe, expect, it } from "vitest";

import { elementUserData, resolveElementId } from "./selection";

describe("resolveElementId", () => {
  it("returns the element id stored on the hit mesh", () => {
    const mesh = new Mesh();
    mesh.userData = elementUserData("abc", "body");
    expect(resolveElementId(mesh)).toBe("abc");
  });

  it("walks up to the nearest tagged ancestor", () => {
    const group = new Group();
    group.userData = elementUserData("parent-id", "body");
    const child = new Mesh();
    group.add(child);
    expect(resolveElementId(child)).toBe("parent-id");
  });

  it("returns null for untagged objects (ground, grid)", () => {
    expect(resolveElementId(new Mesh())).toBeNull();
    expect(resolveElementId(null)).toBeNull();
  });
});
