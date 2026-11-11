// Construction order and timing of the build reveal. Pure: no React, no GPU, no clock, no
// randomness — the same model always gives the same order and the same schedule.
//
// Order (derived from the model): per storey (level index) the floor slab, the room floors, the
// exterior walls going around the perimeter, the interior walls, doors and windows, stairs;
// then roofs, the entrance canopy, balconies and railings; then furniture; then the site.
import type { ModelIndex } from "@/engine/model/model-index";
import type { BuildingElement, Wall } from "@/engine/model/types";

export type ConstructionStage =
  | "slab"
  | "floor"
  | "exterior_wall"
  | "interior_wall"
  | "opening"
  | "stair"
  | "roof"
  | "canopy"
  | "balcony"
  | "furniture"
  | "site";

/** Stages built storey by storey, in this order; the rest follows for the whole building. */
export const STOREY_STAGES: readonly ConstructionStage[] = [
  "slab",
  "floor",
  "exterior_wall",
  "interior_wall",
  "opening",
  "stair",
];
export const BUILDING_STAGES: readonly ConstructionStage[] = [
  "roof",
  "canopy",
  "balcony",
  "furniture",
  "site",
];

export interface ConstructionStep {
  /** Element id (or a site key from `gate.ts`). */
  id: string;
  stage: ConstructionStage;
  /** Position of the element's level among the levels sorted by index (0 = lowest). */
  storey: number;
  /** Running number of the step's group (one storey's stage, or one building stage). */
  group: number;
}

export function stageOf(el: BuildingElement): ConstructionStage {
  switch (el.type) {
    case "slab":
      return el.properties.slab_kind === "canopy"
        ? "canopy"
        : el.properties.slab_kind === "balcony"
          ? "balcony"
          : "slab";
    case "room":
      return "floor";
    case "wall":
      return el.properties.wall_kind === "exterior" ? "exterior_wall" : "interior_wall";
    case "door":
    case "window":
      return "opening";
    case "stair":
      return "stair";
    case "roof":
      return "roof";
    case "railing":
      return "balcony";
    case "furniture":
      return "furniture";
  }
}

const round = (x: number) => Math.round(x * 1000); // 1 mm grid: no float noise in the order

function wallMid(w: Wall): [number, number] {
  const half = w.dimensions.length / 2;
  return [
    w.position.x + Math.cos(w.rotation.z) * half,
    w.position.y + Math.sin(w.rotation.z) * half,
  ];
}

/**
 * Exterior walls of one storey, going once around the perimeter: sorted by the angle of the
 * wall's midpoint around the centre of those midpoints, starting at the south-west.
 */
function perimeterOrder(walls: Wall[]): Wall[] {
  if (walls.length === 0) return walls;
  const mids = walls.map(wallMid);
  const cx = mids.reduce((s, m) => s + m[0], 0) / mids.length;
  const cy = mids.reduce((s, m) => s + m[1], 0) / mids.length;
  const START = (-3 * Math.PI) / 4; // south-west
  const keyed = walls.map((w, i) => {
    const a = Math.atan2(mids[i]![1] - cy, mids[i]![0] - cx) - START;
    const turn = ((a % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
    return { w, angle: Math.round(turn * 1e6) };
  });
  keyed.sort((a, b) => a.angle - b.angle || a.w.id.localeCompare(b.w.id));
  return keyed.map((k) => k.w);
}

const byPlace = (a: BuildingElement, b: BuildingElement) =>
  round(a.position.z) - round(b.position.z) ||
  round(a.position.x) - round(b.position.x) ||
  round(a.position.y) - round(b.position.y) ||
  a.id.localeCompare(b.id);

/**
 * Every element of the model in construction order. Independent of the order of
 * `model.elements`. `site` appends the site steps (keys, e.g. paving + fence, then each plant).
 */
export function constructionOrder(
  index: ModelIndex,
  site: readonly string[] = [],
): ConstructionStep[] {
  const storeyOf = new Map(index.levels.map((l, i) => [l.id, i]));
  const buckets = new Map<string, BuildingElement[]>();
  for (const el of index.model.elements) {
    const stage = stageOf(el);
    const storey = STOREY_STAGES.includes(stage) ? (storeyOf.get(el.level_id ?? "") ?? 0) : -1;
    const key = `${storey}:${stage}`;
    const list = buckets.get(key);
    if (list) list.push(el);
    else buckets.set(key, [el]);
  }

  const steps: ConstructionStep[] = [];
  let group = 0;
  const wallRank = new Map<string, number>();
  const emit = (stage: ConstructionStage, storey: number, elements: BuildingElement[]) => {
    if (elements.length === 0) return;
    for (const el of elements) {
      steps.push({
        id: el.id,
        stage,
        storey: storey >= 0 ? storey : (storeyOf.get(el.level_id ?? "") ?? 0),
        group,
      });
    }
    group += 1;
  };

  const storeys = Math.max(index.levels.length, 1);
  for (let storey = 0; storey < storeys; storey++) {
    for (const stage of STOREY_STAGES) {
      const list = [...(buckets.get(`${storey}:${stage}`) ?? [])];
      if (stage === "exterior_wall") {
        const ordered = perimeterOrder(list as Wall[]);
        ordered.forEach((w) => wallRank.set(w.id, wallRank.size));
        emit(stage, storey, ordered);
      } else if (stage === "opening") {
        // Along the walls in the order they were built, then along each wall.
        const rank = (el: BuildingElement) =>
          wallRank.get(index.hostOf.get(el.id)?.id ?? "") ?? Number.MAX_SAFE_INTEGER;
        list.sort(
          (a, b) => rank(a) - rank(b) || round(a.position.x) - round(b.position.x) || byPlace(a, b),
        );
        emit(stage, storey, list);
      } else {
        list.sort(byPlace);
        if (stage === "interior_wall") list.forEach((w) => wallRank.set(w.id, wallRank.size));
        emit(stage, storey, list);
      }
    }
  }
  const level = (el: BuildingElement) => storeyOf.get(el.level_id ?? "") ?? 0;
  for (const stage of BUILDING_STAGES) {
    if (stage === "site") continue;
    const list = [...(buckets.get(`-1:${stage}`) ?? [])];
    list.sort((a, b) => level(a) - level(b) || byPlace(a, b));
    emit(stage, -1, list);
  }
  if (site.length > 0) {
    for (const id of site) steps.push({ id, stage: "site", storey: 0, group });
  }
  return steps;
}

/** What the schedule needs to know about a step's pieces. */
export interface StepExtent {
  /** Height of the element's pieces (top target − base), meters. */
  height: number;
}

export interface ScheduleConfig {
  /** Seconds before the first element starts (the blueprint draws itself). */
  lead: number;
  /** Total length: `minDuration + secondsPerElement × elements`, at most `maxDuration`. */
  minDuration: number;
  maxDuration: number;
  secondsPerElement: number;
  /** One piece's rise from the element base to its place. */
  rise: number;
  /** Largest per-piece random delay. */
  jitter: number;
  /** Bottom-to-top arrival spread of an element: height × this, within [min, max]. */
  spreadPerMeter: number;
  minSpread: number;
  maxSpread: number;
  /** The real mesh fades in over this time once every piece has landed. */
  fade: number;
  /** The pieces shrink away over this time, starting `shrinkDelay × fade` into the fade. */
  shrink: number;
  shrinkDelay: number;
  /** Relative time each stage's elements take before the next one starts. */
  stageWeight: Readonly<Record<ConstructionStage, number>>;
  /** Extra pause (in the same units) between two groups. */
  groupGap: number;
}

export interface StepTiming {
  /** The element's first piece leaves the base. */
  start: number;
  /** Arrival spread between the lowest and the highest piece. */
  spread: number;
  /** Every piece has landed: the real mesh starts to appear. */
  landed: number;
  /** The real mesh is fully shown. */
  shown: number;
  /** The pieces start to shrink / are gone. */
  vanish: number;
  end: number;
}

export interface ConstructionSchedule {
  timings: ReadonlyMap<string, StepTiming>;
  /** Seconds until the last piece is gone. */
  duration: number;
}

/**
 * Start times follow the construction order (never earlier than the step before), with a
 * small stagger inside a group and a pause between groups; the whole build is fitted into the
 * duration for the model's size.
 */
export function scheduleConstruction(
  steps: readonly ConstructionStep[],
  extents: ReadonlyMap<string, StepExtent>,
  cfg: ScheduleConfig,
): ConstructionSchedule {
  const spreads = steps.map((s) => {
    const h = extents.get(s.id)?.height ?? 0;
    return Math.min(Math.max(h * cfg.spreadPerMeter, cfg.minSpread), cfg.maxSpread);
  });
  // Time from an element's start until its pieces are gone.
  const tail = (i: number) =>
    spreads[i]! + cfg.jitter + cfg.rise + cfg.shrinkDelay * cfg.fade + cfg.shrink;
  const offsets: number[] = [];
  let cursor = 0;
  steps.forEach((s, i) => {
    if (i > 0) {
      const prev = steps[i - 1]!;
      cursor += cfg.stageWeight[prev.stage] + (prev.group !== s.group ? cfg.groupGap : 0);
    }
    offsets.push(cursor);
  });
  const total = Math.min(
    Math.max(cfg.minDuration + cfg.secondsPerElement * steps.length, cfg.minDuration),
    cfg.maxDuration,
  );
  // The largest unit that lets every element finish within the total.
  let unit = Infinity;
  steps.forEach((_, i) => {
    if (offsets[i]! > 0) unit = Math.min(unit, (total - cfg.lead - tail(i)) / offsets[i]!);
  });
  if (!Number.isFinite(unit)) unit = 0;
  unit = Math.max(unit, 0);

  const timings = new Map<string, StepTiming>();
  let duration = cfg.lead;
  steps.forEach((s, i) => {
    const start = cfg.lead + offsets[i]! * unit;
    const landed = start + spreads[i]! + cfg.jitter + cfg.rise;
    const vanish = landed + cfg.shrinkDelay * cfg.fade;
    const end = Math.max(vanish + cfg.shrink, landed + cfg.fade);
    timings.set(s.id, {
      start,
      spread: spreads[i]!,
      landed,
      shown: landed + cfg.fade,
      vanish,
      end,
    });
    duration = Math.max(duration, end);
  });
  return { timings, duration };
}
