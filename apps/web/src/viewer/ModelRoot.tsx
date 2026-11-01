"use client";

import { useEffect, useMemo } from "react";
import { Box3Helper, Color } from "three";

import type { RenderDescriptor } from "@/engine/builders/types";
import { furnitureSource } from "@/engine/builders/furniture/assets";
import { fitToDimensions, type ModelEntry } from "@/engine/materials/models";

import { MODEL_ROOT_ROTATION } from "@/engine/math/coords";
import { elementBounds, type SceneGraph } from "@/engine/scene/build-scene";
import { visibilityMap } from "@/engine/scene/visibility";
import { useLayerStore } from "@/stores/layer-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";

import { ElementMesh } from "./ElementMesh";
import { ModelInstance } from "./ModelInstance";
import { useServedAssets } from "./served-assets";

const SELECTION_COLOR = new Color("#2f6fed");

/**
 * The single model -> world boundary: everything below this group is in BuildingModel
 * coordinates (Z-up, meters). See engine/math/coords.ts.
 */
export function ModelRoot({ scene }: { scene: SceneGraph }) {
  const selectedId = useSelectionStore((s) => s.selectedId);
  const levelFilter = useViewerStore((s) => s.levelFilter);
  const showRoof = useViewerStore((s) => s.showRoof);
  const showExteriorWalls = useViewerStore((s) => s.showExteriorWalls);
  const layers = useLayerStore((s) => s.visible);
  const served = useServedAssets();

  // Furniture drawn by a CC0 model (V2): only when the model file is actually served.
  const models = useMemo(() => {
    const out = new Map<string, ModelEntry>();
    if (!served) return out;
    for (const el of scene.index.elementsById.values()) {
      if (el.type !== "furniture") continue;
      const src = furnitureSource(el);
      if (src.type === "model" && served.has(src.model.file)) out.set(el.id, src.model);
    }
    return out;
  }, [scene.index, served]);

  const modes = useMemo(
    () => visibilityMap(scene.index, { levelFilter, layers, showRoof, showExteriorWalls }),
    [scene.index, levelFilter, layers, showRoof, showExteriorWalls],
  );

  return (
    <group name="model-root" rotation={MODEL_ROOT_ROTATION}>
      {scene.descriptors.map((d) => {
        const mode = modes.get(d.elementId) ?? "visible";
        const selected = d.elementId === selectedId;
        const model = d.part === "body" && mode === "visible" ? models.get(d.elementId) : undefined;
        if (!model) {
          return <ElementMesh key={d.key} descriptor={d} mode={mode} selected={selected} />;
        }
        return (
          <FurnitureModel
            key={d.key}
            descriptor={d}
            model={model}
            selected={selected}
            scene={scene}
          />
        );
      })}
      {selectedId && modes.get(selectedId) === "visible" && (
        <SelectionBox scene={scene} elementId={selectedId} />
      )}
    </group>
  );
}

/** Bounding-box outline around the selected element (model space). */
function SelectionBox({ scene, elementId }: { scene: SceneGraph; elementId: string }) {
  const helper = useMemo(() => {
    const box = elementBounds(scene, elementId);
    if (!box) return null;
    box.expandByScalar(0.02);
    const h = new Box3Helper(box, SELECTION_COLOR);
    h.raycast = () => undefined;
    return h;
  }, [scene, elementId]);
  useEffect(
    () => () => {
      helper?.geometry.dispose();
      (helper?.material as { dispose?: () => void } | undefined)?.dispose?.();
    },
    [helper],
  );
  return helper ? <primitive object={helper} /> : null;
}

/**
 * Furniture drawn by a glTF model fitted to the element's width x depth x height. The placeholder
 * stays as an invisible pick proxy (selection, outline) and is shown while the model loads or if
 * it fails.
 */
function FurnitureModel({
  descriptor: d,
  model,
  selected,
  scene,
}: {
  descriptor: RenderDescriptor;
  model: ModelEntry;
  selected: boolean;
  scene: SceneGraph;
}) {
  const matrix = useMemo(() => {
    const el = scene.index.elementsById.get(d.elementId);
    const dims = el?.type === "furniture" ? el.dimensions : { width: 1, depth: 1, height: 1 };
    return d.matrix.clone().multiply(fitToDimensions(model, dims));
  }, [d, model, scene.index]);
  return (
    <>
      <ElementMesh descriptor={d} mode="visible" selected={selected} proxy />
      <ModelInstance
        model={model}
        matrix={matrix}
        fallback={<ElementMesh descriptor={d} mode="visible" selected={selected} />}
      />
    </>
  );
}
