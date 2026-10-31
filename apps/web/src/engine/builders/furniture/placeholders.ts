// Procedural placeholder furniture (Phase 1). Local frame: origin = base center on the floor,
// width along x, depth along y (front faces -y, back is +y), height along z.
// Each placeholder is sized from the element's dimensions, so any size renders plausibly.
import type { FurnitureKind } from "@buildai/schema";

import type { MeshBuilder } from "../../geometry/mesh-builder";

export interface PlaceholderDims {
  w: number;
  d: number;
  h: number;
}

type Draw = (mb: MeshBuilder, dims: PlaceholderDims, material: string) => void;

function legs(
  mb: MeshBuilder,
  { w, d }: PlaceholderDims,
  height: number,
  size: number,
  material: string,
) {
  const x = w / 2 - size / 2 - 0.02;
  const y = d / 2 - size / 2 - 0.02;
  for (const [sx, sy] of [
    [-1, -1],
    [1, -1],
    [1, 1],
    [-1, 1],
  ]) {
    mb.box([size, size, height], [sx * x, sy * y, height / 2], material);
  }
}

function table(topT: number): Draw {
  return (mb, dims, material) => {
    mb.box([dims.w, dims.d, topT], [0, 0, dims.h - topT / 2], material);
    legs(mb, dims, dims.h - topT, 0.05, material);
  };
}

function seat(armW: number): Draw {
  return (mb, { w, d, h }, material) => {
    const seatH = Math.min(0.45, h * 0.55);
    const back = Math.min(0.22, d * 0.25);
    mb.box([w, d, 0.08], [0, 0, 0.04], "wood_dark"); // plinth / legs
    mb.box(
      [w - 2 * armW, d - back, seatH - 0.08],
      [0, -back / 2, 0.08 + (seatH - 0.08) / 2],
      material,
    );
    mb.box([w, back, h - 0.08], [0, d / 2 - back / 2, 0.08 + (h - 0.08) / 2], material);
    if (armW > 0) {
      const armH = seatH + 0.18;
      mb.box(
        [armW, d - back, armH - 0.08],
        [-(w / 2 - armW / 2), -back / 2, 0.08 + (armH - 0.08) / 2],
        material,
      );
      mb.box(
        [armW, d - back, armH - 0.08],
        [w / 2 - armW / 2, -back / 2, 0.08 + (armH - 0.08) / 2],
        material,
      );
    }
  };
}

function cabinet(topMaterial: string | null, withSink: boolean): Draw {
  return (mb, { w, d, h }, material) => {
    const topT = topMaterial ? 0.04 : 0;
    mb.box(
      [w, d - 0.02, h - topT - 0.1],
      [0, 0.01, 0.1 + (h - topT - 0.1) / 2],
      topMaterial ? "cabinet" : material,
    );
    mb.box([w - 0.04, d - 0.08, 0.1], [0, 0.03, 0.05], "wood_dark"); // recessed plinth
    if (topMaterial) mb.box([w, d, topT], [0, 0, h - topT / 2], material);
    if (withSink) {
      mb.box([0.6, 0.4, 0.012], [w * 0.15, 0, h + 0.006], "metal");
      mb.box([0.03, 0.03, 0.25], [w * 0.15, d / 2 - 0.08, h + 0.125], "metal");
    }
  };
}

export const FURNITURE_PLACEHOLDERS: Record<FurnitureKind, Draw> = {
  sofa: seat(0.18),
  armchair: seat(0.16),
  coffee_table: table(0.04),
  dining_table: table(0.05),
  desk: table(0.04),
  chair: (mb, { w, d, h }, material) => {
    const seatH = 0.45;
    legs(mb, { w, d, h }, seatH - 0.04, 0.035, material);
    mb.box([w, d, 0.04], [0, 0, seatH - 0.02], material);
    mb.box([w, 0.04, h - seatH], [0, d / 2 - 0.02, seatH + (h - seatH) / 2], material);
  },
  tv_unit: (mb, { w, d, h }, material) => {
    mb.box([w, d, h], [0, 0, h / 2], material);
    const sw = w * 0.75;
    const sh = sw * 0.5625;
    mb.box([sw, 0.04, sh], [0, 0, h + 0.1 + sh / 2], "screen");
    mb.box([0.3, 0.2, 0.1], [0, 0, h + 0.05], "screen");
  },
  bed: (mb, { w, d, h }, material) => {
    mb.box([w, d, 0.28], [0, 0, 0.14], "wood");
    mb.box([w - 0.06, d - 0.1, h - 0.28], [0, -0.03, 0.28 + (h - 0.28) / 2], material);
    mb.box([w, 0.08, 1.0], [0, d / 2 - 0.04, 0.5], "wood");
    const pw = Math.min(0.7, w / 2 - 0.1);
    for (const sx of w > 1.2 ? [-1, 1] : [0]) {
      mb.box([pw, 0.4, 0.12], [sx * (w / 4), d / 2 - 0.35, h + 0.06], "fabric_light");
    }
  },
  nightstand: (mb, { w, d, h }, material) => mb.box([w, d, h], [0, 0, h / 2], material),
  wardrobe: (mb, { w, d, h }, material) => {
    mb.box([w, d, h], [0, 0, h / 2], material);
    const doors = Math.max(2, Math.round(w / 0.5));
    for (let i = 1; i < doors; i++) {
      mb.box([0.01, 0.01, h - 0.1], [-w / 2 + (i * w) / doors, -d / 2 - 0.004, h / 2], "wood_dark");
    }
  },
  bookshelf: (mb, { w, d, h }, material) => {
    const b = 0.025;
    mb.box([b, d, h], [-w / 2 + b / 2, 0, h / 2], material);
    mb.box([b, d, h], [w / 2 - b / 2, 0, h / 2], material);
    mb.box([w, b, h], [0, d / 2 - b / 2, h / 2], material);
    const shelves = Math.max(2, Math.round(h / 0.38));
    for (let i = 0; i <= shelves; i++) {
      mb.box(
        [w - 2 * b, d - b, b],
        [0, -b / 2, Math.min(h - b / 2, b / 2 + (i * (h - b)) / shelves)],
        material,
      );
    }
  },
  kitchen_counter: cabinet("countertop", true),
  kitchen_island: cabinet("countertop", false),
  fridge: (mb, { w, d, h }, material) => {
    mb.box([w, d, h], [0, 0, h / 2], material);
    mb.box([0.03, 0.03, 0.5], [w / 2 - 0.08, -d / 2 - 0.02, h * 0.62], "wood_dark");
  },
  toilet: (mb, { w, d, h }, material) => {
    mb.box([w * 0.7, d * 0.55, 0.38], [0, -d * 0.1, 0.19], material);
    mb.box([w, d * 0.7, 0.06], [0, -d * 0.15, 0.41], material);
    mb.box([w, d * 0.28, h - 0.38], [0, d / 2 - d * 0.14, 0.38 + (h - 0.38) / 2], material);
  },
  basin: (mb, { w, d, h }, material) => {
    mb.box([w, d, h - 0.14], [0, 0, (h - 0.14) / 2], "wood");
    mb.box([w, d, 0.14], [0, 0, h - 0.07], material);
    mb.box([0.03, 0.03, 0.22], [0, d / 2 - 0.06, h + 0.11], "metal");
  },
  bathtub: (mb, { w, d, h }, material) => {
    const s = 0.07;
    mb.box([w, d, 0.1], [0, 0, 0.05], material);
    mb.box([w, s, h], [0, -d / 2 + s / 2, h / 2], material);
    mb.box([w, s, h], [0, d / 2 - s / 2, h / 2], material);
    mb.box([s, d - 2 * s, h], [-w / 2 + s / 2, 0, h / 2], material);
    mb.box([s, d - 2 * s, h], [w / 2 - s / 2, 0, h / 2], material);
  },
  shower: (mb, { w, d, h }) => {
    mb.box([w, d, 0.05], [0, 0, 0.025], "ceramic");
    mb.box([0.2, 0.2, 0.02], [0, d / 2 - 0.15, h - 0.01], "metal");
    mb.box(
      [0.025, 0.025, h - 0.05],
      [w / 2 - 0.0125, -d / 2 + 0.0125, 0.05 + (h - 0.05) / 2],
      "metal",
    );
  },
};

/** Glass parts of placeholders (rendered separately: transparent, no shadows). */
export const FURNITURE_GLASS: Partial<Record<FurnitureKind, Draw>> = {
  shower: (mb, { w, d, h }, material) => {
    mb.box([w - 0.03, 0.01, h - 0.05], [-0.015, -d / 2 + 0.005, 0.05 + (h - 0.05) / 2], material);
    mb.box([0.01, d - 0.03, h - 0.05], [w / 2 - 0.005, 0.015, 0.05 + (h - 0.05) / 2], material);
  },
};
