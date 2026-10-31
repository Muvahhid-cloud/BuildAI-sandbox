import { describe, expect, it } from "vitest";

import { bySemanticKey, demoIndex } from "../test-fixtures";
import { buildScene } from "./build-scene";
import { type CameraPresetId, cameraPose, EYE_HEIGHT } from "./camera-presets";

const index = demoIndex();
const { bounds } = buildScene(index);
const [floor1, floor2] = index.levels;

describe("camera presets", () => {
  const presets: CameraPresetId[] = [
    "exterior",
    "front",
    "rear",
    "top",
    "interior",
    `level:${floor1.id}`,
    `level:${floor2.id}`,
  ];

  it.each(presets)("%s gives a finite pose that is not degenerate", (preset) => {
    const p = cameraPose(preset, bounds, index);
    const values = [p.position.x, p.position.y, p.position.z, p.target.x, p.target.y, p.target.z];
    expect(values.every(Number.isFinite)).toBe(true);
    const d = Math.hypot(
      p.position.x - p.target.x,
      p.position.y - p.target.y,
      p.position.z - p.target.z,
    );
    expect(d).toBeGreaterThan(1);
  });

  it("front looks from the street side (south), rear from the garden (north)", () => {
    expect(cameraPose("front", bounds, index).position.y).toBeLessThan(bounds.min.y);
    expect(cameraPose("rear", bounds, index).position.y).toBeGreaterThan(bounds.max.y);
    expect(cameraPose("top", bounds, index).position.z).toBeGreaterThan(bounds.max.z);
  });

  it("floor presets isolate their level and look at it", () => {
    const p = cameraPose(`level:${floor2.id}`, bounds, index);
    expect(p.levelFilter).toBe(floor2.id);
    expect(p.target.z).toBeCloseTo(floor2.elevation + 1);
  });

  it("interior stands inside the living room at eye height", () => {
    const p = cameraPose("interior", bounds, index);
    const living = bySemanticKey(index.model, "room:living");
    expect(p.levelFilter).toBe(living.level_id);
    expect(p.position.z).toBeCloseTo(EYE_HEIGHT);
    expect(p.position.x).toBeGreaterThan(0);
    expect(p.position.x).toBeLessThan(7.4);
    expect(p.position.y).toBeGreaterThan(6);
    expect(p.position.y).toBeLessThan(10);
  });
});
