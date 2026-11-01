"use client";

import { useEffect, useMemo } from "react";
import { Matrix4 } from "three";

import { materialCache } from "@/engine/materials/material-cache";
import { fitToHeight, type ModelEntry, modelsFor } from "@/engine/materials/models";
import { MODEL_ROOT_ROTATION } from "@/engine/math/coords";
import type { SceneGraph } from "@/engine/scene/build-scene";
import { buildSiteMesh, planSite, type SitePlant } from "@/engine/scene/site";
import { useViewerStore } from "@/stores/viewer-store";

import { ModelInstance } from "./ModelInstance";
import { useServedAssets } from "./served-assets";

const NO_RAYCAST = () => undefined;

/**
 * The site around the building (V2, "Site" toggle): paving to the entrance and the garage, a low
 * street fence, trees and shrubs. Environment only — derived from the model by the pure
 * `planSite`, never stored in it, never pickable. Model space (Z-up) like the building, under
 * the same coords.ts root rotation.
 */
export function SiteLayer({ scene }: { scene: SceneGraph }) {
  const show = useViewerStore((s) => s.showSite);
  const sectioned = useViewerStore((s) => s.section.enabled);
  const served = useServedAssets();
  const plan = useMemo(() => planSite(scene.index, scene.bounds), [scene.index, scene.bounds]);
  const mesh = useMemo(() => buildSiteMesh(plan), [plan]);
  useEffect(() => () => mesh.geometry.dispose(), [mesh]);
  const materials = useMemo(() => mesh.materials.map((id) => materialCache.get(id)), [mesh]);

  const plants = useMemo(() => {
    if (!served) return [];
    const pick = (kind: SitePlant["kind"]) => modelsFor(kind).filter((m) => served.has(m.file));
    const trees = pick("tree");
    const bushes = pick("bush");
    const out: { key: string; model: ModelEntry; matrix: Matrix4 }[] = [];
    for (const p of plan.plants) {
      const options = p.kind === "tree" ? trees : bushes;
      if (!options.length) continue;
      const model = options[p.slot % options.length];
      const matrix = new Matrix4()
        .makeTranslation(p.x, p.y, -0.05)
        .multiply(fitToHeight(model, p.height, p.rotation));
      out.push({ key: `${p.kind}:${p.slot}`, model, matrix });
    }
    return out;
  }, [plan, served]);

  if (!show) return null;
  return (
    <group name="site-root" rotation={MODEL_ROOT_ROTATION}>
      <mesh
        geometry={mesh.geometry}
        material={materials}
        receiveShadow
        castShadow={!sectioned}
        raycast={NO_RAYCAST}
        dispose={null}
      />
      {plants.map((p) => (
        <ModelInstance key={p.key} model={p.model} matrix={p.matrix} />
      ))}
    </group>
  );
}
