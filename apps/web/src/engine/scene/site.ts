// Site context around the building (not part of the BuildingModel): the ground disc and the
// site plan (V2). Pure and
// deterministic. The disc lies in its local XY plane; the viewer lays it flat in world space.
import { type Box3, CircleGeometry, Vector2, Vector3 } from "three";

import { fnv1a } from "../builders/common";
import { type BuiltMesh, MeshBuilder } from "../geometry/mesh-builder";
import { openingMatrix } from "../math/transform";
import type { ModelIndex } from "../model/model-index";
import type { Door } from "../model/types";

/** Ground disc radius for a model's bounds (meters): generous, so the horizon stays distant. */
export function siteRadius(bounds: Box3): number {
  const r = Math.max(bounds.getSize(new Vector3()).length() / 2, 5);
  return Math.max(60, r * 6);
}

/**
 * Disc of `radius` meters whose UVs are the local position in meters (1 UV unit = 1 m), like
 * every building mesh, so the library's `tile_size_m` applies unchanged.
 */
export function groundDiscGeometry(radius: number, segments = 96): CircleGeometry {
  const g = new CircleGeometry(radius, segments);
  const pos = g.getAttribute("position");
  const uv = g.getAttribute("uv");
  for (let i = 0; i < pos.count; i++) uv.setXY(i, pos.getX(i), pos.getY(i));
  uv.needsUpdate = true;
  return g;
}

// ---------------------------------------------------------------------------------------------
// Site plan (V2): path, driveway, plants and a low street fence, in MODEL space (Z-up, meters).
// Environment only — never part of the BuildingModel. Derived deterministically from the model:
// the entrance and garage doors (door_kind), their host walls and the building's bounds. No
// randomness: variation (plant heights, rotations, species) comes from a stable hash of the slot.

/** Street edge distance south of the building (meters). */
export const STREET_SETBACK = 7;
const LANDING = 1.5;
const PATH_MIN_WIDTH = 1.2;
const DRIVEWAY_MARGIN = 0.8;
const TREE_CLEARANCE = 2.4;
const BUSH_CLEARANCE = 0.9;
const BUSH_SPACING = 2.4;

export type P2 = [number, number];

export interface SiteStrip {
  kind: "path" | "driveway";
  /** Centre line from the door's facade point to the street edge. */
  points: P2[];
  width: number;
  /** The door the strip serves. */
  doorId: string;
}

export interface SitePlant {
  kind: "tree" | "bush";
  /** Slot index: stable, so the same model yields the same plants. */
  slot: number;
  x: number;
  y: number;
  height: number;
  rotation: number;
}

export interface SitePlan {
  streetY: number;
  strips: SiteStrip[];
  plants: SitePlant[];
  /** Fence runs along the street edge, split where strips cross. */
  fence: [P2, P2][];
}

/** Stable pseudo-random fraction in [0, 1) for a key (FNV-1a; no global state, no clock). */
export function hashFraction(key: string): number {
  return parseInt(fnv1a(key), 16) / 0x100000000;
}

interface DoorOnFacade {
  id: string;
  width: number;
  point: P2; // centre of the opening on the facade (outer) face
  out: P2; // unit outward direction in plan
}

function doorsOfKind(index: ModelIndex, kind: string): DoorOnFacade[] {
  const out: DoorOnFacade[] = [];
  const doors = [...index.elementsById.values()]
    .filter((e): e is Door => e.type === "door" && e.properties.door_kind === kind)
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  for (const door of doors) {
    const host = index.hostOf.get(door.id);
    if (!host || host.type !== "wall") continue;
    const m = openingMatrix(door, host, index);
    const t = host.dimensions.thickness;
    // Exterior = right face (-v) for counter-clockwise exterior walls.
    const p = new Vector3(door.dimensions.width / 2, -t / 2, 0).applyMatrix4(m);
    const q = new Vector3(door.dimensions.width / 2, -t / 2 - 1, 0).applyMatrix4(m);
    const len = Math.hypot(q.x - p.x, q.y - p.y) || 1;
    out.push({
      id: door.id,
      width: door.dimensions.width,
      point: [round(p.x), round(p.y)],
      out: [round((q.x - p.x) / len), round((q.y - p.y) / len)],
    });
  }
  return out;
}

/** Centre line from a facade point to the street, going around the building when needed. */
function routeToStreet(d: DoorOnFacade, bounds: Box3, streetY: number): P2[] {
  const [px, py] = d.point;
  const [nx, ny] = d.out;
  const land: P2 = [round(px + nx * LANDING), round(py + ny * LANDING)];
  if (ny < -0.7) return [d.point, [px, streetY]]; // street-side door: straight
  if (Math.abs(nx) > 0.7) return [d.point, land, [land[0], streetY]]; // side door
  // Garden-side door: walk around the nearer end of the building.
  const left = bounds.min.x - LANDING;
  const right = bounds.max.x + LANDING;
  const sideX = Math.abs(px - left) <= Math.abs(right - px) ? left : right;
  return [d.point, land, [round(sideX), land[1]], [round(sideX), streetY]];
}

function distanceToStrip(x: number, y: number, s: SiteStrip): number {
  let best = Infinity;
  for (let i = 0; i + 1 < s.points.length; i++) {
    const [ax, ay] = s.points[i];
    const [bx, by] = s.points[i + 1];
    const dx = bx - ax;
    const dy = by - ay;
    const l2 = dx * dx + dy * dy || 1;
    const k = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2));
    best = Math.min(best, Math.hypot(x - (ax + k * dx), y - (ay + k * dy)));
  }
  return best - s.width / 2;
}

function round(v: number): number {
  return Math.round(v * 1000) / 1000;
}

/** The site around a building. Same model + bounds => identical plan. */
export function planSite(index: ModelIndex, bounds: Box3): SitePlan {
  const { min, max } = bounds;
  const streetY = round(min.y - STREET_SETBACK);
  const strips: SiteStrip[] = [];
  for (const d of doorsOfKind(index, "entrance")) {
    strips.push({
      kind: "path",
      points: routeToStreet(d, bounds, streetY),
      width: round(Math.max(PATH_MIN_WIDTH, d.width + 0.4)),
      doorId: d.id,
    });
  }
  for (const d of doorsOfKind(index, "garage")) {
    strips.push({
      kind: "driveway",
      points: routeToStreet(d, bounds, streetY),
      width: round(d.width + 2 * DRIVEWAY_MARGIN),
      doorId: d.id,
    });
  }

  const free = (x: number, y: number, clearance: number, margin: number) =>
    !(x > min.x - margin && x < max.x + margin && y > min.y - margin && y < max.y + margin) &&
    strips.every((s) => distanceToStrip(x, y, s) > clearance) &&
    y > streetY + 1;

  const plants: SitePlant[] = [];
  const treeSlots: P2[] = [
    [min.x - 3.2, min.y - 3.6],
    [max.x + 3.4, min.y - 3.0],
    [min.x - 3.0, max.y + 4.2],
    [max.x + 3.6, max.y + 3.4],
  ];
  treeSlots.forEach(([x, y], slot) => {
    if (!free(x, y, TREE_CLEARANCE, 2.0)) return;
    const f = hashFraction(`tree:${slot}`);
    plants.push({
      kind: "tree",
      slot,
      x: round(x),
      y: round(y),
      height: round(4.2 + 1.4 * f),
      rotation: round(hashFraction(`tree-rot:${slot}`) * Math.PI * 2),
    });
  });
  // A hedge-like row of shrubs along the street facade, clear of the path and the driveway.
  const by = min.y - 1.0;
  const count = Math.max(0, Math.floor((max.x - min.x - 1.2) / BUSH_SPACING) + 1);
  for (let i = 0; i < count; i++) {
    const x = min.x + 0.6 + i * BUSH_SPACING;
    if (!strips.every((s) => distanceToStrip(x, by, s) > BUSH_CLEARANCE)) continue;
    plants.push({
      kind: "bush",
      slot: 100 + i,
      x: round(x),
      y: round(by),
      height: round(0.8 + 0.5 * hashFraction(`bush:${i}`)),
      rotation: round(hashFraction(`bush-rot:${i}`) * Math.PI * 2),
    });
  }

  // Low fence on the street edge, open where a strip reaches the street.
  const fy = round(streetY + 0.4);
  const x0 = round(min.x - 8);
  const x1 = round(max.x + 8);
  const gaps = strips
    .map((s) => {
      const end = s.points[s.points.length - 1];
      return [round(end[0] - s.width / 2 - 0.3), round(end[0] + s.width / 2 + 0.3)] as P2;
    })
    .sort((a, b) => a[0] - b[0]);
  const fence: [P2, P2][] = [];
  let cursor = x0;
  for (const [g0, g1] of gaps) {
    if (g0 > cursor)
      fence.push([
        [cursor, fy],
        [g0, fy],
      ]);
    cursor = Math.max(cursor, g1);
  }
  if (x1 > cursor)
    fence.push([
      [cursor, fy],
      [x1, fy],
    ]);
  return { streetY, strips, plants, fence };
}

const STRIP_TOP = -0.015; // a little above the ground disc (GROUND_Y = -0.05), below the FFL
const FENCE_HEIGHT = 0.9;

/**
 * Site geometry (model space, Z-up) as one mesh with a group per library material: paving
 * strips (`site_paving`, UVs in meters) and the fence (`wood`). Plants are glTF models placed
 * by the viewer from `plan.plants`.
 */
export function buildSiteMesh(plan: SitePlan): BuiltMesh {
  const mb = new MeshBuilder();
  const paving = { top: "site_paving", bottom: "site_paving", side: "site_paving" };
  for (const s of plan.strips) {
    for (let i = 0; i + 1 < s.points.length; i++) {
      const [ax, ay] = s.points[i];
      const [bx, by] = s.points[i + 1];
      const len = Math.hypot(bx - ax, by - ay);
      if (len < 1e-6) continue;
      const ux = (bx - ax) / len;
      const uy = (by - ay) / len;
      // Extend joints by half the width so consecutive segments overlap at corners.
      const e0 = i > 0 ? s.width / 2 : 0;
      const e1 = i + 2 < s.points.length ? s.width / 2 : 0;
      const sx = ax - ux * e0;
      const sy = ay - uy * e0;
      const ex = bx + ux * e1;
      const ey = by + uy * e1;
      const nx = -uy * (s.width / 2);
      const ny = ux * (s.width / 2);
      const outline = [
        new Vector2(sx + nx, sy + ny),
        new Vector2(sx - nx, sy - ny),
        new Vector2(ex - nx, ey - ny),
        new Vector2(ex + nx, ey + ny),
      ];
      // Segments are offset by a hair in height so overlapping corners never z-fight.
      const top = STRIP_TOP - i * 0.001;
      mb.prism(outline, [], top - 0.04, top, paving);
    }
  }
  for (const [[ax, ay], [bx]] of plan.fence) {
    const len = bx - ax;
    if (len < 0.2) continue;
    const posts = Math.max(1, Math.round(len / 2));
    for (let i = 0; i <= posts; i++) {
      const x = ax + (len * i) / posts;
      mb.box([0.08, 0.08, FENCE_HEIGHT], [x, ay, FENCE_HEIGHT / 2 - 0.05], "wood");
    }
    for (const z of [0.35, 0.75]) mb.box([len, 0.04, 0.09], [ax + len / 2, ay, z], "wood");
  }
  return mb.build();
}
