// Exterior dimension chains (docs/3d-engine.md §19.3), in millimeters as on architectural
// plans. Per side, from the building outwards: openings + corners of that facade, the
// footprint corners (only when the footprint steps), and the overall dimension.
import type { WallJoin } from "../builders/wall-layout";
import type { P2 } from "../math/polygon";
import { wallThicknessRange } from "../math/transform";
import type { ModelIndex } from "../model/model-index";
import { EPS, type Wall } from "../model/types";
import { textWidthMm, toModel } from "./plan-math";
import { type DrawGroup, type DrawItem, TEXT_MM } from "./primitives";
import { wallFrame } from "./symbols";

type Side = "S" | "E" | "N" | "W";
const SIDES: Side[] = ["S", "E", "N", "W"];

/** Paper offsets (mm): first chain from the building, then between chains. */
const FIRST_MM = 10;
const STEP_MM = 7;
const TICK_MM = 1.5;
const OVERSHOOT_MM = 1.5;

interface Face {
  side: Side;
  /** Coordinate across the side (y for S/N, x for E/W). */
  level: number;
  wall: Wall;
}

function outerFaces(walls: readonly Wall[], joins: ReadonlyMap<string, WallJoin>): Face[] {
  const faces: Face[] = [];
  for (const wall of walls) {
    if (wall.properties.wall_kind !== "exterior") continue;
    const join = joins.get(wall.id) ?? { start: 0, end: 0 };
    const [v0] = wallThicknessRange(wall);
    const f = wallFrame(wall);
    // Exterior walls run counter-clockwise: the outside is the right face (v0).
    const p = toModel(f, [-join.start, v0]);
    const nx = Math.sin(wall.rotation.z);
    const ny = -Math.cos(wall.rotation.z);
    const side: Side | null =
      ny < -0.5 ? "S" : ny > 0.5 ? "N" : nx > 0.5 ? "E" : nx < -0.5 ? "W" : null;
    if (!side) continue;
    const horizontal = side === "S" || side === "N";
    faces.push({
      side,
      level: horizontal ? p[1] : p[0],
      wall,
    });
  }
  return faces;
}

function unique(values: number[]): number[] {
  const sorted = [...values].sort((p, q) => p - q);
  const out: number[] = [];
  for (const v of sorted) {
    const r = Math.round(v * 1000) / 1000;
    if (out.length === 0 || r - out[out.length - 1] > 0.001 + EPS) out.push(r);
  }
  return out;
}

export function dimensionGroups(
  walls: readonly Wall[],
  joins: ReadonlyMap<string, WallJoin>,
  index: ModelIndex,
  scale: number,
): DrawGroup[] {
  const faces = outerFaces(walls, joins);
  if (faces.length === 0) return [];
  const k = scale / 1000; // paper mm -> meters
  const horizontalFaces = faces.filter((f) => f.side === "S" || f.side === "N");
  const verticalFaces = faces.filter((f) => f.side === "E" || f.side === "W");
  // Footprint corners along a side are where the perpendicular facades stand. (Face ends
  // are not used: the corner joins trim or extend them by the wall thickness.)
  const cornersX = unique(verticalFaces.map((f) => f.level));
  const cornersY = unique(horizontalFaces.map((f) => f.level));
  const minY = Math.min(...horizontalFaces.map((f) => f.level));
  const maxY = Math.max(...horizontalFaces.map((f) => f.level));
  const minX = Math.min(...verticalFaces.map((f) => f.level));
  const maxX = Math.max(...verticalFaces.map((f) => f.level));

  const groups: DrawGroup[] = [];
  for (const side of SIDES) {
    const horizontal = side === "S" || side === "N";
    const corners = horizontal ? cornersX : cornersY;
    if (corners.length < 2) continue;
    const openings: number[] = [];
    for (const face of faces) {
      if (face.side !== side) continue;
      const f = wallFrame(face.wall);
      for (const o of index.hostedOpenings.get(face.wall.id) ?? []) {
        for (const u of [o.position.x, o.position.x + o.dimensions.width]) {
          const p = toModel(f, [u, 0]);
          openings.push(horizontal ? p[0] : p[1]);
        }
      }
    }
    const span = [corners[0], corners[corners.length - 1]];
    const chains: number[][] = [];
    const first = unique([...corners, ...openings]);
    if (first.length > 2) chains.push(first);
    if (corners.length > 2 && corners.join() !== first.join()) chains.push(corners);
    chains.push(span);

    // Outward direction and the base coordinate (outer face of the building on this side).
    const out = side === "S" || side === "W" ? -1 : 1;
    const base = side === "S" ? minY : side === "N" ? maxY : side === "W" ? minX : maxX;
    const items: DrawItem[] = [];
    chains.forEach((chain, i) => {
      const at = base + out * (FIRST_MM + i * STEP_MM) * k;
      items.push(...chainItems(chain, at, base, out, horizontal, k));
    });
    groups.push({ elementId: null, role: "dimension", items });
  }
  return groups;
}

function chainItems(
  values: number[],
  at: number,
  base: number,
  out: number,
  horizontal: boolean,
  k: number,
): DrawItem[] {
  const pt = (along: number, across: number): P2 =>
    horizontal ? [along, across] : [across, along];
  const items: DrawItem[] = [];
  const first = values[0];
  const last = values[values.length - 1];
  items.push({
    kind: "poly",
    pts: [pt(first - OVERSHOOT_MM * k, at), pt(last + OVERSHOOT_MM * k, at)],
    closed: false,
    pen: "dim",
    fill: "none",
  });
  for (const v of values) {
    // Extension line from just outside the building to just past the chain.
    items.push({
      kind: "poly",
      pts: [pt(v, base + out * 2 * k), pt(v, at + out * OVERSHOOT_MM * k)],
      closed: false,
      pen: "dim",
      fill: "none",
    });
    // 45° tick (architectural dimension terminator).
    const t = (TICK_MM / 2) * k;
    items.push({
      kind: "poly",
      pts: horizontal
        ? [
            [v - t, at - t],
            [v + t, at + t],
          ]
        : [
            [at - t, v - t],
            [at + t, v + t],
          ],
      closed: false,
      pen: "outline",
      fill: "none",
    });
  }
  for (let i = 0; i + 1 < values.length; i++) {
    const length = values[i + 1] - values[i];
    const text = String(Math.round(length * 1000));
    const room = (length / k) * 0.9;
    const size = Math.max(
      TEXT_MM.dim * 0.7,
      Math.min(TEXT_MM.dim, room / textWidthMm(text, 1) || 0),
    );
    const mid = (values[i] + values[i + 1]) / 2;
    // Text sits on the reading side of the line: above horizontal chains, left of vertical.
    // When it does not fit between the ticks it moves to the other side of the line.
    const fits = textWidthMm(text, size) * k <= length;
    const side = horizontal ? 1 : -1;
    const offset = fits ? side * 0.8 * k : -side * (0.8 + size) * k;
    items.push({
      kind: "text",
      at: pt(mid, at + offset),
      text,
      role: "dim",
      size: Math.round(size * 100) / 100,
      anchor: "middle",
      angle: horizontal ? 0 : Math.PI / 2,
    });
  }
  return items;
}
