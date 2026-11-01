import { describe, expect, it } from "vitest";

import type { Wall } from "../model/types";
import { bySemanticKey, demoIndex } from "../test-fixtures";
import {
  isFacade,
  isMovableWall,
  moveDirections,
  movedWallOutline,
  offsetFromDrag,
  offsetTowards,
  positiveDirection,
  roofOutlines,
  snapOffset,
} from "./wall-edit";

const index = demoIndex();
// W-G05: runs east along y = 4.8 (rotation 0), so a positive offset moves it north.
const eastWall = bySemanticKey(index.model, "wall:G-I1") as Wall;

function turned(wall: Wall, angle: number): Wall {
  return { ...wall, rotation: { ...wall.rotation, z: angle } };
}

describe("wall editing helpers", () => {
  it("allows interior walls only", () => {
    expect(isMovableWall(eastWall)).toBe(true);
    expect(isMovableWall(bySemanticKey(index.model, "wall:G-S"))).toBe(true); // a facade (D2.5)
    expect(isFacade(bySemanticKey(index.model, "wall:G-S") as Wall)).toBe(true);
    expect(isFacade(eastWall)).toBe(false);
    expect(isMovableWall(bySemanticKey(index.model, "room:kitchen"))).toBe(false);
  });

  it("snaps drags to 5 cm and whole millimeters", () => {
    expect(snapOffset(0.123)).toBe(0.1);
    expect(snapOffset(0.126)).toBe(0.15);
    expect(snapOffset(-0.024)).toBe(0);
    expect(Object.is(snapOffset(-0.01), -0)).toBe(false);
  });

  it("maps compass directions to the signed offset of the operation", () => {
    expect(positiveDirection(eastWall)).toBe("north");
    expect(moveDirections(eastWall)).toEqual(["south", "north"]);
    expect(offsetTowards(eastWall, "north", 0.3)).toBe(0.3);
    expect(offsetTowards(eastWall, "south", 0.3)).toBe(-0.3);
    expect(offsetTowards(eastWall, "east", 0.3)).toBe(0); // along the wall: not a move
    const westWall = turned(eastWall, Math.PI);
    expect(positiveDirection(westWall)).toBe("south");
    expect(offsetTowards(westWall, "north", 0.3)).toBe(-0.3);
    const northWall = turned(eastWall, Math.PI / 2);
    expect(positiveDirection(northWall)).toBe("west");
    expect(moveDirections(northWall)).toEqual(["west", "east"]);
    expect(offsetTowards(northWall, "east", 0.2)).toBe(-0.2);
  });

  it("projects a drag onto the wall's normal", () => {
    expect(offsetFromDrag(eastWall, [5, 0.4])).toBeCloseTo(0.4);
    expect(offsetFromDrag(turned(eastWall, Math.PI / 2), [0.4, 5])).toBeCloseTo(-0.4);
  });

  it("outlines the wall body at its new position", () => {
    const pts = movedWallOutline(eastWall, 0.5);
    const ys = pts.map((p) => p[1]);
    const t = eastWall.dimensions.thickness;
    expect(Math.min(...ys)).toBeCloseTo(4.8 + 0.5 - t / 2);
    expect(Math.max(...ys)).toBeCloseTo(4.8 + 0.5 + t / 2);
    expect(Math.max(...pts.map((p) => p[0])) - Math.min(...pts.map((p) => p[0]))).toBeCloseTo(
      eastWall.dimensions.length,
    );
  });
});

describe("roof outlines", () => {
  it("places each roof's eaves outline in plan coordinates", () => {
    const [ring] = roofOutlines(demoIndex());
    expect(ring[0][0]).toBeCloseTo(-0.65);
    expect(ring[2][0]).toBeCloseTo(12.65);
    expect(ring[2][1]).toBeCloseTo(10.65);
  });
});
