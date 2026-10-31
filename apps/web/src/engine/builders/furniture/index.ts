import { elementMatrix } from "../../math/transform";
import type { Furniture } from "../../model/types";
import { contentKey, part } from "../common";
import { assertDimensions, type BuildContext, type RenderDescriptor } from "../types";
import { FURNITURE_GLASS, FURNITURE_PLACEHOLDERS } from "./placeholders";

/**
 * Furniture placeholders. Geometry depends only on (kind, dimensions, material), so identical
 * pieces (e.g. six dining chairs) share one cached BufferGeometry.
 */
export function buildFurniture(item: Furniture, ctx: BuildContext): RenderDescriptor[] {
  assertDimensions(item);
  const kind = item.properties.furniture_kind;
  const material = item.material_id ?? "__missing__";
  const { width: w, depth: d, height: h } = item.dimensions;
  const dims = { w, d, h };
  const key = contentKey("furniture", kind, item.dimensions, material);
  const matrix = elementMatrix(item, ctx.index);
  const body = part(ctx, item, "body", key, matrix, (mb) =>
    FURNITURE_PLACEHOLDERS[kind](mb, dims, material),
  );
  const drawGlass = FURNITURE_GLASS[kind];
  if (!drawGlass) return body;
  return [
    ...body,
    ...part(ctx, item, "glass", `${key}:glass`, matrix, (mb) => drawGlass(mb, dims, "glass")),
  ];
}
