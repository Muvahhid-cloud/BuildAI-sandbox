import { describe, expect, it } from "vitest";

import type { Wall } from "@/engine/model/types";
import { bySemanticKey, demoIndex } from "@/engine/test-fixtures";

import {
  isOpening,
  newOpening,
  offsetFor,
  openingCenter,
  openingOutline,
  slideDirections,
  slideTowards,
  wallAt,
  wallMargins,
} from "./opening-edit";

const index = demoIndex();
const ground = index.levels[0].id;
const wall = (key: string) => bySemanticKey(index.model, key) as Wall;

describe("opening placement helpers", () => {
  it("recognises doors and windows", () => {
    expect(isOpening(bySemanticKey(index.model, "door:front"))).toBe(true);
    expect(isOpening(bySemanticKey(index.model, "window:ent"))).toBe(true);
    expect(isOpening(wall("wall:G-S"))).toBe(false);
  });

  it("finds the wall under a point and the position along it", () => {
    const south = wall("wall:G-S"); // runs east from (0, 0), 12 m
    expect(wallAt(index, ground, [3, 0.1])).toMatchObject({ wall: { id: south.id } });
    expect(wallAt(index, ground, [3, 0.1])?.u).toBeCloseTo(3, 6);
    expect(wallAt(index, ground, [3, 2.5])).toBeNull(); // in the middle of a room
    // Near a corner the preferred wall (the one being dragged along) wins.
    const west = wall("wall:G-W");
    expect(wallAt(index, ground, [0.1, 0.1], west)?.wall.id).toBe(west.id);
    expect(wallAt(index, ground, [0.1, 0.1], south)?.wall.id).toBe(south.id);
  });

  it("snaps the start edge to 5 cm and never below the wall start", () => {
    expect(offsetFor(2.03, 0.9)).toBe(1.6); // centre 2.03 -> start 1.58 -> 1.60
    expect(offsetFor(0.2, 0.9)).toBe(0);
    expect(offsetFor(1.0, 1.0, 0.1)).toBe(0.5);
  });

  it("draws the opening over the wall body and reports the wall left on each side", () => {
    const south = wall("wall:G-S"); // 0.3 m thick
    const pts = openingOutline(south, 1, 2);
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    expect(Math.min(...xs)).toBeCloseTo(1, 6);
    expect(Math.max(...xs)).toBeCloseTo(3, 6);
    expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(0.3, 6);
    expect(wallMargins(south, 1, 2)).toEqual([1, 9]);
  });

  it("slides along the wall in its compass directions only", () => {
    const south = wall("wall:G-S"); // runs east
    expect(slideDirections(south)).toEqual(["west", "east"]);
    expect(slideTowards(south, "east", 0.05)).toBe(0.05);
    expect(slideTowards(south, "west", 0.05)).toBe(-0.05);
    expect(slideTowards(south, "north", 0.05)).toBe(0);
  });

  it("finds an opening's centre on its wall", () => {
    const door = bySemanticKey(index.model, "door:front");
    expect(isOpening(door) && openingCenter(index, door)).toEqual([1.7, 0]);
  });

  it("sizes a new opening like the model's own of that kind", () => {
    expect(newOpening(index, "door")).toMatchObject({ width: 0.9, height: 2.1, sill: 0 });
    expect(newOpening(index, "door", "entrance")).toMatchObject({ width: 1, height: 2.2 });
    const win = newOpening(index, "window");
    expect(win.kind).toBe("window");
    expect(win.sill).toBeGreaterThan(0);
    // No garage door in the demo house: a preset size.
    expect(newOpening(index, "door", "garage")).toMatchObject({ width: 2.5, height: 2.2 });
  });
});
