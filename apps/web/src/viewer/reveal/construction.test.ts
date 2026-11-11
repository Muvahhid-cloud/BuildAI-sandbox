import { Group, Mesh, Quaternion, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { indexModel } from "@/engine/model/model-index";
import { buildScene } from "@/engine/scene/build-scene";
import { cameraPose } from "@/engine/scene/camera-presets";
import {
  demoIndex,
  demoModelJson,
  generatedLModelJson,
  generatedModelJson,
} from "@/engine/test-fixtures";
import { parseBuildingModel } from "@/engine/model/parse";

import { REVEAL } from "../render-settings";
import { blueprintFrame, blueprintPlan } from "./blueprint";
import { orbitPose } from "./camera";
import { gateScene, HIDDEN_LAYER, plantKey, revealTag, SITE_KEY, ungateScene } from "./gate";
import {
  BUILDING_STAGES,
  type ConstructionStage,
  constructionOrder,
  scheduleConstruction,
  stageOf,
  STOREY_STAGES,
} from "./order";
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

  it("lands, shows the real mesh, then removes the pieces — all within the duration", () => {
    for (const t of timings.values()) {
      expect(t.landed).toBeCloseTo(
        t.start + t.spread + REVEAL.schedule.jitter + REVEAL.schedule.rise,
      );
      expect(t.shown).toBeCloseTo(t.landed + REVEAL.schedule.fade);
      expect(t.vanish).toBeGreaterThan(t.landed); // pieces stay until the mesh is nearly opaque
      expect(t.vanish).toBeLessThan(t.shown);
      expect(t.end).toBeLessThanOrEqual(duration + 1e-9);
    }
  });

  it("scales the duration with the model, between 6 and 9 seconds", () => {
    for (const json of [demoModelJson(), generatedModelJson(), generatedLModelJson()]) {
      const s = buildScene(parseBuildingModel(json));
      const d = buildRevealPlan(s, { seed: "x", site: { plants: new Set() } }).schedule.duration;
      expect(d).toBeGreaterThanOrEqual(6);
      expect(d).toBeLessThanOrEqual(9);
    }
    // More elements, more time (until the cap).
    const few = scheduleConstruction(plan.steps.slice(0, 20), new Map(), REVEAL.schedule);
    const many = scheduleConstruction(plan.steps.slice(0, 90), new Map(), REVEAL.schedule);
    expect(few.duration).toBeLessThan(many.duration);
    expect(few.duration).toBeGreaterThanOrEqual(REVEAL.schedule.minDuration);
  });

  it("re-assembles only the changed elements, in a short time, without the blueprint lead", () => {
    const ids = new Set(plan.steps.slice(10, 14).map((s) => s.id));
    const short = buildRevealPlan(scene, {
      seed: "model-hash:changes",
      include: (id) => ids.has(id),
      short: true,
    });
    expect(new Set(short.steps.map((s) => s.id))).toEqual(ids);
    expect(new Set(short.pieces.ranges.keys())).toEqual(ids);
    expect(short.schedule.timings.get(short.steps[0]!.id)!.start).toBe(0);
    expect(short.schedule.duration).toBeLessThanOrEqual(REVEAL.changes.duration + 1e-9);
    expect(short.schedule.duration).toBeLessThan(duration / 2);
  });
});

describe("pieces", () => {
  const scene = buildScene(generatedIndex());
  const options = {
    seed: "model-hash:build",
    site: { plants: new Set<"tree" | "bush">(["tree"]) },
  };
  const plan = buildRevealPlan(scene, options);
  const { pieces, motion } = plan;

  it("is deterministic for the same model and seed, different for another seed", () => {
    const again = buildRevealPlan(scene, options);
    expect(again.pieces.target).toEqual(pieces.target);
    expect(again.pieces.quat).toEqual(pieces.quat);
    expect(again.motion.start).toEqual(motion.start);
    expect(again.motion.time).toEqual(motion.time);
    const other = buildRevealPlan(scene, { ...options, seed: "other-hash:build" });
    expect(other.pieces.target).not.toEqual(pieces.target);
  });

  it("stays within the piece budget and gives every built element pieces", () => {
    expect(pieces.count).toBeLessThanOrEqual(REVEAL.pieces.maxPieces);
    expect(REVEAL.pieces.maxPieces).toBeLessThanOrEqual(25_000);
    expect(pieces.count).toBeGreaterThan(5_000);
    let total = 0;
    for (const step of plan.steps) {
      const r = pieces.ranges.get(step.id)!;
      expect(r.count).toBeGreaterThan(0);
      expect(r.offset).toBe(total); // pieces are stored in construction order
      total += r.count;
    }
    expect(total).toBe(pieces.count);
    expect(plan.steps.some((s) => s.id === SITE_KEY)).toBe(true);
    expect(plan.steps.some((s) => s.id.startsWith("site:tree:"))).toBe(true);
  });

  it("sizes pieces for their element (0.12–0.2 m) and lays them on its surfaces", () => {
    const q = new Quaternion();
    const normal = new Vector3();
    const along = new Vector3();
    for (const step of plan.steps) {
      const r = pieces.ranges.get(step.id)!;
      expect(r.edge).toBeGreaterThanOrEqual(0.12);
      expect(r.edge).toBeLessThanOrEqual(0.2);
      const el = scene.index.elementsById.get(step.id);
      for (let i = r.offset; i < r.offset + r.count; i++) {
        expect(pieces.scale[i * 3]!).toBeCloseTo(r.edge * REVEAL.pieces.joint, 5);
        if (el?.type !== "wall") continue;
        // On a wall every piece is square to it: its normal is horizontal (faces, ends) or
        // vertical (top, bottom), and on the faces it runs level, like a brick course.
        q.fromArray(pieces.quat, i * 4);
        normal.set(0, 0, 1).applyQuaternion(q);
        along.set(1, 0, 0).applyQuaternion(q);
        const flat = Math.abs(normal.z) < 1e-3;
        expect(flat || Math.abs(Math.abs(normal.z) - 1) < 1e-3).toBe(true);
        if (flat) expect(Math.abs(along.z)).toBeLessThan(1e-3);
      }
    }
    const big = pieces.ranges.get(plan.steps.find((s) => s.stage === "slab")!.id)!;
    const small = pieces.ranges.get(plan.steps.find((s) => s.stage === "furniture")!.id)!;
    expect(big.edge).toBeGreaterThan(small.edge);
  });

  it("keeps targets on the element (within one piece of its bounds)", () => {
    for (const step of plan.steps) {
      const parts = scene.byElement.get(step.id);
      if (!parts) continue;
      const r = pieces.ranges.get(step.id)!;
      const box = parts
        .map((d) => d.geometry.boundingBox!.clone().applyMatrix4(d.matrix))
        .reduce((a, b) => a.union(b))
        .expandByScalar(r.edge);
      for (let i = r.offset; i < r.offset + r.count; i++) {
        expect(box.containsPoint(new Vector3().fromArray(pieces.target, i * 3))).toBe(true);
      }
    }
  });

  it("starts every piece at the base of its own element, directly under its target", () => {
    for (const step of plan.steps) {
      const r = pieces.ranges.get(step.id)!;
      let lowest = Infinity;
      for (let i = r.offset; i < r.offset + r.count; i++) {
        const dx = motion.start[i * 3]! - pieces.target[i * 3]!;
        const dy = motion.start[i * 3 + 1]! - pieces.target[i * 3 + 1]!;
        expect(Math.hypot(dx, dy)).toBeLessThanOrEqual(0.15);
        expect(motion.start[i * 3 + 2]!).toBeCloseTo(r.baseZ, 5); // the element's base
        expect(motion.start[i * 3 + 2]!).toBeLessThanOrEqual(pieces.target[i * 3 + 2]! + 1e-6);
        lowest = Math.min(lowest, pieces.target[i * 3 + 2]!);
      }
      expect(r.baseZ).toBeCloseTo(lowest, 5);
    }
    expect(REVEAL.pieces.startJitter).toBeLessThanOrEqual(0.15);
  });

  it("lands the bottom of an element first, and every piece inside the element's window", () => {
    const { rise, jitter } = REVEAL.schedule;
    for (const step of plan.steps) {
      const r = pieces.ranges.get(step.id)!;
      const t = plan.schedule.timings.get(step.id)!;
      const order = Array.from({ length: r.count }, (_, k) => r.offset + k).sort(
        (a, b) => pieces.target[a * 3 + 2]! - pieces.target[b * 3 + 2]!,
      );
      let latestBelow = -Infinity;
      for (const i of order) {
        const [depart, arrive, vanish] = motion.time.subarray(i * 3, i * 3 + 3);
        expect(arrive! - depart!).toBeCloseTo(rise, 5);
        expect(depart!).toBeGreaterThanOrEqual(t.start - 1e-6);
        expect(arrive!).toBeLessThanOrEqual(t.landed + 1e-5);
        expect(vanish!).toBeCloseTo(t.vanish, 5);
        // A higher piece never lands earlier than a lower one by more than the small jitter.
        expect(arrive!).toBeGreaterThanOrEqual(latestBelow - jitter - 1e-5);
        latestBelow = Math.max(latestBelow, arrive!);
      }
      if (r.topZ - r.baseZ > 1) {
        const first = motion.time[order[0]! * 3 + 1]!;
        const last = motion.time[order[order.length - 1]! * 3 + 1]!;
        expect(last - first).toBeGreaterThan(jitter); // the top really lands later
      }
    }
  });

  it("gives landed pieces the element's library color", () => {
    const wall = plan.steps.find((s) => s.stage === "exterior_wall")!;
    const r = pieces.ranges.get(wall.id)!;
    const colors = new Set<string>();
    for (let i = r.offset; i < r.offset + r.count; i++) {
      colors.add([...pieces.color.subarray(i * 3, i * 3 + 3)].map((c) => c.toFixed(3)).join());
    }
    expect(colors.size).toBeGreaterThanOrEqual(2); // facade finish and interior plaster
    for (const c of pieces.color) expect(c >= 0 && c <= 1).toBe(true);
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

    const models = new Set<string>();
    gateScene(root, (key) => key === "chair-1", models);
    expect(models).toEqual(new Set(["chair-1"]));
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
