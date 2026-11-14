import { Group, Mesh, Quaternion, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { indexModel } from "@/engine/model/model-index";
import { buildScene } from "@/engine/scene/build-scene";
import { cameraPose } from "@/engine/scene/camera-presets";
import { demoIndex, generatedLModelJson, generatedModelJson } from "@/engine/test-fixtures";
import { parseBuildingModel } from "@/engine/model/parse";

import { REVEAL } from "../render-settings";
import { blueprintFrame, blueprintPlan } from "./blueprint";
import { orbitPose } from "./camera";
import { gateScene, HIDDEN_LAYER, plantKey, revealTag, SITE_KEY, ungateScene } from "./gate";
import {
  BUILDING_STAGES,
  type ConstructionStage,
  constructionOrder,
  frontEase,
  frontEaseInverse,
  frontTime,
  growthAt,
  scheduleConstruction,
  stageOf,
  STOREY_STAGES,
} from "./order";
import { pieceScale, pieceState } from "./pieces";
import { buildRevealPlan } from "./plan";

const generatedIndex = () => parseBuildingModel(generatedModelJson());

describe("construction order", () => {
  it("contains every element once and does not depend on the order of model.elements", () => {
    const index = generatedIndex();
    const steps = constructionOrder(index);
    expect(steps).toHaveLength(index.model.elements.length);
    expect(new Set(steps.map((s) => s.id)).size).toBe(steps.length);

    const shuffled = generatedModelJson();
    shuffled.elements.reverse();
    expect(constructionOrder(indexModel(shuffled))).toEqual(steps);
    expect(constructionOrder(generatedIndex())).toEqual(steps);
  });

  it("builds storey by storey: slab, floors, exterior walls, interior walls, openings, stairs", () => {
    const index = generatedIndex();
    const steps = constructionOrder(index);
    const structure = steps.filter((s) => STOREY_STAGES.includes(s.stage));
    expect(index.levels.length).toBe(2);
    // The whole lower storey comes before anything of the upper one …
    const storeys = structure.map((s) => s.storey);
    expect(storeys).toEqual([...storeys].sort((a, b) => a - b));
    expect(new Set(storeys)).toEqual(new Set([0, 1]));
    // … and inside a storey the stages follow the building sequence.
    for (const storey of [0, 1]) {
      const stages = structure.filter((s) => s.storey === storey).map((s) => s.stage);
      const ranks = stages.map((stage) => STOREY_STAGES.indexOf(stage));
      expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
      expect(stages[0]).toBe("slab");
      expect(stages).toContain("exterior_wall");
      expect(stages).toContain("opening");
    }
    // A step's storey is its element's level.
    for (const s of structure) {
      const el = index.elementsById.get(s.id)!;
      expect(index.levels[s.storey]!.id).toBe(el.level_id);
      expect(stageOf(el)).toBe(s.stage);
    }
  });

  it("then roofs, canopy, balconies and railings, furniture, and the site last", () => {
    const index = generatedIndex();
    const site = [SITE_KEY, plantKey("tree", 0)];
    const steps = constructionOrder(index, site);
    const firstLate = steps.findIndex((s) => BUILDING_STAGES.includes(s.stage));
    expect(steps.slice(0, firstLate).every((s) => STOREY_STAGES.includes(s.stage))).toBe(true);
    const late = steps.slice(firstLate).map((s) => s.stage);
    expect(late.every((stage) => BUILDING_STAGES.includes(stage))).toBe(true);
    const ranks = late.map((stage) => BUILDING_STAGES.indexOf(stage));
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
    for (const stage of ["roof", "canopy", "balcony", "furniture"] as ConstructionStage[]) {
      expect(late).toContain(stage);
    }
    expect(steps.slice(-2).map((s) => s.id)).toEqual(site);
    // Balcony slabs and railings are not built with the storey's floor slab.
    const balcony = index.model.elements.find(
      (e) => e.type === "slab" && e.properties.slab_kind === "balcony",
    )!;
    expect(steps.find((s) => s.id === balcony.id)!.stage).toBe("balcony");
  });

  it("goes around the perimeter: consecutive exterior walls turn one way around the plan", () => {
    const index = generatedIndex();
    const walls = constructionOrder(index)
      .filter((s) => s.stage === "exterior_wall" && s.storey === 0)
      .map((s) => index.elementsById.get(s.id)!);
    expect(walls.length).toBeGreaterThan(3);
    const mid = walls.map((w) => {
      if (w.type !== "wall") throw new Error("not a wall");
      const half = w.dimensions.length / 2;
      return [
        w.position.x + Math.cos(w.rotation.z) * half,
        w.position.y + Math.sin(w.rotation.z) * half,
      ] as const;
    });
    const cx = mid.reduce((s, m) => s + m[0], 0) / mid.length;
    const cy = mid.reduce((s, m) => s + m[1], 0) / mid.length;
    const START = (-3 * Math.PI) / 4;
    const turn = mid.map((m) => {
      const a = Math.atan2(m[1] - cy, m[0] - cx) - START;
      return ((a % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
    });
    for (let i = 1; i < turn.length; i++)
      expect(turn[i]!).toBeGreaterThanOrEqual(turn[i - 1]! - 1e-6);
  });

  it("gives doors and windows the order of the walls that host them", () => {
    const index = generatedIndex();
    const steps = constructionOrder(index);
    const wallAt = new Map(
      steps.filter((s) => s.stage.endsWith("wall")).map((s, i) => [s.id, i] as const),
    );
    for (const storey of [0, 1]) {
      const hosts = steps
        .filter((s) => s.stage === "opening" && s.storey === storey)
        .map((s) => wallAt.get(index.hostOf.get(s.id)!.id)!);
      expect(hosts).toEqual([...hosts].sort((a, b) => a - b));
    }
  });
});

describe("construction schedule", () => {
  const scene = buildScene(generatedIndex());
  const plan = buildRevealPlan(scene, { seed: "model-hash:build", site: { plants: new Set() } });
  const { timings, duration } = plan.schedule;
  const p = REVEAL.pieces;

  it("starts elements in construction order, after the blueprint, with a stagger", () => {
    const starts = plan.steps.map((s) => timings.get(s.id)!.start);
    expect(starts[0]).toBeCloseTo(REVEAL.schedule.lead);
    for (let i = 1; i < starts.length; i++) expect(starts[i]!).toBeGreaterThan(starts[i - 1]!);
    // The upper storey's slab starts after every structural element of the lower storey.
    const upperSlab = plan.steps.find((s) => s.storey === 1 && s.stage === "slab")!;
    const lower = plan.steps.filter((s) => s.storey === 0 && STOREY_STAGES.includes(s.stage));
    const lastLower = Math.max(...lower.map((s) => timings.get(s.id)!.start));
    expect(timings.get(upperSlab.id)!.start).toBeGreaterThan(lastLower);
    // The pause between groups is longer than the stagger inside the group before it.
    for (let i = 2; i < plan.steps.length; i++) {
      const [a, b, c] = [plan.steps[i - 2]!, plan.steps[i - 1]!, plan.steps[i]!];
      if (a.group === b.group && b.group !== c.group) {
        expect(starts[i]! - starts[i - 1]!).toBeGreaterThan(starts[i - 1]! - starts[i - 2]!);
      }
    }
  });

  it("grows every element from its own base to its own top, for at least the minimum time", () => {
    for (const step of plan.steps) {
      const t = timings.get(step.id)!;
      const parts = scene.byElement.get(step.id);
      if (parts) {
        // The extent is the element's real geometry (model z).
        let min = Infinity;
        let max = -Infinity;
        for (const d of parts) {
          const box = d.geometry.boundingBox!.clone().applyMatrix4(d.matrix);
          min = Math.min(min, box.min.z);
          max = Math.max(max, box.max.z);
        }
        expect(t.baseZ).toBeCloseTo(min, 6);
        expect(t.topZ).toBeCloseTo(max, 6);
      }
      expect(t.from - t.start).toBeCloseTo(p.settle + p.early); // the first slices settle
      const grow = t.end - t.from;
      expect(grow).toBeGreaterThanOrEqual(REVEAL.schedule.minGrow - 1e-9);
      expect(grow).toBeLessThanOrEqual(REVEAL.schedule.maxGrow + 1e-9);
    }
    // Small elements are visibly built too; a storey-high wall takes longer than a window.
    const of = (stage: ConstructionStage) => {
      const t = timings.get(plan.steps.find((s) => s.stage === stage)!.id)!;
      return t.end - t.from;
    };
    expect(of("opening")).toBeGreaterThanOrEqual(0.8 - 1e-9);
    expect(of("furniture")).toBeGreaterThanOrEqual(0.8 - 1e-9);
    expect(of("exterior_wall")).toBeGreaterThan(of("opening"));
  });

  it("moves the front bottom to top only, eased at both ends (never linear, never sideways)", () => {
    const wall = timings.get(plan.steps.find((s) => s.stage === "exterior_wall")!.id)!;
    expect(growthAt(wall, wall.start)).toBe(0);
    expect(growthAt(wall, wall.from)).toBe(0);
    expect(growthAt(wall, wall.end)).toBe(1);
    expect(growthAt(wall, wall.end + 5)).toBe(1);
    let previous = 0;
    for (let k = 0; k <= 1.0001; k += 0.05) {
      const share = growthAt(wall, wall.from + k * (wall.end - wall.from));
      expect(share).toBeGreaterThanOrEqual(previous); // the front never goes back down
      previous = share;
    }
    // Slow off the base and onto the top, fastest in the middle.
    expect(frontEase(0.1)).toBeLessThan(0.1);
    expect(frontEase(0.9)).toBeGreaterThan(0.9);
    expect(frontEase(0.5)).toBeCloseTo(0.5);
    for (const f of [0, 0.2, 0.5, 0.8, 1]) expect(frontEase(frontEaseInverse(f))).toBeCloseTo(f);
    // The front reaches a height exactly when the growth share says so.
    const z = wall.baseZ + 0.3 * (wall.topZ - wall.baseZ);
    expect(growthAt(wall, frontTime(wall, z))).toBeCloseTo(0.3);
    expect(frontTime(wall, wall.baseZ)).toBeCloseTo(wall.from);
    expect(frontTime(wall, wall.topZ)).toBeCloseTo(wall.end);
  });

  it("overlaps: the next element starts before the one before it is complete", () => {
    const walls = plan.steps.filter((s) => s.stage === "exterior_wall" && s.storey === 0);
    expect(walls.length).toBeGreaterThan(2);
    for (let i = 1; i < walls.length; i++) {
      expect(timings.get(walls[i]!.id)!.start).toBeLessThan(timings.get(walls[i - 1]!.id)!.end);
    }
  });

  it("lasts 6 to 10 seconds, scaled with the model, and is deterministic", () => {
    expect(duration).toBeGreaterThanOrEqual(REVEAL.schedule.minDuration - 1e-6);
    expect(duration).toBeLessThanOrEqual(REVEAL.schedule.maxDuration + 1e-6);
    expect(REVEAL.schedule.minDuration).toBe(6);
    expect(REVEAL.schedule.maxDuration).toBe(10);
    const small = buildRevealPlan(buildScene(demoIndex()), { seed: "x" });
    const large = buildRevealPlan(buildScene(parseBuildingModel(generatedLModelJson())), {
      seed: "x",
    });
    for (const other of [small, large]) {
      expect(other.schedule.duration).toBeGreaterThanOrEqual(6 - 1e-6);
      expect(other.schedule.duration).toBeLessThanOrEqual(10 + 1e-6);
    }
    const again = buildRevealPlan(buildScene(generatedIndex()), {
      seed: "model-hash:build",
      site: { plants: new Set() },
    });
    expect(again.steps).toEqual(plan.steps);
    expect([...again.schedule.timings]).toEqual([...timings]);
    expect(again.front).toEqual(plan.front);
    const cfg = {
      ...REVEAL.schedule,
      settle: p.settle + p.early,
      absorb: p.absorb,
    };
    const one = scheduleConstruction(plan.steps.slice(0, 1), new Map(), cfg);
    expect(one.duration).toBeLessThan(REVEAL.schedule.minDuration); // nothing is stretched
  });

  it("grows only the changed elements again, in a short version without the blueprint", () => {
    const changed = new Set(plan.steps.slice(40, 46).map((s) => s.id));
    const short = buildRevealPlan(scene, {
      seed: "model-hash:changes",
      include: (id) => changed.has(id),
      short: true,
    });
    expect(new Set(short.steps.map((s) => s.id))).toEqual(changed);
    expect(short.schedule.duration).toBeLessThanOrEqual(REVEAL.changes.duration + 1e-6);
    expect(short.schedule.timings.get(short.steps[0]!.id)!.start).toBe(0);
    for (const key of short.pieces.keys) expect(changed.has(key)).toBe(true);
  });
});

describe("pieces", () => {
  const scene = buildScene(generatedIndex());
  const plan = buildRevealPlan(scene, { seed: "model-hash:build", site: { plants: new Set() } });
  const { pieces, front, schedule } = plan;
  const p = REVEAL.pieces;
  const keyOf = (i: number) => pieces.keys[pieces.item[i]!]!;

  it("are deterministic for a model hash and differ for another one", () => {
    const same = buildRevealPlan(buildScene(generatedIndex()), {
      seed: "model-hash:build",
      site: { plants: new Set() },
    }).pieces;
    expect(same.target).toEqual(pieces.target);
    expect(same.quat).toEqual(pieces.quat);
    expect(same.batches).toEqual(pieces.batches);
    const other = buildRevealPlan(scene, { seed: "other:build", site: { plants: new Set() } });
    expect(other.pieces.target).not.toEqual(pieces.target);
  });

  it("stay within the budget, adapt their density, and give every built element some", () => {
    expect(pieces.count).toBeGreaterThan(2000);
    expect(pieces.count).toBeLessThanOrEqual(p.maxPieces);
    const walls = plan.steps.filter((s) => s.stage === "exterior_wall");
    for (const w of walls) expect(pieces.counts.get(w.id)!).toBeGreaterThanOrEqual(p.minPerItem);
    for (const s of plan.steps.filter((x) => x.stage === "opening" || x.stage === "stair")) {
      expect(pieces.counts.get(s.id) ?? 0).toBeGreaterThanOrEqual(p.minPerItem);
    }
    // A tighter budget gives fewer pieces of the same size (never smaller boxes or dots).
    const tight = buildRevealPlan(scene, { seed: "model-hash:build" });
    expect(tight.pieces.count).toBeLessThanOrEqual(p.maxPieces);
  });

  it("are thin flat slices of about 0.36 × 0.22 × 0.035 m, scaled to the element", () => {
    expect([p.length, p.height, p.thickness]).toEqual([0.36, 0.22, 0.035]);
    for (let i = 0; i < pieces.count; i++) {
      const [long, short, thick] = [
        pieces.scale[i * 3]!,
        pieces.scale[i * 3 + 1]!,
        pieces.scale[i * 3 + 2]!,
      ];
      expect(long).toBeLessThanOrEqual(p.length);
      expect(long).toBeGreaterThanOrEqual(p.length * p.minScale * p.joint - 1e-6);
      expect(long / short).toBeCloseTo(p.length / p.height, 4);
      expect(thick).toBeLessThan(short / 4); // thin
    }
    expect(pieceScale(100, p)).toBe(1); // a wall: full size
    expect(pieceScale(1, p)).toBe(p.minScale); // a window: smaller slices
  });

  it("lie flat on the element's surface: thin axis = surface normal, long axis horizontal", () => {
    const q = new Quaternion();
    const long = new Vector3();
    const normal = new Vector3();
    let vertical = 0;
    for (let i = 0; i < pieces.count; i++) {
      q.fromArray(pieces.quat, i * 4);
      long.set(1, 0, 0).applyQuaternion(q);
      normal.set(0, 0, 1).applyQuaternion(q);
      expect(normal.z).toBeGreaterThanOrEqual(-0.5 - 1e-6); // nothing is laid from below
      if (Math.abs(normal.z) < 0.9) {
        vertical++;
        expect(Math.abs(long.z)).toBeLessThan(1e-5); // level courses on walls and roof slopes
      }
      expect(Math.abs(long.dot(normal))).toBeLessThan(1e-5);
    }
    expect(vertical).toBeGreaterThan(pieces.count / 2);
    // On the element: every target is inside the element's bounds (plus the slice thickness).
    for (let i = 0; i < pieces.count; i += 7) {
      const t = schedule.timings.get(keyOf(i))!;
      const z = pieces.target[i * 3 + 2]!;
      expect(z).toBeGreaterThanOrEqual(t.baseZ - p.height);
      expect(z).toBeLessThanOrEqual(t.topZ + p.height);
    }
  });

  it("are drawn in the element's real material: one batch (draw call) per library material", () => {
    const used = new Set<string>();
    for (const step of plan.steps) {
      for (const d of scene.byElement.get(step.id) ?? []) d.materials.forEach((m) => used.add(m));
    }
    let total = 0;
    const seen = new Set<string>();
    for (const batch of pieces.batches) {
      expect(seen.has(batch.material)).toBe(false);
      seen.add(batch.material);
      expect(batch.offset).toBe(total); // contiguous runs
      total += batch.count;
      expect(used.has(batch.material) || batch.material.startsWith("site")).toBe(true);
    }
    expect(total).toBe(pieces.count);
    expect(pieces.batches.length).toBeLessThan(40);
    // A wall's slices use that wall's own material keys.
    const wall = plan.steps.find((s) => s.stage === "exterior_wall")!;
    const keys = new Set(scene.byElement.get(wall.id)!.flatMap((d) => d.materials));
    for (const batch of pieces.batches) {
      for (let i = batch.offset; i < batch.offset + batch.count; i++) {
        if (keyOf(i) === wall.id) expect(keys.has(batch.material)).toBe(true);
      }
    }
  });

  it("exist only at the growing front: none before or after their element grows", () => {
    const motion = { ...p };
    for (let i = 0; i < pieces.count; i += 3) {
      const t = schedule.timings.get(keyOf(i))!;
      const at = front[i]!;
      const seed = pieces.seed[i]!;
      // The front reaches the piece while its element grows …
      expect(at).toBeGreaterThanOrEqual(t.from - 1e-4);
      expect(at).toBeLessThanOrEqual(t.end + 1e-4);
      expect(at).toBeCloseTo(frontTime(t, pieces.target[i * 3 + 2]!), 4);
      // … and the piece is there only around that moment.
      expect(pieceState(at, seed, t.start - 0.01, motion).visible).toBe(false);
      expect(pieceState(at, seed, at - p.settle - p.early - 0.01, motion).visible).toBe(false);
      expect(pieceState(at, seed, at - 0.01, motion).visible).toBe(true);
      expect(pieceState(at, seed, at + p.absorb + 0.001, motion).visible).toBe(false);
      expect(pieceState(at, seed, t.end + p.absorb + 0.001, motion).size).toBe(0);
    }
    // Lower slices of an element are reached first: the front rises.
    const wall = plan.steps.find((s) => s.stage === "exterior_wall")!;
    const own = [...Array(pieces.count).keys()].filter((i) => keyOf(i) === wall.id);
    own.sort((a, b) => pieces.target[a * 3 + 2]! - pieces.target[b * 3 + 2]!);
    for (let k = 1; k < own.length; k++) {
      expect(front[own[k]!]!).toBeGreaterThanOrEqual(front[own[k - 1]!]! - 1e-6);
    }
    // At any moment only a small share of all pieces is on screen.
    for (const elapsed of [2, 3.5, 5, 6.5]) {
      let visible = 0;
      for (let i = 0; i < pieces.count; i++) {
        if (pieceState(front[i]!, pieces.seed[i]!, elapsed, motion).visible) visible++;
      }
      expect(visible).toBeLessThan(pieces.count * 0.35);
    }
  });

  it("settle from about half a meter in about 0.3 s, ease out, and press the last centimeters", () => {
    expect(p.approach).toBeCloseTo(0.5);
    expect(p.settle).toBeCloseTo(0.3);
    expect(p.settleDrop).toBeGreaterThanOrEqual(0.02);
    expect(p.settleDrop).toBeLessThanOrEqual(0.03);
    const motion = { ...p };
    const at = 5;
    const offset = (elapsed: number) => pieceState(at, 0, elapsed, motion).offset;
    expect(offset(at - p.settle)).toBeCloseTo(p.approach + p.settleDrop);
    expect(offset(at)).toBe(0); // exactly in place when the front arrives
    let previous = Infinity;
    const steps: number[] = [];
    for (let k = 0; k <= 1.0001; k += 0.1) {
      const d = offset(at - p.settle + k * p.settle);
      expect(d).toBeLessThanOrEqual(previous + 1e-9); // never away from its place
      if (previous !== Infinity) steps.push(previous - d);
      previous = d;
    }
    expect(steps[0]!).toBeGreaterThan(steps[5]! * 2); // ease-out: fast first, slow at the end
    // It sinks into the surface as the front passes — no pop.
    expect(pieceState(at, 0, at + p.absorb / 2, motion).size).toBeGreaterThan(0);
    expect(pieceState(at, 0, at + p.absorb / 2, motion).size).toBeLessThan(1);
  });

  it("gives glTF furniture, plants and flat top faces no pieces", () => {
    const served = buildRevealPlan(scene, {
      seed: "model-hash:build",
      site: { plants: new Set(["tree"]) },
      modelServed: () => true,
    });
    const furniture = served.steps.filter((s) => s.stage === "furniture");
    expect(furniture.length).toBeGreaterThan(0);
    let withModel = 0;
    for (const s of furniture) {
      if (!served.objects.has(s.id)) continue;
      withModel++;
      expect(served.pieces.counts.has(s.id)).toBe(false);
      expect(served.schedule.timings.has(s.id)).toBe(true); // still grows, from its model
    }
    expect(withModel).toBeGreaterThan(0);
    expect(served.objects.has(SITE_KEY)).toBe(true);
    const tree = served.steps.find((s) => s.id.startsWith("site:tree"));
    expect(tree && served.pieces.counts.has(tree.id)).toBe(false);
    // Floors, slab tops and roof decks are reached by the front all at once: no slices
    // flash on them. Only stair treads (reached one after the other) carry flat pieces.
    const stairs = new Set(plan.steps.filter((s) => s.stage === "stair").map((s) => s.id));
    const q = new Quaternion();
    const normal = new Vector3();
    let onTreads = 0;
    for (let i = 0; i < pieces.count; i++) {
      q.fromArray(pieces.quat, i * 4);
      normal.set(0, 0, 1).applyQuaternion(q);
      if (normal.z < 0.9) continue;
      expect(stairs.has(keyOf(i))).toBe(true);
      onTreads++;
    }
    expect(onTreads).toBeGreaterThan(0);
    const floors = plan.steps.filter((s) => s.stage === "floor");
    expect(floors.length).toBeGreaterThan(0);
    for (const floor of floors) expect(pieces.counts.has(floor.id)).toBe(false);
  });
});

describe("blueprint", () => {
  const index = demoIndex();
  const walls = constructionOrder(index)
    .filter((s) => s.stage.endsWith("wall"))
    .map((s) => s.id);
  const plan = blueprintPlan(index, walls);

  it("draws the outline of every ground-floor wall of the model, in construction order", () => {
    const ground = index.model.elements.filter(
      (e) => e.type === "wall" && e.level_id === index.levels[0]!.id,
    );
    expect(plan.segments).toHaveLength(ground.length * 4);
    expect(plan.length).toBeCloseTo(
      ground.reduce((s, w) => s + (w.type === "wall" ? w.dimensions.length : 0), 0),
    );
    expect(plan.z).toBe(index.levels[0]!.elevation);
    let last = 0;
    for (const s of plan.segments.filter((_, i) => i % 4 === 0)) {
      expect(s.from).toBeCloseTo(last);
      expect(s.to).toBeGreaterThan(s.from);
      last = s.to;
    }
    expect(last).toBeCloseTo(1);
    expect(blueprintPlan(demoIndex(), walls)).toEqual(plan);
  });

  it("draws itself in about a second, fades to a faint trace, and is gone at the end", () => {
    const t = REVEAL.blueprint;
    expect(blueprintFrame(0, 8, t)).toMatchObject({ progress: 0, sheet: 0 });
    expect(blueprintFrame(t.draw / 2, 8, t).progress).toBeCloseTo(0.5);
    expect(blueprintFrame(t.draw, 8, t)).toMatchObject({ progress: 1, lines: 1, sheet: 1 });
    expect(t.line).toBe("#4f4ee0"); // thin accent-blue lines
    expect(t.lineWidth).toBeLessThanOrEqual(0.06);
    expect(blueprintFrame(t.draw + t.settle, 8, t).lines).toBeCloseTo(t.trace);
    expect(blueprintFrame(4, 8, t).lines).toBeCloseTo(t.trace);
    expect(blueprintFrame(8, 8, t)).toMatchObject({ lines: 0, sheet: 0 });
    expect(t.draw).toBeCloseTo(REVEAL.schedule.lead);
  });
});

describe("camera orbit", () => {
  const scene = buildScene(demoIndex());
  const end = cameraPose("exterior", scene.bounds, scene.index);

  it("ends exactly on the default exterior view", () => {
    const last = orbitPose(end, 1, REVEAL.camera);
    expect(last.position).toEqual(end.position);
    expect(last.target).toEqual(end.target);
  });

  it("turns slowly around the building, always looking at it, and eases into the end", () => {
    const angle = (k: number) => {
      const p = orbitPose(end, k, REVEAL.camera);
      expect(p.target).toEqual(end.target);
      return Math.atan2(p.position.y - end.target.y, p.position.x - end.target.x);
    };
    const final = angle(1);
    let previous = angle(0);
    expect(final - previous).toBeCloseTo(REVEAL.camera.sweep);
    for (let k = 0.05; k <= 1.0001; k += 0.05) {
      const a = angle(k);
      expect(a).toBeGreaterThanOrEqual(previous - 1e-9); // one direction, no swinging back
      previous = a;
    }
    expect(final - angle(0.98)).toBeLessThan(0.001); // no snap at the end
    const start = orbitPose(end, 0, REVEAL.camera).position;
    const dist = (p: typeof start) =>
      Math.hypot(p.x - end.target.x, p.y - end.target.y, p.z - end.target.z);
    expect(dist(start)).toBeGreaterThan(dist(end.position));
    expect(REVEAL.camera.sweep).toBeLessThan(Math.PI / 2);
  });
});

describe("gate", () => {
  it("hides unbuilt objects on a layer nothing renders or picks, and restores them", () => {
    const root = new Group();
    const wall = new Mesh();
    wall.userData = { elementId: "wall-1", part: "body" };
    const model = new Group();
    model.userData = revealTag("chair-1");
    const leg = new Mesh();
    model.add(leg);
    const other = new Mesh(); // ground, lights, helpers: no key
    root.add(wall, model, other);

    const tagged = new Map<string, unknown>();
    gateScene(root, (key) => key === "chair-1", tagged as never);
    expect([...tagged.keys()]).toEqual(["chair-1"]);
    expect(tagged.get("chair-1")).toBe(model); // the object the element is grown from
    expect(leg.layers.test(other.layers)).toBe(false); // hidden through its tagged ancestor
    expect(leg.layers.isEnabled(HIDDEN_LAYER)).toBe(true);
    expect(wall.layers.mask).toBe(1);
    expect(other.layers.mask).toBe(1);

    gateScene(root, (key) => key === "wall-1");
    expect(wall.layers.test(other.layers)).toBe(false);
    expect(leg.layers.mask).toBe(1); // built now
    expect(wall.userData).toEqual({ elementId: "wall-1", part: "body" }); // mapping untouched

    ungateScene(root);
    expect(wall.layers.mask).toBe(1);
    expect(other.layers.mask).toBe(1);
  });
});
