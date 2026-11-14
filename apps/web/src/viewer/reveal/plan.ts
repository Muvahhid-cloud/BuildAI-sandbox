// What the construction builds for a scene: the items (elements, site, plants) in construction
// order, when each one grows, and the pieces at their growing fronts. No GPU objects; the only
// geometry created here (the site mesh, for sampling) is returned to be disposed with the effect.
import { Box3, type BufferGeometry, Matrix4 } from "three";

import { furnitureSource } from "@/engine/builders/furniture/assets";
import type { SceneGraph } from "@/engine/scene/build-scene";
import { buildSiteMesh, planSite } from "@/engine/scene/site";

import { REVEAL } from "../render-settings";
import { plantKey, SITE_KEY } from "./gate";
import {
  type ConstructionSchedule,
  type ConstructionStep,
  constructionOrder,
  scheduleConstruction,
  stageOf,
  type StepExtent,
} from "./order";
import { animatePieces, type PieceItem, type PieceTargets, samplePieces } from "./pieces";

export interface RevealPlanOptions {
  /** PRNG key: the version's model hash. */
  seed: string;
  /** Only these elements take part (default: all). */
  include?: (elementId: string) => boolean;
  /** Add the site (paving, fence) and the plants of these kinds (those the viewer draws). */
  site?: { plants: ReadonlySet<"tree" | "bush"> } | null;
  /** Furniture drawn by a glTF model of this file is grown from that model (no pieces). */
  modelServed?: (file: string) => boolean;
  /** "changes": no blueprint lead, a short fixed length. */
  short?: boolean;
}

export interface RevealPlan {
  steps: ConstructionStep[];
  pieces: PieceTargets;
  /** Per piece: the moment its element's front reaches it. */
  front: Float32Array;
  schedule: ConstructionSchedule;
  /** Keys grown from an object the viewer draws itself (glTF models, site mesh, plants). */
  objects: ReadonlySet<string>;
  /** Geometry made for sampling only; dispose with the effect. */
  owned: BufferGeometry[];
}

/** Ground level of the site in model space (SceneEnvironment GROUND_Y). */
const SITE_Z = -0.05;

function extentOf(parts: readonly { geometry: BufferGeometry; matrix: Matrix4 }[]): StepExtent {
  const box = new Box3();
  for (const p of parts) {
    if (!p.geometry.boundingBox) p.geometry.computeBoundingBox();
    if (p.geometry.boundingBox) box.union(p.geometry.boundingBox.clone().applyMatrix4(p.matrix));
  }
  return box.isEmpty() ? { baseZ: 0, topZ: 0 } : { baseZ: box.min.z, topZ: box.max.z };
}

export function buildRevealPlan(scene: SceneGraph, options: RevealPlanOptions): RevealPlan {
  const owned: BufferGeometry[] = [];
  const items = new Map<string, PieceItem>();
  const extents = new Map<string, StepExtent>();
  const objects = new Set<string>();
  const keys = new Set<string>();

  for (const [id, parts] of scene.byElement) {
    if (parts.length === 0 || (options.include && !options.include(id))) continue;
    const el = scene.index.elementsById.get(id);
    keys.add(id);
    extents.set(id, extentOf(parts));
    if (el?.type === "furniture" && options.modelServed) {
      const source = furnitureSource(el);
      if (source.type === "model" && options.modelServed(source.model.file)) {
        objects.add(id); // drawn by its model: pieces on the placeholder box would float
        continue;
      }
    }
    items.set(id, {
      key: id,
      density: el ? REVEAL.stageDensity[stageOf(el)] : 1,
      flatTops: el?.type === "stair",
      parts: parts.map((d) => ({ geometry: d.geometry, matrix: d.matrix, materials: d.materials })),
    });
  }

  const siteKeys: string[] = [];
  if (options.site) {
    const plan = planSite(scene.index, scene.bounds);
    const built = buildSiteMesh(plan);
    owned.push(built.geometry);
    if ((built.geometry.getAttribute("position")?.count ?? 0) > 0) {
      const part = { geometry: built.geometry, matrix: new Matrix4(), materials: built.materials };
      items.set(SITE_KEY, { key: SITE_KEY, density: REVEAL.stageDensity.site, parts: [part] });
      extents.set(SITE_KEY, extentOf([part]));
      objects.add(SITE_KEY);
      keys.add(SITE_KEY);
      siteKeys.push(SITE_KEY);
    }
    for (const p of plan.plants) {
      if (!options.site.plants.has(p.kind)) continue;
      const key = plantKey(p.kind, p.slot);
      extents.set(key, { baseZ: SITE_Z, topZ: SITE_Z + p.height });
      objects.add(key);
      keys.add(key);
      siteKeys.push(key);
    }
  }

  const steps = constructionOrder(scene.index, siteKeys).filter((s) => keys.has(s.id));
  const pieces = samplePieces(
    steps.flatMap((s) => items.get(s.id) ?? []),
    options.seed,
    REVEAL.pieces,
  );
  const timing = {
    ...REVEAL.schedule,
    settle: REVEAL.pieces.settle + REVEAL.pieces.early,
    absorb: REVEAL.pieces.absorb,
  };
  const schedule = scheduleConstruction(
    steps,
    extents,
    options.short
      ? {
          ...timing,
          lead: 0,
          minDuration: REVEAL.changes.duration,
          maxDuration: REVEAL.changes.duration,
          secondsPerElement: 0,
        }
      : timing,
  );
  return { steps, pieces, front: animatePieces(pieces, schedule), schedule, objects, owned };
}
