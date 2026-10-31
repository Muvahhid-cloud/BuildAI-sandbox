"use client";

import type { ThreeEvent } from "@react-three/fiber";
import { memo, useMemo } from "react";
import { Mesh } from "three";

import type { RenderDescriptor } from "@/engine/builders/types";
import { materialCache } from "@/engine/materials/material-cache";
import { elementUserData, resolveElementId } from "@/engine/scene/selection";
import type { VisibilityMode } from "@/engine/scene/visibility";
import { useSelectionStore } from "@/stores/selection-store";

// Hidden and ghosted meshes must not be pickable.
const NO_RAYCAST = () => undefined;

interface Props {
  descriptor: RenderDescriptor;
  mode: VisibilityMode;
  selected: boolean;
}

/**
 * One mesh per render descriptor. Geometry and materials are shared/cached, so a re-render
 * only swaps references. Memoized: it re-renders only when its visibility or selection changes.
 */
export const ElementMesh = memo(function ElementMesh({ descriptor: d, mode, selected }: Props) {
  const select = useSelectionStore((s) => s.select);
  const variant = mode === "ghost" ? "ghost" : selected ? "selected" : "default";
  const material = useMemo(() => {
    const list = d.materials.map((id) => materialCache.get(id, variant));
    return list.length === 1 ? list[0] : list;
  }, [d.materials, variant]);
  const userData = useMemo(() => elementUserData(d.elementId, d.part), [d.elementId, d.part]);
  const pickable = mode === "visible";

  return (
    <mesh
      geometry={d.geometry}
      material={material}
      matrix={d.matrix}
      matrixAutoUpdate={false}
      visible={mode !== "hidden"}
      castShadow={d.castShadow && pickable}
      receiveShadow={pickable}
      renderOrder={d.part === "glass" ? 1 : 0}
      userData={userData}
      dispose={null /* geometry/materials are owned by the scene graph and material cache */}
      raycast={pickable ? Mesh.prototype.raycast : NO_RAYCAST}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        if (e.delta > 4) return; // a drag (orbit/pan), not a click
        e.stopPropagation();
        const id = resolveElementId(e.object);
        if (id) select(id);
      }}
      onPointerOver={(e: ThreeEvent<PointerEvent>) => {
        e.stopPropagation();
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        document.body.style.cursor = "";
      }}
    />
  );
});
