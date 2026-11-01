// Doors and windows. Local frame (openingMatrix): u from the opening's start edge along the
// wall, v across the wall (0 = wall center, +v = left face = interior of exterior walls),
// z from the sill. The wall builder already left the void; these fill it.
import type { MeshBuilder } from "../geometry/mesh-builder";
import { openingMatrix } from "../math/transform";
import type { Door, Wall, Window } from "../model/types";
import { coloredMaterialKey } from "../materials/material-cache";
import { contentKey, part } from "./common";
import {
  assertDimensions,
  type BuildContext,
  InvalidElementError,
  type RenderDescriptor,
} from "./types";

const FRAME = 0.06; // window frame profile width
const FRAME_DEPTH = 0.08;
const MULLION = 0.05;
const GLASS_T = 0.012;
const SASH = 0.025; // glazing bead around each pane (visible profile step)
const SASH_DEPTH = FRAME_DEPTH - 0.02;
const LINING = 0.012; // reveal lining between the frame and each wall face
const DOOR_FRAME = 0.05;
const HANDLE_Z = 1.0;

function hostOf(el: Door | Window, ctx: BuildContext): Wall {
  const host = ctx.index.hostOf.get(el.id);
  if (!host) throw new InvalidElementError(el, "no host wall");
  return host;
}

export function buildWindow(win: Window, ctx: BuildContext): RenderDescriptor[] {
  assertDimensions(win);
  const host = hostOf(win, ctx);
  const { width: w, height: h } = win.dimensions;
  const t = host.dimensions.thickness;
  const frame = win.properties.frame_material_id ?? win.material_id ?? "__missing__";
  const glass = win.material_id ?? "__missing__";
  const exterior = host.properties.wall_kind === "exterior";
  const matrix = openingMatrix(win, host, ctx.index);
  // Reveal linings take the host's face finishes (+v = left face, -v = right face), so window
  // reveals read as plaster/render instead of the raw wall core.
  const core = host.material_id ?? "__missing__";
  const liningIn = coloredMaterialKey(
    host.properties.finish_left_id ?? core,
    host.properties.finish_left_color,
  );
  const liningOut = coloredMaterialKey(
    host.properties.finish_right_id ?? core,
    host.properties.finish_right_color,
  );
  const key = contentKey(
    "window",
    win.dimensions,
    win.properties,
    glass,
    t,
    exterior,
    liningIn,
    liningOut,
  );

  const body = part(ctx, win, "body", key, matrix, (mb) => {
    mb.box([w, FRAME_DEPTH, FRAME], [w / 2, 0, FRAME / 2], frame);
    mb.box([w, FRAME_DEPTH, FRAME], [w / 2, 0, h - FRAME / 2], frame);
    mb.box([FRAME, FRAME_DEPTH, h - 2 * FRAME], [FRAME / 2, 0, h / 2], frame);
    mb.box([FRAME, FRAME_DEPTH, h - 2 * FRAME], [w - FRAME / 2, 0, h / 2], frame);
    const n = win.properties.mullions;
    const pane = (w - 2 * FRAME - n * MULLION) / (n + 1);
    for (let i = 0; i < n; i++) {
      const u = FRAME + (i + 1) * pane + i * MULLION + MULLION / 2;
      mb.box([MULLION, FRAME_DEPTH * 0.8, h - 2 * FRAME], [u, 0, h / 2], frame);
    }
    const paneH = h - 2 * FRAME;
    if (pane > 3 * SASH && paneH > 3 * SASH) {
      for (let i = 0; i <= n; i++) {
        const u0 = FRAME + i * (pane + MULLION);
        sashRing(mb, u0, FRAME, pane, paneH, frame);
      }
    }
    const half = t / 2;
    if (half - FRAME_DEPTH / 2 > LINING) {
      revealLining(mb, w, h, FRAME_DEPTH / 2, half, liningIn);
      revealLining(mb, w, h, -half, -FRAME_DEPTH / 2, liningOut);
    }
    if (exterior) {
      // Outside = right face (-v) for counter-clockwise exterior walls.
      const vOuter = -t / 2 - 0.05;
      const vInner = -FRAME_DEPTH / 2;
      mb.box([w + 0.1, vInner - vOuter, 0.03], [w / 2, (vInner + vOuter) / 2, -0.015], frame);
    }
  });
  const pane = part(ctx, win, "glass", `${key}:glass`, matrix, (mb) => {
    mb.box([w - 2 * FRAME, GLASS_T, h - 2 * FRAME], [w / 2, 0, h / 2], glass);
  });
  return [...body, ...pane];
}

export function buildDoor(door: Door, ctx: BuildContext): RenderDescriptor[] {
  assertDimensions(door);
  const host = hostOf(door, ctx);
  const { width: w, height: h, thickness: leafT } = door.dimensions;
  const t = host.dimensions.thickness;
  const leaf = door.material_id ?? "__missing__";
  const frame = door.properties.frame_material_id ?? leaf;
  const matrix = openingMatrix(door, host, ctx.index);
  const key = contentKey("door", door.dimensions, door.properties, leaf, t);
  const sliding = door.properties.door_kind === "sliding" || door.properties.swing === "sliding";

  const body = part(ctx, door, "body", key, matrix, (mb) => {
    const fd = t + 0.01; // lining covers the reveal
    mb.box([DOOR_FRAME, fd, h], [DOOR_FRAME / 2, 0, h / 2], frame);
    mb.box([DOOR_FRAME, fd, h], [w - DOOR_FRAME / 2, 0, h / 2], frame);
    mb.box([w, fd, DOOR_FRAME], [w / 2, 0, h - DOOR_FRAME / 2], frame);
    const clearW = w - 2 * DOOR_FRAME;
    const clearH = h - DOOR_FRAME;
    if (sliding) {
      slidingPanelFrames(mb, clearW, clearH, frame);
    } else if (door.properties.swing === "double") {
      const lw = clearW / 2 - 0.005;
      mb.box([lw, leafT, clearH - 0.01], [DOOR_FRAME + lw / 2, 0, clearH / 2], leaf);
      mb.box([lw, leafT, clearH - 0.01], [w - DOOR_FRAME - lw / 2, 0, clearH / 2], leaf);
      handle(mb, w / 2 - 0.06, leafT);
      handle(mb, w / 2 + 0.06, leafT);
    } else {
      mb.box([clearW - 0.01, leafT, clearH - 0.01], [w / 2, 0, clearH / 2], leaf);
      // Hinges on the swing side; the handle goes on the latch side.
      handle(mb, door.properties.swing === "left" ? w - DOOR_FRAME - 0.1 : DOOR_FRAME + 0.1, leafT);
    }
  });
  if (!sliding) return body;
  const glass = part(ctx, door, "glass", `${key}:glass`, matrix, (mb) => {
    const clearW = w - 2 * DOOR_FRAME;
    const clearH = h - DOOR_FRAME;
    for (const [u0, v] of slidingPanels(clearW)) {
      const pw = clearW / 2 + 0.04;
      mb.box(
        [pw - 2 * 0.05, GLASS_T, clearH - 2 * 0.05],
        [DOOR_FRAME + u0 + pw / 2, v, clearH / 2],
        leaf,
      );
    }
  });
  return [...body, ...glass];
}

/** Glazing bead around one pane (lower-left corner u0, z0), thinner than the frame. */
function sashRing(mb: MeshBuilder, u0: number, z0: number, pw: number, ph: number, m: string) {
  mb.box([pw, SASH_DEPTH, SASH], [u0 + pw / 2, 0, z0 + SASH / 2], m);
  mb.box([pw, SASH_DEPTH, SASH], [u0 + pw / 2, 0, z0 + ph - SASH / 2], m);
  mb.box([SASH, SASH_DEPTH, ph - 2 * SASH], [u0 + SASH / 2, 0, z0 + ph / 2], m);
  mb.box([SASH, SASH_DEPTH, ph - 2 * SASH], [u0 + pw - SASH / 2, 0, z0 + ph / 2], m);
}

/** Thin lining on the jambs, head and sill of the reveal between v0 and v1. */
function revealLining(mb: MeshBuilder, w: number, h: number, v0: number, v1: number, m: string) {
  const d = v1 - v0;
  const vc = (v0 + v1) / 2;
  mb.box([LINING, d, h], [LINING / 2, vc, h / 2], m);
  mb.box([LINING, d, h], [w - LINING / 2, vc, h / 2], m);
  mb.box([w - 2 * LINING, d, LINING], [w / 2, vc, h - LINING / 2], m);
  mb.box([w - 2 * LINING, d, LINING], [w / 2, vc, LINING / 2], m);
}

function handle(mb: MeshBuilder, u: number, leafT: number) {
  mb.box([0.12, leafT + 0.08, 0.025], [u, 0, HANDLE_Z], "metal");
}

/** Two overlapping sliding panels on separate tracks: [start offset, v]. */
function slidingPanels(clearW: number): [number, number][] {
  const pw = clearW / 2 + 0.04;
  return [
    [0, -0.025],
    [clearW - pw, 0.025],
  ];
}

function slidingPanelFrames(mb: MeshBuilder, clearW: number, clearH: number, frame: string) {
  const pw = clearW / 2 + 0.04;
  const bar = 0.05;
  for (const [u0, v] of slidingPanels(clearW)) {
    const cu = DOOR_FRAME + u0;
    mb.box([pw, 0.04, bar], [cu + pw / 2, v, bar / 2], frame);
    mb.box([pw, 0.04, bar], [cu + pw / 2, v, clearH - bar / 2], frame);
    mb.box([bar, 0.04, clearH - 2 * bar], [cu + bar / 2, v, clearH / 2], frame);
    mb.box([bar, 0.04, clearH - 2 * bar], [cu + pw - bar / 2, v, clearH / 2], frame);
  }
}
