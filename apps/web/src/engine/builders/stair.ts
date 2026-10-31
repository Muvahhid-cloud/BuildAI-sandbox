import { elementMatrix } from "../math/transform";
import type { Stair } from "../model/types";
import { contentKey, part } from "./common";
import { assertDimensions, type BuildContext, type RenderDescriptor } from "./types";

/** Structural thickness under the nosing line, beyond one riser. */
const WAIST = 0.12;

/**
 * Stair side profile in the local (x = run, z = rise) plane: n risers and n-1 treads rising
 * along +x, with a sloped soffit parallel to the pitch line. The last riser lands on the upper
 * floor at (run, rise_total).
 */
export function stairProfile(risers: number, riserH: number, treadD: number): [number, number][] {
  const run = (risers - 1) * treadD;
  const rise = risers * riserH;
  const pts: [number, number][] = [[0, 0]];
  for (let i = 0; i < risers - 1; i++) {
    pts.push([i * treadD, (i + 1) * riserH]);
    pts.push([(i + 1) * treadD, (i + 1) * riserH]);
  }
  pts.push([run, rise]);
  const waist = riserH + WAIST;
  pts.push([run, rise - waist]);
  // Soffit line with the stair's pitch through (run, rise - waist) meets z = 0 here:
  const x0 = Math.max(0, Math.min(treadD, run - ((rise - waist) * treadD) / riserH));
  pts.push([x0, 0]);
  return pts.filter((p, i) => i === 0 || p[0] !== pts[i - 1][0] || p[1] !== pts[i - 1][1]);
}

/** Straight flight: the side profile extruded across the stair width (local +y). */
export function buildStair(stair: Stair, ctx: BuildContext): RenderDescriptor[] {
  assertDimensions(stair);
  const { risers, riser_height: r, tread_depth: t } = stair.properties;
  const material = stair.material_id ?? "__missing__";
  const key = contentKey("stair", stair.dimensions, stair.properties, material);
  return part(ctx, stair, "body", key, elementMatrix(stair, ctx.index), (mb) => {
    mb.extrudeXZ(stairProfile(risers, r, t), 0, stair.dimensions.width, material);
  });
}
