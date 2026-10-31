import { describe, expect, it } from "vitest";

import { bySemanticKey, demoIndex } from "../test-fixtures";
import { ALL_LAYERS_VISIBLE } from "./layers";
import { elementVisibility, type VisibilityState, visibilityMap } from "./visibility";

const index = demoIndex();
const [floor1, floor2] = index.levels;
const base: VisibilityState = {
  levelFilter: "all",
  layers: ALL_LAYERS_VISIBLE,
  showRoof: true,
  showExteriorWalls: true,
};
const vis = (key: string, state: Partial<VisibilityState> = {}) =>
  elementVisibility(bySemanticKey(index.model, key), index, { ...base, ...state });

describe("floor isolation", () => {
  it("shows everything for 'all'", () => {
    const modes = new Set(visibilityMap(index, base).values());
    expect(modes).toEqual(new Set(["visible"]));
  });

  it("floor 1: floor 2 and the roof are hidden", () => {
    expect(vis("room:living", { levelFilter: floor1.id })).toBe("visible");
    expect(vis("room:master", { levelFilter: floor1.id })).toBe("hidden");
    expect(vis("slab:floor_f", { levelFilter: floor1.id })).toBe("hidden");
    expect(vis("roof:main", { levelFilter: floor1.id })).toBe("hidden");
  });

  it("floor 2: floor 1 is ghosted for context, the roof is hidden", () => {
    expect(vis("room:master", { levelFilter: floor2.id })).toBe("visible");
    expect(vis("room:living", { levelFilter: floor2.id })).toBe("ghost");
    expect(vis("roof:main", { levelFilter: floor2.id })).toBe("hidden");
  });
});

describe("layers and inspection toggles", () => {
  it("hides a layer independently", () => {
    const layers = { ...ALL_LAYERS_VISIBLE, furniture: false };
    expect(vis("furniture:sofa", { layers })).toBe("hidden");
    expect(vis("wall:G-I1", { layers })).toBe("visible");
    const noStructure = { ...ALL_LAYERS_VISIBLE, structure: false };
    expect(vis("slab:ground", { layers: noStructure })).toBe("hidden");
    expect(vis("wall:G-S", { layers: noStructure })).toBe("hidden"); // load-bearing facade
  });

  it("hides doors and windows whose host wall's layer is off", () => {
    const layers = { ...ALL_LAYERS_VISIBLE, structure: false }; // exterior walls are structural
    expect(vis("window:kitchen_s", { layers })).toBe("hidden");
    expect(vis("door:front", { layers })).toBe("hidden");
    expect(vis("door:ent_corr", { layers })).toBe("visible"); // interior wall stays
  });

  it("hides the roof", () => {
    expect(vis("roof:main", { showRoof: false })).toBe("hidden");
  });

  it("hides exterior walls together with their doors and windows, keeping interiors", () => {
    const state = { showExteriorWalls: false };
    expect(vis("wall:G-S", state)).toBe("hidden");
    expect(vis("window:kitchen_s", state)).toBe("hidden");
    expect(vis("door:front", state)).toBe("hidden");
    expect(vis("wall:G-I1", state)).toBe("visible");
    expect(vis("door:ent_corr", state)).toBe("visible");
  });
});
