import { Vector2 } from "three";

import { elementMatrix } from "../math/transform";
import type { Slab } from "../model/types";
import { contentKey, part } from "./common";
import { assertDimensions, type BuildContext, type RenderDescriptor } from "./types";

/** Structural slab: outline (+ holes, e.g. the stair void) extruded DOWN from its top face. */
export function buildSlab(slab: Slab, ctx: BuildContext): RenderDescriptor[] {
  assertDimensions(slab);
  const t = slab.dimensions.thickness;
  const material = slab.material_id ?? "__missing__";
  const outline = slab.properties.outline.map((p) => new Vector2(p.x, p.y));
  const holes = slab.properties.holes.map((h) => h.map((p) => new Vector2(p.x, p.y)));
  const key = contentKey("slab", slab.dimensions, slab.properties, material);
  return part(ctx, slab, "body", key, elementMatrix(slab, ctx.index), (mb) => {
    mb.prism(outline, holes, -t, 0, { top: material, bottom: material, side: material });
  });
}
