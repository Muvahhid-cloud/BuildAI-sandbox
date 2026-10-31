import { Matrix4, Vector2, Vector3 } from "three";

import type { MeshBuilder } from "../geometry/mesh-builder";
import { bbox, ensureCCW, type P2 } from "../math/polygon";
import { elementMatrix } from "../math/transform";
import type { Roof } from "../model/types";
import { contentKey, part } from "./common";
import {
  assertDimensions,
  type BuildContext,
  InvalidElementError,
  type RenderDescriptor,
} from "./types";

const PARAPET_T = 0.2;

/**
 * Roofs (docs/3d-engine.md §8). z = 0 is the top of the covering at the eaves; the covering is
 * `thickness` thick, measured vertically. Pitched roofs require a rectangular outline (v1).
 */
export function buildRoof(roof: Roof, ctx: BuildContext): RenderDescriptor[] {
  assertDimensions(roof);
  const material = roof.material_id ?? "__missing__";
  const key = contentKey("roof", roof.dimensions, roof.properties, material);
  const outline = ensureCCW(roof.properties.outline.map((p) => [p.x, p.y] as P2));
  return part(ctx, roof, "body", key, elementMatrix(roof, ctx.index), (mb) => {
    const t = roof.dimensions.thickness;
    if (roof.properties.roof_type === "flat") {
      flatRoof(mb, outline, t, roof.properties.parapet_height, material);
      return;
    }
    if (outline.length !== 4)
      throw new InvalidElementError(roof, "pitched roofs need a rectangular outline");
    const b = bbox(outline);
    const alongX = roof.properties.ridge_axis === "x";
    // Build with the ridge along local x, then rotate into place for ridge_axis "y".
    const L = alongX ? b.maxX - b.minX : b.maxY - b.minY;
    const D = alongX ? b.maxY - b.minY : b.maxX - b.minX;
    const frame = alongX
      ? new Matrix4().makeTranslation(b.minX, b.minY, 0)
      : new Matrix4()
          .makeTranslation(b.maxX, b.minY, 0)
          .multiply(new Matrix4().makeRotationZ(Math.PI / 2));
    const h = (D / 2) * Math.tan((roof.properties.pitch_deg * Math.PI) / 180);
    const hip = roof.properties.roof_type === "hip";
    pitchedRoof(mb, L, D, h, t, hip, material, frame);
  });
}

function flatRoof(mb: MeshBuilder, outline: P2[], t: number, parapet: number, material: string) {
  const pts = outline.map(([x, y]) => new Vector2(x, y));
  mb.prism(pts, [], -t, 0, { top: material, bottom: material, side: material });
  if (parapet <= 0) return;
  for (let i = 0; i < outline.length; i++) {
    const [x0, y0] = outline[i];
    const [x1, y1] = outline[(i + 1) % outline.length];
    const len = Math.hypot(x1 - x0, y1 - y0);
    // Inward normal of a CCW edge is (-dy, dx): the parapet sits inside the outline.
    const nx = -(y1 - y0) / len;
    const ny = (x1 - x0) / len;
    const m = new Matrix4()
      .makeTranslation(
        (x0 + x1) / 2 + (nx * PARAPET_T) / 2,
        (y0 + y1) / 2 + (ny * PARAPET_T) / 2,
        0,
      )
      .multiply(new Matrix4().makeRotationZ(Math.atan2(y1 - y0, x1 - x0)));
    mb.box([len, PARAPET_T, parapet], [0, 0, parapet / 2], material, m);
  }
}

/**
 * Gable or hip roof over an L x D rectangle with the ridge along x at height h.
 * Top surface + an underside offset down by t + fascia/verge bands close the solid.
 */
function pitchedRoof(
  mb: MeshBuilder,
  L: number,
  D: number,
  h: number,
  t: number,
  hip: boolean,
  material: string,
  frame: Matrix4,
) {
  const inset = hip ? Math.min(D / 2, L / 2) : 0;
  const r0 = new Vector3(inset, D / 2, h);
  const r1 = new Vector3(L - inset, D / 2, h);
  const c = [
    new Vector3(0, 0, 0),
    new Vector3(L, 0, 0),
    new Vector3(L, D, 0),
    new Vector3(0, D, 0),
  ];
  // Top faces (outward = up-ish), as [polygon, outward hint].
  const faces: [Vector3[], Vector3][] = [
    [[c[0], c[1], r1, r0], new Vector3(0, -1, 1)],
    [[c[2], c[3], r0, r1], new Vector3(0, 1, 1)],
  ];
  if (hip) {
    faces.push([[c[1], c[2], r1], new Vector3(1, 0, 1)]);
    faces.push([[c[3], c[0], r0], new Vector3(-1, 0, 1)]);
  }
  const down = (v: Vector3) => new Vector3(v.x, v.y, v.z - t);
  const at = (v: Vector3) => v.clone().applyMatrix4(frame);
  const dir = (v: Vector3) => v.clone().transformDirection(frame);
  for (const [poly, out] of faces) {
    mb.face(poly.map(at), material, dir(out));
    mb.face(poly.map(down).map(at), material, dir(out.clone().negate()));
  }
  // Closing bands along the free boundary of the top surface.
  const bands: [Vector3, Vector3, Vector3][] = hip
    ? [
        [c[0], c[1], new Vector3(0, -1, 0)],
        [c[1], c[2], new Vector3(1, 0, 0)],
        [c[2], c[3], new Vector3(0, 1, 0)],
        [c[3], c[0], new Vector3(-1, 0, 0)],
      ]
    : [
        [c[0], c[1], new Vector3(0, -1, 0)],
        [c[2], c[3], new Vector3(0, 1, 0)],
        [c[1], r1, new Vector3(1, 0, 0)],
        [r1, c[2], new Vector3(1, 0, 0)],
        [c[3], r0, new Vector3(-1, 0, 0)],
        [r0, c[0], new Vector3(-1, 0, 0)],
      ];
  for (const [a, b, out] of bands) {
    mb.face([a, b, down(b), down(a)].map(at), material, dir(out));
  }
}
