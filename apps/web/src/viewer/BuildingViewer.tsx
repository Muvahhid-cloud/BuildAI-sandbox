"use client";

import { Canvas } from "@react-three/fiber";

import type { SceneGraph } from "@/engine/scene/build-scene";
import { useSelectionStore } from "@/stores/selection-store";

import { CameraRig } from "./CameraRig";
import { ModelRoot } from "./ModelRoot";
import { RenderOnResize } from "./RenderOnResize";
import { SceneEnvironment } from "./SceneEnvironment";
import { SectionPlane } from "./SectionPlane";

/** Interactive 3D view of a built SceneGraph. Renders on demand (no idle GPU work). */
export function BuildingViewer({ scene }: { scene: SceneGraph }) {
  const select = useSelectionStore((s) => s.select);
  return (
    <Canvas
      shadows="percentage"
      frameloop="demand"
      dpr={[1, 2]}
      gl={{ antialias: true, preserveDrawingBuffer: false }}
      onPointerMissed={(e) => {
        if (e.type === "click") select(null);
      }}
      aria-label="3D building viewer"
    >
      <color attach="background" args={["#e8edf1"]} />
      <SceneEnvironment bounds={scene.bounds} />
      <ModelRoot scene={scene} />
      <CameraRig scene={scene} />
      <SectionPlane />
      <RenderOnResize />
    </Canvas>
  );
}
