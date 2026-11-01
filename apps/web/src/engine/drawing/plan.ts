// BuildingModel level -> PlanDrawing (docs/3d-engine.md §19). Pure and deterministic: the same
// model, level and scale always give the same groups in the same order. Wall joins and the
// opening gaps use the same rules as the 3D wall builder, so plan and 3D cannot disagree.
import type { P2 } from "../math/polygon";
import { segmentOverlap } from "../math/polygon";
import { wallThicknessRange } from "../math/transform";
import type { ModelIndex } from "../model/model-index";
import { computeWallJoins, wallPanels } from "../builders/wall-layout";
import { EPS, type BuildingElement, type Room, type Wall } from "../model/types";
import { dimensionGroups } from "./dimensions";
import { hatchLines, labelPoint, mapPts, placeLabel, rect, textWidthMm } from "./plan-math";
import {
  type Bounds,
  boundsOf,
  type DrawGroup,
  type DrawItem,
  emptyBounds,
  extendBounds,
  line,
  type PlanDrawing,
  poly,
  TEXT_MM,
} from "./primitives";
import {
  doorItems,
  furnitureItems,
  roomOutline,
  stairItems,
  wallAxis,
  wallFrame,
  windowItems,
} from "./symbols";

export interface PlanOptions {
  /** Scale denominator the labels are fitted for (default 1:100). */
  scale?: number;
  /** Draw furniture (default true). */
  furniture?: boolean;
  /** Draw dimension chains (default true). */
  dimensions?: boolean;
}

const OUTDOOR_ROOMS = new Set(["terrace", "balcony"]);
const HATCH_SPACING = 0.12;
/** How far beyond the wall faces a door or window can be picked in the interactive plan (m). */
const OPENING_PICK = 0.12;

function byId<T extends { id: string }>(a: T, b: T): number {
  return a.id.localeCompare(b.id);
}

export function buildPlanDrawing(
  index: ModelIndex,
  levelId: string,
  options: PlanOptions = {},
): PlanDrawing {
  const level = index.levelsById.get(levelId);
  if (!level) throw new Error(`Unknown level ${levelId}`);
  const scale = options.scale ?? 100;
  const elements = [...(index.elementsByLevel.get(levelId) ?? [])].sort(byId);
  const of = <T extends BuildingElement["type"]>(type: T) =>
    elements.filter((e): e is Extract<BuildingElement, { type: T }> => e.type === type);

  const walls = of("wall");
  const rooms = of("room");
  const joins = computeWallJoins(walls);
  const groups: DrawGroup[] = [];

  // 1. Slabs that are visible as their own outline: balconies (other slabs lie under walls),
  // and entrance canopies (1.3.0), which are above the cut plane: dashed, as overhead.
  for (const slab of of("slab")) {
    const kind = slab.properties.slab_kind;
    if (kind !== "balcony" && kind !== "canopy") continue;
    const f = { x: slab.position.x, y: slab.position.y, angle: slab.rotation.z };
    const outline = mapPts(
      f,
      slab.properties.outline.map((p) => [p.x, p.y] as P2),
    );
    const pen = kind === "canopy" ? "hidden" : "outline";
    groups.push({ elementId: slab.id, role: "slab", items: [poly(outline, pen, true)] });
  }
  // Voids in this level's floor (stair openings) are drawn dashed.
  for (const slab of of("slab")) {
    if (slab.properties.holes.length === 0) continue;
    const f = { x: slab.position.x, y: slab.position.y, angle: slab.rotation.z };
    const items = slab.properties.holes.map((h) =>
      poly(
        mapPts(
          f,
          h.map((p) => [p.x, p.y] as P2),
        ),
        "hidden",
        true,
      ),
    );
    groups.push({ elementId: slab.id, role: "slab", items });
  }

  // 2. Rooms: pointer target, decking hatch for outdoor rooms, open boundaries dashed.
  for (const room of rooms)
    groups.push({ elementId: room.id, role: "room", items: roomItems(room, walls) });

  // 3. Furniture and stairs below the cut plane. Stairs from lower levels show through voids.
  const furnitureIn = new Map<string, Bounds[]>();
  if (options.furniture ?? true) {
    for (const item of of("furniture")) {
      const group: DrawGroup = {
        elementId: item.id,
        role: "furniture",
        items: furnitureItems(item),
      };
      groups.push(group);
      const room = item.relationships.find((r) => r.kind === "located_in")?.target_id;
      if (room) furnitureIn.set(room, [...(furnitureIn.get(room) ?? []), boundsOf([group])]);
    }
  }
  for (const stair of of("stair"))
    groups.push({ elementId: stair.id, role: "stair", items: stairItems(stair, false) });
  for (const stair of index.model.elements
    .filter((e) => e.type === "stair" && e.properties.to_level_id === levelId)
    .sort(byId)) {
    if (stair.type === "stair")
      groups.push({ elementId: stair.id, role: "stair", items: stairItems(stair, true) });
  }
  for (const railing of of("railing")) {
    const f = { x: railing.position.x, y: railing.position.y, angle: railing.rotation.z };
    const L = railing.dimensions.length;
    groups.push({
      elementId: railing.id,
      role: "railing",
      items: [poly(mapPts(f, rect(0, -0.025, L, 0.025)), "thin", true, "paper")],
    });
  }

  // 4. Cut walls: poché panels between the openings (the 3D panel rule at plan level).
  for (const wall of walls) {
    const join = joins.get(wall.id) ?? { start: 0, end: 0 };
    const openings = index.hostedOpenings.get(wall.id) ?? [];
    const spans = openings.map((o) => ({
      u0: o.position.x,
      u1: o.position.x + o.dimensions.width,
      z0: 0,
      z1: 1,
    }));
    const [v0, v1] = wallThicknessRange(wall);
    const f = wallFrame(wall);
    const items = wallPanels(-join.start, wall.dimensions.length + join.end, 1, spans)
      .filter((p) => p.kind === "full")
      .map((p) => poly(mapPts(f, rect(p.u0, v0, p.u1, v1)), "cut", true, "solid"));
    groups.push({ elementId: wall.id, role: "wall", items });
  }

  // 5. Openings in the gaps.
  for (const el of elements) {
    if (el.type !== "door" && el.type !== "window") continue;
    const host = index.hostOf.get(el.id);
    if (!host) continue;
    const items = el.type === "window" ? windowItems(el, host) : doorItems(el, host, index);
    groups.push({ elementId: el.id, role: "opening", items });
  }

  // 6. Room labels: name and area from the model (never measured from the drawing).
  // Door swings and stairs are kept clear of labels in every room.
  const shared = groups
    .filter((g) => g.role === "opening" || g.role === "stair")
    .map((g) => boundsOf([g]));
  for (const room of rooms) {
    const items = labelItems(room, scale, [...(furnitureIn.get(room.id) ?? []), ...shared]);
    groups.push({ elementId: room.id, role: "label", items });
  }

  const extent = emptyBounds();
  for (const g of groups) {
    if (g.role === "label") continue;
    const b = boundsOf([g]);
    if (Number.isFinite(b.minX)) {
      extendBounds(extent, [b.minX, b.minY]);
      extendBounds(extent, [b.maxX, b.maxY]);
    }
  }
  if (options.dimensions ?? true) groups.push(...dimensionGroups(walls, joins, index, scale));
  const bounds = groups.length > 0 ? boundsOf(groups) : extent;

  // Pointer targets for doors and windows (drawn only in the interactive view): the wall body
  // over the opening's span, widened a little, so the thin symbol lines are easy to pick. Added
  // after the extents and label obstacles, so drawings and downloads do not change.
  for (const g of groups) {
    const el = g.role === "opening" && g.elementId ? index.elementsById.get(g.elementId) : null;
    const host = el ? index.hostOf.get(el.id) : undefined;
    if (!host || (el?.type !== "door" && el?.type !== "window")) continue;
    const [v0, v1] = wallThicknessRange(host);
    const u0 = el.position.x;
    const u1 = u0 + el.dimensions.width;
    g.items.push(
      poly(
        mapPts(wallFrame(host), rect(u0, v0 - OPENING_PICK, u1, v1 + OPENING_PICK)),
        "none",
        true,
        "hit",
      ),
    );
  }
  return { levelId, levelName: level.name, scale, groups, extent, bounds };
}

function roomItems(room: Room, walls: readonly Wall[]): DrawItem[] {
  const outline = roomOutline(room);
  const items: DrawItem[] = [poly(outline, "none", true, "hit")];
  const outdoor = OUTDOOR_ROOMS.has(room.properties.room_type);
  if (outdoor) {
    for (const [a, b] of hatchLines(outline, HATCH_SPACING)) items.push(line(a, b, "hatch"));
  }
  // Edges without a wall: an open-plan boundary (dashed) or the edge of a terrace (solid).
  const axes = walls.map(wallAxis);
  for (let i = 0; i < outline.length; i++) {
    const edge: [P2, P2] = [outline[i], outline[(i + 1) % outline.length]];
    const length = Math.hypot(edge[1][0] - edge[0][0], edge[1][1] - edge[0][1]);
    const covered = axes.reduce((sum, axis) => sum + segmentOverlap(edge, axis), 0);
    if (covered >= length - EPS) continue;
    items.push(line(edge[0], edge[1], outdoor ? "outline" : "hidden"));
  }
  return items;
}

/**
 * Name over area. The block goes where it fits inside the room and clear of furniture
 * (vertical in narrow rooms), shrinking to 60 % before it falls back to the room's
 * label point.
 */
function labelItems(room: Room, scale: number, obstacles: readonly Bounds[]): DrawItem[] {
  const outline = roomOutline(room);
  const name = room.name;
  const area = `${formatArea(room.dimensions.area)} m²`;
  const k = scale / 1000; // paper mm -> model meters
  for (const fit of LABEL_FITS) {
    const nameSize = round2(TEXT_MM.room * fit);
    const areaSize = round2(TEXT_MM.area * Math.max(fit, 0.8));
    const width = Math.max(textWidthMm(name, nameSize), textWidthMm(area, areaSize)) * k;
    const height = (nameSize + areaSize + 1) * k;
    const placed = placeLabel(outline, width, height, obstacles);
    if (placed || fit === LABEL_FITS[LABEL_FITS.length - 1]) {
      const { at, vertical } = placed ?? { at: labelPoint(outline), vertical: false };
      return labelBlock(at, vertical, name, nameSize, area, areaSize, k);
    }
  }
  return [];
}

const LABEL_FITS = [1, 0.85, 0.7, 0.6];

function labelBlock(
  [cx, cy]: P2,
  vertical: boolean,
  name: string,
  nameSize: number,
  area: string,
  areaSize: number,
  k: number,
): DrawItem[] {
  const h = (nameSize + areaSize + 1) * k;
  // Baselines: the name in the upper part of the block, the area in the lower part. Vertical
  // text reads bottom to top, so "up" is -x.
  const nameOff = h / 2 - nameSize * 0.8 * k;
  const areaOff = -h / 2 + areaSize * 0.2 * k;
  const at = (off: number): P2 => (vertical ? [cx - off, cy] : [cx, cy + off]);
  const angle = vertical ? Math.PI / 2 : 0;
  return [
    {
      kind: "text",
      at: at(nameOff),
      text: name,
      role: "room",
      size: nameSize,
      anchor: "middle",
      angle,
    },
    {
      kind: "text",
      at: at(areaOff),
      text: area,
      role: "area",
      size: areaSize,
      anchor: "middle",
      angle,
    },
  ];
}

/** Area as printed on drawings: one decimal, from the model's room area. */
export function formatArea(area: number): string {
  return area.toFixed(1);
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}
