"use client";

import { useEffect, useMemo } from "react";
import { Box3Helper, Color } from "three";

import { MODEL_ROOT_ROTATION } from "@/engine/math/coords";
import { elementBounds, type SceneGraph } from "@/engine/scene/build-scene";
import { visibilityMap } from "@/engine/scene/visibility";
import { useLayerStore } from "@/stores/layer-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";

import { ElementMesh } from "./ElementMesh";

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

  const modes = useMemo(
    () => visibilityMap(scene.index, { levelFilter, layers, showRoof, showExteriorWalls }),
    [scene.index, levelFilter, layers, showRoof, showExteriorWalls],
  );

  return (
    <group name="model-root" rotation={MODEL_ROOT_ROTATION}>
      {scene.descriptors.map((d) => (
        <ElementMesh
          key={d.key}
          descriptor={d}
          mode={modes.get(d.elementId) ?? "visible"}
          selected={d.elementId === selectedId}
        />
      ))}
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
