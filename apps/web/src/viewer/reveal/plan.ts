// What the build reveal assembles for a scene: the items (elements, site, plants) in
// construction order, their pieces and the schedule. No GPU objects; the only geometry created
// here (site mesh, plant stand-ins) is returned to be disposed with the effect.
import { type BufferGeometry, Matrix4 } from "three";

import { materialPreset, SITE_GROUND_MATERIAL } from "@/engine/materials/library";
import { parseMaterialKey } from "@/engine/materials/material-cache";
import type { SceneGraph } from "@/engine/scene/build-scene";
import { buildSiteMesh, planSite } from "@/engine/scene/site";

import { REVEAL } from "../render-settings";
import { plantKey, SITE_KEY } from "./gate";
import { plantProxyGeometry } from "./gpu";
import {
  type ConstructionSchedule,
  type ConstructionStep,
  constructionOrder,
  scheduleConstruction,
  stageOf,
} from "./order";
import {
  animatePieces,
  type PieceItem,
  type PieceMotion,
  pieceExtents,
  type PieceTargets,
  samplePieces,
} from "./pieces";

export interface RevealPlanOptions {
  /** PRNG key: the version's model hash. */
  seed: string;
  /** Only these elements take part (default: all). */
  include?: (elementId: string) => boolean;
  /** Add the site (paving, fence) and the plants of these kinds (those the viewer draws). */
  site?: { plants: ReadonlySet<"tree" | "bush"> } | null;
  /** "changes": no blueprint lead, a short fixed length. */
  short?: boolean;
}

export interface RevealPlan {
  steps: ConstructionStep[];
  pieces: PieceTargets;
  motion: PieceMotion;
  schedule: ConstructionSchedule;
  /** Geometry made for sampling only; dispose with the effect. */
  owned: BufferGeometry[];
}

/** sRGB hex a material key is drawn in without textures (its library color or display color). */
export function materialHex(key: string): string {
  const { id, color } = parseMaterialKey(key);
  return color ?? materialPreset(id).color;
}

export function buildRevealPlan(scene: SceneGraph, options: RevealPlanOptions): RevealPlan {
  const owned: BufferGeometry[] = [];
  const items = new Map<string, PieceItem>();
  for (const [id, parts] of scene.byElement) {
    if (parts.length === 0 || (options.include && !options.include(id))) continue;
    const el = scene.index.elementsById.get(id);
    items.set(id, {
      key: id,
      density: el ? REVEAL.stageDensity[stageOf(el)] : 1,
      parts: parts.map((d) => ({
        geometry: d.geometry,
        matrix: d.matrix,
        colors: d.materials.map(materialHex),
      })),
    });
  }

  const siteKeys: string[] = [];
  if (options.site) {
    const plan = planSite(scene.index, scene.bounds);
    const built = buildSiteMesh(plan);
    owned.push(built.geometry);
    if ((built.geometry.getAttribute("position")?.count ?? 0) > 0) {
      items.set(SITE_KEY, {
        key: SITE_KEY,
        density: REVEAL.stageDensity.site,
        parts: [
          {
            geometry: built.geometry,
            matrix: new Matrix4(),
            colors: built.materials.map(materialHex),
          },
        ],
      });
      siteKeys.push(SITE_KEY);
    }
    const proxy = plantProxyGeometry();
    owned.push(proxy);
    const green = [materialHex(SITE_GROUND_MATERIAL)];
    for (const p of plan.plants) {
      if (!options.site.plants.has(p.kind)) continue;
      const key = plantKey(p.kind, p.slot);
      // A tree's crown starts above its trunk; a bush sits on the ground.
      const foot = p.kind === "tree" ? 0.3 * p.height : 0;
      const spread = p.kind === "tree" ? 0.6 * p.height : 1.1 * p.height;
      items.set(key, {
        key,
        density: REVEAL.stageDensity.site,
        parts: [
          {
            geometry: proxy,
            matrix: new Matrix4()
              .makeTranslation(p.x, p.y, foot)
              .multiply(new Matrix4().makeScale(spread, spread, p.height - foot)),
            colors: green,
          },
        ],
      });
      siteKeys.push(key);
    }
  }

  const steps = constructionOrder(scene.index, siteKeys).filter((s) => items.has(s.id));
  const pieces = samplePieces(
    steps.map((s) => items.get(s.id)!),
    options.seed,
    REVEAL.pieces,
  );
  const built = steps.filter((s) => pieces.ranges.has(s.id));
  const schedule = scheduleConstruction(
    built,
    pieceExtents(pieces),
    options.short
      ? {
          ...REVEAL.schedule,
          lead: 0,
          minDuration: REVEAL.changes.duration,
          maxDuration: REVEAL.changes.duration,
          secondsPerElement: 0,
        }
      : REVEAL.schedule,
  );
  const motion = animatePieces(pieces, schedule, {
    rise: REVEAL.schedule.rise,
    jitter: REVEAL.schedule.jitter,
    startJitter: REVEAL.pieces.startJitter,
  });
  return { steps: built, pieces, motion, schedule, owned };
}
