import { describe, expect, it } from "vitest";

import { buildPlanDrawing } from "../drawing/plan";
import { parseBuildingModel } from "../model/parse";
import { generatedModelJson, generatedTModelJson } from "../test-fixtures";
import { buildScene, elementBounds } from "./build-scene";

// Entrance canopies (BuildingModel 1.3.0, slab_kind "canopy") as the layout engine writes them.
describe.each([
  ["generated house", generatedModelJson],
  ["generated T house", generatedTModelJson],
])("entrance canopy (%s)", (_, json) => {
  const index = parseBuildingModel(json());
  const scene = buildScene(index);
  const canopies = [...index.elementsById.values()].filter(
    (e) => e.type === "slab" && e.properties.slab_kind === "canopy",
  );
  const entrance = [...index.elementsById.values()].find(
    (e) => e.type === "door" && e.properties.door_kind === "entrance",
  )!;

  it("is rendered above the entrance door head, in front of its wall", () => {
    expect(canopies).toHaveLength(1);
    const canopy = canopies[0];
    const box = elementBounds(scene, canopy.id)!;
    const door = elementBounds(scene, entrance.id)!;
    if (entrance.type !== "door") throw new Error("fixture");
    const level = index.levelsById.get(canopy.level_id!)!;
    expect(box.min.z).toBeGreaterThan(level.elevation + entrance.dimensions.height);
    expect(box.max.z).toBeLessThanOrEqual(level.elevation + level.height + 1e-6);
    // It spans the door along the facade.
    const along = Math.abs(door.max.x - door.min.x) > Math.abs(door.max.y - door.min.y) ? "x" : "y";
    expect(box.min[along]).toBeLessThanOrEqual(door.min[along] + 1e-6);
    expect(box.max[along]).toBeGreaterThanOrEqual(door.max[along] - 1e-6);
  });

  it("is drawn dashed (overhead) on its level's plan", () => {
    const canopy = canopies[0];
    const drawing = buildPlanDrawing(index, canopy.level_id!);
    const group = drawing.groups.find((g) => g.elementId === canopy.id);
    expect(group).toBeDefined();
    expect(group!.items.every((i) => i.kind === "poly" && i.pen === "hidden")).toBe(true);
  });
});
