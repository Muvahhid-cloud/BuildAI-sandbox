// Pure helpers for placing doors and windows on the plan (docs/3d-engine.md §20, D2.3). They
// only describe the gesture — which wall the pointer is over, the snapped offset along it, the
// outline shown while placing, the distances to the wall ends; moving, adding and removing are
// typed operations applied and validated by the server (wall fit, overlaps, junctions,
// clearances, reachability).
import type { P2 } from "../math/polygon";
import { wallThicknessRange } from "../math/transform";
import type { ModelIndex } from "../model/model-index";
import type { BuildingElement, Door, Opening, Wall, Window } from "../model/types";
import { mapPts, rect } from "./plan-math";
import { wallFrame } from "./symbols";
import type { Compass } from "./wall-edit";

/** Snap of an opening's position along its wall, and the keyboard nudge step (m). */
export const OPENING_SNAP_M = 0.05;
/** How far beside a wall's faces the pointer still counts as "on the wall" (m). */
export const WALL_PICK_M = 0.3;

export type DoorKind = Door["properties"]["door_kind"];
export type WindowKind = Window["properties"]["window_kind"];

/** What a new opening will be: the choices of the "add" controls. */
export interface NewOpening {
  kind: "door" | "window";
  doorKind: DoorKind;
  windowKind: WindowKind;
  width: number;
  height: number;
  /** Windows only; doors stand on the floor. */
  sill: number;
}

export function isOpening(el: BuildingElement | undefined): el is Opening {
  return el?.type === "door" || el?.type === "window";
}

/** Unit vector along the wall, start → end: the direction of a larger offset. */
export function wallDirection(wall: Wall): P2 {
  return [Math.cos(wall.rotation.z), Math.sin(wall.rotation.z)];
}

/** (u along the axis from its start, v across it, + = left face) of a plan point. */
export function wallLocal(wall: Wall, [x, y]: P2): P2 {
  const [ux, uy] = wallDirection(wall);
  const dx = x - wall.position.x;
  const dy = y - wall.position.y;
  return [dx * ux + dy * uy, -dx * uy + dy * ux];
}

export function wallPoint(wall: Wall, u: number): P2 {
  const [ux, uy] = wallDirection(wall);
  return [wall.position.x + u * ux, wall.position.y + u * uy];
}

/** The centre of an opening in plan coordinates. */
export function openingCenter(index: ModelIndex, opening: Opening): P2 | null {
  const host = index.hostOf.get(opening.id);
  return host ? wallPoint(host, opening.position.x + opening.dimensions.width / 2) : null;
}

/**
 * The wall of `levelId` the point lies on (within its body plus `WALL_PICK_M`), and the point's
 * position along it. `prefer` wins while the point is near it, so a drag does not jump to a
 * crossing wall at a corner.
 */
export function wallAt(
  index: ModelIndex,
  levelId: string,
  point: P2,
  prefer?: Wall,
): { wall: Wall; u: number } | null {
  let best: { wall: Wall; u: number; d: number } | null = null;
  for (const el of index.elementsByLevel.get(levelId) ?? []) {
    if (el.type !== "wall") continue;
    const [u, v] = wallLocal(el, point);
    const [v0, v1] = wallThicknessRange(el);
    const d = v < v0 ? v0 - v : v > v1 ? v - v1 : 0;
    if (d > WALL_PICK_M || u < -WALL_PICK_M || u > el.dimensions.length + WALL_PICK_M) continue;
    const score = el.id === prefer?.id ? d - WALL_PICK_M : d;
    if (!best || score < best.d || (score === best.d && el.id < best.wall.id)) {
      best = { wall: el, u, d: score };
    }
  }
  return best ? { wall: best.wall, u: best.u } : null;
}

/** Offset of the start edge for an opening of `width` centred at `u`, snapped, never < 0. */
export function offsetFor(u: number, width: number, step = OPENING_SNAP_M): number {
  const raw = u - width / 2;
  const snapped = Math.round(raw / step) * step;
  return Math.max(0, Math.round(snapped * 1000) / 1000) || 0;
}

/** Plan outline of an opening of `width` at `offset` in `wall` (the wall body over its span). */
export function openingOutline(wall: Wall, offset: number, width: number): P2[] {
  const [v0, v1] = wallThicknessRange(wall);
  return mapPts(wallFrame(wall), rect(offset, v0, offset + width, v1));
}

/**
 * Start offset and width of an opening resized to `width` (resize_opening, docs/building-model.md
 * §5.4): at `offset` if given, else keeping its centre, shifted only as far as needed to stay
 * inside its wall — the server's rule, used to draw a proposal it refused.
 */
export function resizedOpening(
  opening: Opening,
  wall: Wall,
  width: number,
  offset?: number,
): [number, number] {
  if (offset !== undefined) return [offset, width];
  const centred = opening.position.x + (opening.dimensions.width - width) / 2;
  const max = Math.max(wall.dimensions.length - width, 0);
  return [Math.round(Math.min(Math.max(centred, 0), max) * 1000) / 1000, width];
}

/** Solid wall left on each side: from the wall's start to the opening, and from it to the end. */
export function wallMargins(wall: Wall, offset: number, width: number): [number, number] {
  return [offset, wall.dimensions.length - offset - width];
}

/** The two compass directions an opening slides in along its wall: decreasing offset first. */
export function slideDirections(wall: Wall): [Compass, Compass] {
  const [ux, uy] = wallDirection(wall);
  if (Math.abs(ux) >= Math.abs(uy)) return ux > 0 ? ["west", "east"] : ["east", "west"];
  return uy > 0 ? ["south", "north"] : ["north", "south"];
}

/** The offset change for sliding `distance` towards `direction` (0 if across the wall). */
export function slideTowards(wall: Wall, direction: Compass, distance: number): number {
  const [less, more] = slideDirections(wall);
  return direction === more ? distance : direction === less ? -distance : 0;
}

/** Sizes offered for a new opening when the model has none of that kind to copy. */
const PRESETS: Record<string, Pick<NewOpening, "width" | "height" | "sill">> = {
  "door:interior": { width: 0.9, height: 2.1, sill: 0 },
  "door:entrance": { width: 1.0, height: 2.2, sill: 0 },
  "door:sliding": { width: 2.4, height: 2.4, sill: 0 },
  "door:garage": { width: 2.5, height: 2.2, sill: 0 },
  window: { width: 1.2, height: 1.4, sill: 0.9 },
};

/** A new opening of the chosen kind, sized like the model's first opening of that kind. */
export function newOpening(
  index: ModelIndex,
  kind: "door" | "window",
  doorKind: DoorKind = "interior",
  windowKind: WindowKind = "casement",
): NewOpening {
  const like = index.model.elements.find((e) =>
    kind === "door"
      ? e.type === "door" && e.properties.door_kind === doorKind
      : e.type === "window" && e.properties.window_kind === windowKind,
  );
  const preset = PRESETS[kind === "door" ? `door:${doorKind}` : "window"];
  const size =
    like?.type === "door" || like?.type === "window"
      ? {
          width: like.dimensions.width,
          height: like.dimensions.height,
          sill: like.position.z,
        }
      : preset;
  return { kind, doorKind, windowKind, ...size, sill: kind === "door" ? 0 : size.sill };
}
