import { Euler, Object3D, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { MODEL_ROOT_ROTATION, modelToWorld, worldToModel } from "./coords";

describe("model <-> world coordinate boundary", () => {
  it("modelToWorld matches the transform of the rotated model root group", () => {
    const root = new Object3D();
    root.rotation.copy(new Euler(...MODEL_ROOT_ROTATION));
    root.updateMatrixWorld();
    for (const p of [new Vector3(1, 2, 3), new Vector3(-4, 0.5, 0), new Vector3(0, 0, 7)]) {
      const viaGroup = p.clone().applyMatrix4(root.matrixWorld);
      const viaFn = modelToWorld(p);
      expect(viaFn.distanceTo(viaGroup)).toBeLessThan(1e-9);
    }
  });

  it("maps model up (+Z) to world up (+Y) and north (+Y) to world -Z", () => {
    expect(modelToWorld({ x: 0, y: 0, z: 1 }).toArray()).toEqual([0, 1, -0]);
    expect(modelToWorld({ x: 0, y: 1, z: 0 }).toArray()).toEqual([0, 0, -1]);
  });

  it("round-trips", () => {
    const p = { x: 1.25, y: -3.5, z: 2 };
    expect(worldToModel(modelToWorld(p))).toEqual({ x: 1.25, y: -3.5, z: 2 });
  });
});
