import { describe, expect, it } from "vitest";

import { parseBuildingModel } from "../model/parse";
import type { Room } from "../model/types";
import { bySemanticKey, demoIndex, generatedLModelJson } from "../test-fixtures";
import { newWall, roomAt, snapPoint, wallAcross, wallBody } from "./wall-add";

const index = demoIndex();
const entrance = bySemanticKey(index.model, "room:entrance") as Room; // 0..3.4 x 0..4.8

describe("adding a wall: the gesture", () => {
  it("finds the room under the pointer and snaps the point to 5 cm", () => {
    expect(snapPoint([1.024, 1.4449])).toEqual([1.0, 1.45]);
    expect(roomAt(index, index.levels[0].id, [1.02, 1.44])?.id).toBe(entrance.id);
    expect(roomAt(index, index.levels[0].id, [-5, -5])).toBeNull();
  });

  it("runs across the room from boundary to boundary in the chosen direction", () => {
    expect(wallAcross(entrance, [1.02, 1.44], "north_south")).toEqual([
      [1.02, 0],
      [1.02, 4.8],
    ]);
    expect(wallAcross(entrance, [1.02, 1.44], "east_west")).toEqual([
      [0, 1.44],
      [3.4, 1.44],
    ]);
  });

  it("stays in the arm of an L-shaped room that holds the point", () => {
    const l = parseBuildingModel(generatedLModelJson());
    for (const room of l.model.elements) {
      if (room.type !== "room") continue;
      const line = wallAcross(room, [room.position.x, room.position.y], "east_west");
      if (line) expect(line[0][0]).toBeLessThanOrEqual(line[1][0]);
    }
  });

  it("draws the wall body and defaults to a door sized like the model's doors", () => {
    expect(wallBody([[0, 0], [2, 0]], 0.2)).toEqual([[0, 0.1], [2, 0.1], [2, -0.1], [0, -0.1]]); // prettier-ignore
    const spec = newWall(index);
    expect(spec).toMatchObject({ direction: "north_south", door: true, newRoomType: null });
    expect(spec.doorWidth).toBeGreaterThan(0);
  });
});
