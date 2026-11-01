"use client";

import { Canvas } from "@react-three/fiber";
import { ACESFilmicToneMapping } from "three";

import type { SceneGraph } from "@/engine/scene/build-scene";
import { useSelectionStore } from "@/stores/selection-store";

import { CameraRig } from "./CameraRig";
import { MaterialTextures } from "./MaterialTextures";
import { ModelRoot } from "./ModelRoot";
import { PostEffects } from "./PostEffects";
import { RENDER } from "./render-settings";
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
      gl={{
        antialias: true,
        preserveDrawingBuffer: false,
      }}
      onCreated={({ gl }) => {
        // ACES Filmic (also applied by the post-processing ToneMapping effect when enabled).
        gl.toneMapping = ACESFilmicToneMapping;
        gl.toneMappingExposure = RENDER.exposure;
      }}
      onPointerMissed={(e) => {
        if (e.type === "click") select(null);
      }}
      aria-label="3D building viewer"
    >
      <color attach="background" args={[RENDER.sky.horizon]} />
      <MaterialTextures />
      <SceneEnvironment bounds={scene.bounds} />
      <ModelRoot scene={scene} />
      <CameraRig scene={scene} />
      <SectionPlane />
      <PostEffects />
      <RenderOnResize />
    </Canvas>
  );
}
