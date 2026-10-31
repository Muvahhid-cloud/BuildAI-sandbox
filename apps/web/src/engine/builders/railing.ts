import { Matrix4 } from "three";

import { elementMatrix } from "../math/transform";
import type { Railing } from "../model/types";
import { contentKey, part } from "./common";
import { assertDimensions, type BuildContext, type RenderDescriptor } from "./types";

const POST = 0.04;
const RAIL = 0.045;
const BALUSTER = 0.018;
const BALUSTER_SPACING = 0.12;

/** Guard rail along local +x from (0,0,0) to (length, 0, rise), `height` above that line. */
export function buildRailing(railing: Railing, ctx: BuildContext): RenderDescriptor[] {
  assertDimensions(railing);
  const { length: L, height: H } = railing.dimensions;
  const { rise, post_spacing: spacing, railing_kind: kind } = railing.properties;
  const material = railing.material_id ?? "__missing__";
  const matrix = elementMatrix(railing, ctx.index);
  const key = contentKey("railing", railing.dimensions, railing.properties, material);
  const zAt = (u: number) => (rise * u) / L;
  const glassPanel = kind === "glass" && Math.abs(rise) < 1e-6;

  const body = part(ctx, railing, "body", key, matrix, (mb) => {
    const posts = Math.max(2, Math.ceil(L / spacing) + 1);
    for (let i = 0; i < posts; i++) {
      const u = Math.min(L - POST / 2, Math.max(POST / 2, (i * L) / (posts - 1)));
      mb.box([POST, POST, H], [u, 0, zAt(u) + H / 2], material);
    }
    const slope = Math.hypot(L, rise);
    const tilt = new Matrix4()
      .makeTranslation(L / 2, 0, rise / 2 + H)
      .multiply(new Matrix4().makeRotationY(-Math.atan2(rise, L)));
    mb.box([slope, RAIL, RAIL], [0, 0, 0], material, tilt);
    if (!glassPanel) {
      const n = Math.floor(L / BALUSTER_SPACING);
      for (let i = 1; i < n; i++) {
        const u = (i * L) / n;
        mb.box([BALUSTER, BALUSTER, H - RAIL], [u, 0, zAt(u) + (H - RAIL) / 2], material);
      }
    }
  });
  if (!glassPanel) return body;
  const glass = part(ctx, railing, "glass", `${key}:glass`, matrix, (mb) => {
    mb.box([L - POST, 0.012, H - 0.12], [L / 2, 0, 0.06 + (H - 0.12) / 2], "glass");
  });
  return [...body, ...glass];
}
