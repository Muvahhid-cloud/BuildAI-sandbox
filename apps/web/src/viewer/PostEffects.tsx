"use client";

import { useThree } from "@react-three/fiber";
import { EffectComposer, N8AO, SMAA, ToneMapping } from "@react-three/postprocessing";
import { ToneMappingMode } from "postprocessing";
import { useEffect } from "react";

import { useViewerStore } from "@/stores/viewer-store";

import { RENDER } from "./render-settings";

/**
 * Optional post-processing ("Effects" toggle): N8AO ambient occlusion, SMAA anti-aliasing and
 * ACES Filmic tone mapping (the composer disables the renderer's own tone mapping while it is
 * mounted). Off = the plain renderer with MSAA and the same tone mapping.
 */
export function PostEffects() {
  const effects = useViewerStore((s) => s.effects);
  const invalidate = useThree((s) => s.invalidate);
  // frameloop="demand": switching the composer on/off must draw a new frame.
  useEffect(() => {
    invalidate();
  }, [effects, invalidate]);
  if (!effects) return null;
  return (
    <EffectComposer multisampling={0}>
      <N8AO
        halfRes
        quality="medium"
        aoRadius={RENDER.ao.radius}
        distanceFalloff={RENDER.ao.distanceFalloff}
        intensity={RENDER.ao.intensity}
      />
      <SMAA />
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
    </EffectComposer>
  );
}
