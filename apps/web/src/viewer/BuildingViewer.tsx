"use client";

import { Canvas } from "@react-three/fiber";
import { ACESFilmicToneMapping } from "three";

import type { SceneGraph } from "@/engine/scene/build-scene";
import { useSelectionStore } from "@/stores/selection-store";

import { CameraRig } from "./CameraRig";
import { MaterialTextures } from "./MaterialTextures";
import { ModelRoot } from "./ModelRoot";
import { PostEffects } from "./PostEffects";
import { RENDER, REVEAL } from "./render-settings";
import { RenderOnResize } from "./RenderOnResize";
import { RevealLayer } from "./reveal/RevealLayer";
import { waitingBounds } from "./reveal/waiting";
import { SceneEnvironment } from "./SceneEnvironment";
import { SectionPlane } from "./SectionPlane";
import { SiteLayer } from "./SiteLayer";

/** What the camera frames while there is no model yet (a design is being created). */
const WAITING_BOUNDS = waitingBounds(REVEAL.waiting.bounds);

/**
 * Interactive 3D view of a built SceneGraph. Renders on demand (no idle GPU work). Without a
 * scene it shows the empty site: the same canvas a design is then created in (§25).
 */
export function BuildingViewer({ scene }: { scene: SceneGraph | null }) {
  const select = useSelectionStore((s) => s.select);
  const bounds = scene?.bounds ?? WAITING_BOUNDS;
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
      <SceneEnvironment bounds={bounds} />
      {scene && <ModelRoot scene={scene} />}
      {scene && <SiteLayer scene={scene} />}
      <CameraRig bounds={bounds} index={scene?.index ?? null} />
      <SectionPlane />
      <RevealLayer scene={scene} bounds={bounds} />
      <PostEffects />
      <RenderOnResize />
    </Canvas>
  );
}
