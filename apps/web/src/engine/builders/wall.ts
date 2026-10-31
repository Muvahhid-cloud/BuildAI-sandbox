import { coloredMaterialKey } from "../materials/material-cache";
import { elementMatrix, wallThicknessRange } from "../math/transform";
import type { Wall } from "../model/types";
import { contentKey, part } from "./common";
import { assertDimensions, type BuildContext, type RenderDescriptor } from "./types";
import { wallPanels } from "./wall-layout";

const MISSING = "__missing__";

/**
 * Wall = panels around its hosted openings (no CSG). Local frame: u along the axis, v across
 * the thickness (+v = left face), z up. Box faces: ±u ends/reveals use the core material,
 * +v the left finish, -v the right finish.
 */
export function buildWall(wall: Wall, ctx: BuildContext): RenderDescriptor[] {
  assertDimensions(wall);
  const { length, height } = wall.dimensions;
  const join = ctx.joins.get(wall.id) ?? { start: 0, end: 0 };
  const openings = ctx.index.hostedOpenings.get(wall.id) ?? [];
  const spans = openings.map((o) => ({
    u0: o.position.x,
    u1: o.position.x + o.dimensions.width,
    z0: o.position.z,
    z1: o.position.z + o.dimensions.height,
  }));
  const [v0, v1] = wallThicknessRange(wall);
  const core = wall.material_id ?? MISSING;
  // Face finishes, drawn in their display color when the model sets one (K3 appearance).
  const faces = {
    px: core,
    nx: core,
    py: coloredMaterialKey(
      wall.properties.finish_left_id ?? core,
      wall.properties.finish_left_color,
    ),
    ny: coloredMaterialKey(
      wall.properties.finish_right_id ?? core,
      wall.properties.finish_right_color,
    ),
    pz: core,
    nz: core,
  };
  const key = contentKey("wall", wall.dimensions, wall.properties, core, join, spans);
  return part(ctx, wall, "body", key, elementMatrix(wall, ctx.index), (mb) => {
    for (const p of wallPanels(-join.start, length + join.end, height, spans)) {
      mb.box(
        [p.u1 - p.u0, v1 - v0, p.z1 - p.z0],
        [(p.u0 + p.u1) / 2, (v0 + v1) / 2, (p.z0 + p.z1) / 2],
        faces,
      );
    }
  });
}
