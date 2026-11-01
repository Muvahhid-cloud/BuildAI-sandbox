import { describe, expect, it } from "vitest";

import { parseBuildingModel } from "../model/parse";
import type { Room } from "../model/types";
import { demoIndex, demoModelJson } from "../test-fixtures";
import {
  compassOf,
  deltaFromDrag,
  movedSideOutline,
  relocateSide,
  roomExtent,
  roomSides,
  sideRefusal,
} from "./room-edit";

const index = demoIndex();
const room = (name: string) =>
  index.model.elements.find((e): e is Room => e.type === "room" && e.name === name)!;

describe("room sides", () => {
  it("describes every side: direction, walls and whether it can move", () => {
    const entrance = room("Entrance");
    const sides = roomSides(index, entrance);
    expect(sides).toHaveLength(entrance.properties.boundary.length);
    const kinds = new Set(sides.map((s) => s.kind));
    expect(kinds.has("exterior")).toBe(true); // the south side is the facade
    expect(kinds.has("movable")).toBe(true); // the north side is W-G05
    const north = sides.find((s) => s.compass === "north")!;
    expect(north.kind).toBe("movable");
    expect(north.walls.map((w) => w.name)).toEqual(["W-G05"]);
    expect(north.outward).toEqual([0, 1]);
    expect(north.length).toBeCloseTo(3.4);
  });

  it("explains sides that cannot move, like the server", () => {
    const entrance = room("Entrance");
    const sides = roomSides(index, entrance);
    const exterior = sides.find((s) => s.kind === "exterior")!;
    // D2.5: a facade side moves the facade (the server checks it as a whole).
    expect(sideRefusal(entrance, exterior)).toBeNull();
    expect(exterior.resizable).toBe(true);
    const balcony = room("Balcony");
    const facade = roomSides(index, balcony).find(
      (s) => s.kind === "exterior" && s.walls.some((w) => w.properties.wall_kind === "exterior"),
    );
    if (facade) {
      expect(facade.resizable).toBe(false);
      expect(sideRefusal(balcony, facade)).toMatch(/facade/);
    }
    expect(
      sideRefusal(
        entrance,
        sides.find((s) => s.kind === "movable")!,
      ),
    ).toBeNull();
    const open = roomSides(index, room("Entrance")).find((s) => s.kind === "open");
    if (open) expect(sideRefusal(entrance, open)).toMatch(/open boundary/);
  });

  it("projects drags on the outward normal and outlines the moved side", () => {
    const entrance = room("Entrance");
    const north = roomSides(index, entrance).find((s) => s.compass === "north")!;
    expect(deltaFromDrag(north, [3, 0.4])).toBeCloseTo(0.4); // dragging north grows it
    expect(deltaFromDrag(north, [0, -0.2])).toBeCloseTo(-0.2);
    const before = roomExtent(entrance);
    const ys = movedSideOutline(entrance, north, 0.5).map((p) => p[1]);
    expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(before.depth + 0.5);
    expect(compassOf([0.1, -0.9])).toBe("south");
  });

  it("finds the side again after the room changed", () => {
    const entrance = room("Entrance");
    const north = roomSides(index, entrance).find((s) => s.compass === "north")!;
    // Simulate the server's answer: the entrance boundary moved 0.2 m north.
    const model = demoModelJson();
    const target = model.elements.find((e) => e.id === entrance.id) as Room;
    const top = Math.max(...target.properties.boundary.map((p) => p.y));
    target.properties.boundary = target.properties.boundary.map((p) =>
      p.y === top ? { ...p, y: p.y + 0.2 } : p,
    );
    const after = parseBuildingModel(model);
    expect(relocateSide(after, entrance.id, north, 0.2)).toBe(north.index);
    expect(relocateSide(after, entrance.id, north, 0.9)).toBeNull();
  });
});
