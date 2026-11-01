import { Matrix4, Vector2, Vector3 } from "three";

import type { BoxFaces, MeshBuilder } from "../geometry/mesh-builder";
import { coloredMaterialKey } from "../materials/material-cache";
import { bbox, ensureCCW, type P2 } from "../math/polygon";
import { elementMatrix } from "../math/transform";
import type { ModelIndex } from "../model/model-index";
import type { Roof, Wall } from "../model/types";
import { contentKey, part } from "./common";
import {
  assertDimensions,
  type BuildContext,
  InvalidElementError,
  type RenderDescriptor,
} from "./types";

const PARAPET_T = 0.2;
const COPING_T = 0.04;
const COPING_OVERHANG = 0.03;
/** Library material of roof trim: fascia and verge bands, soffits, parapet coping (V3). */
export const ROOF_TRIM = "roof_trim";

/** Faces the roof derives from the walls that support it (V3): parapets and gable ends. */
interface Enclosure {
  /** Facade (right/exterior face) finish key of the supporting exterior walls. */
  outer: string;
  /** Interior (left face) finish key. */
  inner: string;
  thickness: number;
}

/**
 * The exterior walls a roof bears on (`supports` relationships), lowest id first. Parapets and
 * gable-end infill take their finishes, so they read as the wall continuing up to the roof.
 */
export function roofEnclosure(roof: Roof, index: ModelIndex): Enclosure | null {
  const walls: Wall[] = [];
  for (const el of index.elementsById.values()) {
    if (el.type !== "wall" || el.properties.wall_kind !== "exterior") continue;
    if (el.relationships.some((r) => r.kind === "supports" && r.target_id === roof.id))
      walls.push(el);
  }
  walls.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const w = walls[0];
  if (!w) return null;
  const core = w.material_id ?? "__missing__";
  return {
    outer: coloredMaterialKey(
      w.properties.finish_right_id ?? core,
      w.properties.finish_right_color,
    ),
    inner: coloredMaterialKey(w.properties.finish_left_id ?? core, w.properties.finish_left_color),
    thickness: w.dimensions.thickness,
  };
}

/**
 * Roofs (docs/3d-engine.md §8, §23). z = 0 is the top of the covering at the eaves; the
 * covering is `thickness` thick, measured vertically. Pitched roofs require a rectangular
 * outline (v1). Trim (fascia, verge, soffit, coping) uses the library's `roof_trim`; parapets
 * and gable-end infill take the finishes of the supporting walls.
 */
export function buildRoof(roof: Roof, ctx: BuildContext): RenderDescriptor[] {
  assertDimensions(roof);
  const material = roof.material_id ?? "__missing__";
  const enclosure = roofEnclosure(roof, ctx.index);
  const key = contentKey("roof", roof.dimensions, roof.properties, material, enclosure);
  const outline = ensureCCW(roof.properties.outline.map((p) => [p.x, p.y] as P2));
  return part(ctx, roof, "body", key, elementMatrix(roof, ctx.index), (mb) => {
    const t = roof.dimensions.thickness;
    if (roof.properties.roof_type === "flat") {
      flatRoof(mb, outline, t, roof.properties.parapet_height, material, enclosure);
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
    const pitch = (roof.properties.pitch_deg * Math.PI) / 180;
    const h = (D / 2) * Math.tan(pitch);
    const hip = roof.properties.roof_type === "hip";
    pitchedRoof(mb, L, D, h, t, hip, material, frame);
    if (!hip && enclosure) {
      gableEnds(mb, L, D, h, t, Math.tan(pitch), roof.dimensions.overhang, enclosure, frame);
    }
  });
}

function flatRoof(
  mb: MeshBuilder,
  outline: P2[],
  t: number,
  parapet: number,
  material: string,
  enclosure: Enclosure | null,
) {
  const pts = outline.map(([x, y]) => new Vector2(x, y));
  mb.prism(pts, [], -t, 0, { top: material, bottom: ROOF_TRIM, side: ROOF_TRIM });
  if (parapet <= 0) return;
  // The parapet is the facade carried up past the roof: facade finish outside and inside
  // (rendered upstand), capped by a trim coping that overhangs both faces a little.
  const outer = enclosure?.outer ?? material;
  const inner = enclosure?.outer ?? material;
  const faces: BoxFaces = { px: outer, nx: outer, py: inner, ny: outer, pz: ROOF_TRIM, nz: outer };
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
    mb.box([len, PARAPET_T, parapet - COPING_T], [0, 0, (parapet - COPING_T) / 2], faces, m);
    mb.box(
      [len + 2 * COPING_OVERHANG, PARAPET_T + 2 * COPING_OVERHANG, COPING_T],
      [0, 0, parapet - COPING_T / 2],
      ROOF_TRIM,
      m,
    );
  }
}

/**
 * Gable or hip roof over an L x D rectangle with the ridge along x at height h.
 * Top surface (covering) + an underside (soffit, trim) offset down by t + fascia/verge bands.
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
    mb.face(poly.map(down).map(at), ROOF_TRIM, dir(out.clone().negate()));
  }
  // Fascia (eaves) and verge bands along the free boundary of the top surface.
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
    mb.face([a, b, down(b), down(a)].map(at), ROOF_TRIM, dir(out));
  }
}

/**
 * Gable-end infill (V3): the triangle between the top of each gable wall and the roof
 * underside, at the wall's outer face (the verge overhangs it by `overhang`), as thick as the
 * wall, in the wall's finishes. The walls in the model stop at the eaves line; this is the
 * part of them the pitched roof implies.
 */
function gableEnds(
  mb: MeshBuilder,
  L: number,
  D: number,
  h: number,
  t: number,
  slope: number,
  overhang: number,
  enc: Enclosure,
  frame: Matrix4,
) {
  const o = Math.min(overhang, D / 2 - 0.01, L / 2 - 0.01);
  const zBase = o * slope - t; // roof underside above the wall's outer face = wall top
  const apex = h - t;
  if (apex - zBase < 0.05) return;
  const at = (x: number, y: number, z: number) => new Vector3(x, y, z).applyMatrix4(frame);
  const dir = (x: number) => new Vector3(x, 0, 0).transformDirection(frame);
  const T = Math.min(enc.thickness, L / 2 - o);
  for (const [xOut, xIn, sign] of [
    [o, o + T, -1],
    [L - o, L - o - T, 1],
  ] as const) {
    const tri = (x: number) => [at(x, o, zBase), at(x, D - o, zBase), at(x, D / 2, apex)];
    mb.face(tri(xOut), enc.outer, dir(sign)); // facade
    mb.face(tri(xIn), enc.inner, dir(-sign)); // attic side
  }
}
