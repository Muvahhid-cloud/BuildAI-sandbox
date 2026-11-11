// The blueprint of the build reveal: the real ground-floor plan (the outline of every wall of
// the lowest storey, from the model) that draws itself on the ground before construction
// starts. Pure: segments and timing only; the GPU objects are in gpu.ts.
import type { ModelIndex } from "@/engine/model/model-index";
import type { Wall } from "@/engine/model/types";

export interface BlueprintSegment {
  /** End points in plan (model x, y). */
  ax: number;
  ay: number;
  bx: number;
  by: number;
  /** Drawing progress (0..1 over the whole plan) at which each end is reached. */
  from: number;
  to: number;
}

export interface BlueprintPlan {
  segments: BlueprintSegment[];
  /** Model height the plan is drawn at (the lowest storey's floor level). */
  z: number;
  /** Total length of wall axis drawn (meters). */
  length: number;
}

/**
 * Wall outlines of the lowest storey, drawn wall after wall in the order of `wallIds` (the
 * construction order: around the perimeter, then the interior walls). Each wall draws along
 * its axis; its two faces and two ends are four segments.
 */
export function blueprintPlan(index: ModelIndex, wallIds: readonly string[]): BlueprintPlan {
  const ground = index.levels[0];
  const walls: Wall[] = [];
  for (const id of wallIds) {
    const el = index.elementsById.get(id);
    if (el?.type === "wall" && (!ground || el.level_id === ground.id)) walls.push(el);
  }
  const length = walls.reduce((s, w) => s + w.dimensions.length, 0);
  const segments: BlueprintSegment[] = [];
  let done = 0;
  for (const w of walls) {
    const len = w.dimensions.length;
    const half = w.dimensions.thickness / 2;
    const ux = Math.cos(w.rotation.z);
    const uy = Math.sin(w.rotation.z);
    const from = length > 0 ? done / length : 0;
    done += len;
    const to = length > 0 ? done / length : 1;
    const at = (along: number, side: number): [number, number] => [
      w.position.x + ux * along - uy * side,
      w.position.y + uy * along + ux * side,
    ];
    const add = (a: [number, number], b: [number, number], f: number, t: number) =>
      segments.push({ ax: a[0], ay: a[1], bx: b[0], by: b[1], from: f, to: t });
    add(at(0, half), at(len, half), from, to);
    add(at(0, -half), at(len, -half), from, to);
    add(at(0, -half), at(0, half), from, from);
    add(at(len, -half), at(len, half), to, to);
  }
  return { segments, z: ground?.elevation ?? 0, length };
}

export interface BlueprintTiming {
  /** The plan draws itself over this time (seconds). */
  draw: number;
  /** Then the lines fade to `trace` opacity over this time. */
  settle: number;
  trace: number;
  /** Lines and sheet fade out over this time at the end of the build. */
  out: number;
}

export interface BlueprintFrame {
  /** Share of the plan drawn (0..1). */
  progress: number;
  /** Opacity of the lines and of the paper sheet under them (0..1). */
  lines: number;
  sheet: number;
}

const smooth = (x: number) => {
  const t = Math.min(Math.max(x, 0), 1);
  return t * t * (3 - 2 * t);
};

/** What the blueprint shows `elapsed` seconds into a build of `duration` seconds. */
export function blueprintFrame(
  elapsed: number,
  duration: number,
  t: BlueprintTiming,
): BlueprintFrame {
  const out = 1 - smooth((elapsed - (duration - t.out)) / t.out);
  const settle = smooth((elapsed - t.draw) / t.settle);
  return {
    progress: smooth(elapsed / t.draw),
    lines: (1 - (1 - t.trace) * settle) * out,
    sheet: smooth(elapsed / (t.draw * 0.35)) * out,
  };
}
