import { Vector3 } from "three";

import { ensureCCW, insetRectilinear, type P2, segmentOverlap } from "../math/polygon";
import { axisOf, elementMatrix } from "../math/transform";
import { EPS, type Room } from "../model/types";
import { contentKey, part } from "./common";
import { assertDimensions, type BuildContext, type RenderDescriptor } from "./types";

/** Floor finish sits just above the structural slab to avoid z-fighting. */
export const FLOOR_FINISH_OFFSET = 0.004;

/**
 * buildFloor: a room's floor finish — its boundary (wall centerlines) inset to the inner wall
 * faces, so the finish meets the walls exactly. Edges without a wall (open-plan boundaries)
 * are not inset. The finish is also the room's pick surface in the viewer.
 */
export function buildFloor(room: Room, ctx: BuildContext): RenderDescriptor[] {
  assertDimensions(room);
  const { x: px, y: py } = room.position;
  const a = room.rotation.z;
  const cos = Math.cos(a);
  const sin = Math.sin(a);
  const local = ensureCCW(room.properties.boundary.map((p) => [p.x, p.y] as P2));
  const absolute = local.map(([x, y]) => [px + x * cos - y * sin, py + x * sin + y * cos] as P2);

  const walls = ctx.index.wallsBounding.get(room.id) ?? [];
  const insets = absolute.map((p, i) => {
    const edge: [P2, P2] = [p, absolute[(i + 1) % absolute.length]];
    let inset = 0;
    for (const w of walls) {
      const { start, end } = axisOf(w);
      if (segmentOverlap(edge, [start, end]) > EPS)
        inset = Math.max(inset, w.dimensions.thickness / 2);
    }
    return inset;
  });
  const inner = insetRectilinear(absolute, insets).map(([x, y]) => {
    const dx = x - px;
    const dy = y - py;
    return new Vector3(dx * cos + dy * sin, -dx * sin + dy * cos, FLOOR_FINISH_OFFSET);
  });
  const material = room.properties.floor_material_id ?? room.material_id ?? "__missing__";
  const key = contentKey("floor", room.properties.boundary, insets, material);
  return part(ctx, room, "body", key, elementMatrix(room, ctx.index), (mb) => {
    mb.face(inner, material, new Vector3(0, 0, 1));
  });
}
