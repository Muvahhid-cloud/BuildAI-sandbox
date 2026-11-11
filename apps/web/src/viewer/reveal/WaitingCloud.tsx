"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import type { PerspectiveCamera } from "three";

import { MODEL_ROOT_ROTATION } from "@/engine/math/coords";
import { prefersReducedMotion } from "@/stores/reveal-store";

import { REVEAL } from "../render-settings";
import { createRevealParticles } from "./particles";
import { cloudSeeds } from "./sampling";

/** WebGL is needed for the cloud; without it (or in tests) only the stage text is shown. */
function canUseWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export interface WaitingCloudProps {
  /** The backend's current stage, in the product's own words (AI_STAGES label). */
  label: string;
  /** Index of that stage and how many there are: more stages done, denser cloud. */
  stageIndex: number;
  stageCount: number;
  /** Shown under the label (e.g. "Step 3 of 6" is not used: no invented progress). */
  hint?: string;
}

/**
 * The waiting phase: a glowing particle cloud in the canvas area while the design is generated.
 * It reacts only to real stage changes (a burst, more density) and shows the real stage label.
 * With reduced motion or without WebGL it is a quiet panel with the same text.
 */
export function WaitingCloud({ label, stageIndex, stageCount, hint }: WaitingCloudProps) {
  // Decided once on mount (this component only ever renders in the browser).
  const [animated] = useState(
    () => typeof document !== "undefined" && !prefersReducedMotion() && canUseWebGL(),
  );
  return (
    <div
      data-theme="dark"
      className="relative flex h-full w-full items-end justify-center overflow-hidden text-fg"
      style={{ background: REVEAL.veilColor }}
    >
      {animated && (
        <div className="absolute inset-0" aria-hidden>
          <Canvas
            dpr={[1, 2]}
            gl={{ antialias: false, alpha: false }}
            camera={{ position: [0, 3.2, 13], fov: 40, near: 0.1, far: 100 }}
            onCreated={({ gl }) => gl.setClearColor(REVEAL.veilColor)}
          >
            <Cloud stageIndex={stageIndex} stageCount={stageCount} />
          </Canvas>
        </div>
      )}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none relative mb-[12%] flex flex-col items-center gap-1 px-6 text-center"
      >
        <span className="text-2xs font-semibold uppercase tracking-[0.2em] text-fg-subtle">
          Designing your building
        </span>
        <span key={label} className="animate-rise-in text-lg font-semibold tracking-tight">
          {label}…
        </span>
        {hint && <span className="text-xs text-fg-subtle">{hint}</span>}
      </div>
    </div>
  );
}

function Cloud({ stageIndex, stageCount }: { stageIndex: number; stageCount: number }) {
  const fx = useMemo(() => {
    const seeds = cloudSeeds(REVEAL.particleCount, "waiting-cloud");
    const particles = createRevealParticles(new Float32Array(REVEAL.particleCount * 3), seeds);
    particles.setup({ radius: 5.2, size: REVEAL.pointSize * 1.15 });
    return particles;
  }, []);
  useEffect(() => () => fx.dispose(), [fx]);

  // A real stage change: one burst, then it decays.
  const burst = useRef(0);
  const seen = useRef(stageIndex);
  useEffect(() => {
    if (seen.current !== stageIndex) {
      seen.current = stageIndex;
      burst.current = REVEAL.burst;
    }
  }, [stageIndex]);

  const density =
    REVEAL.minDensity +
    (1 - REVEAL.minDensity) * Math.min(1, (stageIndex + 1) / Math.max(stageCount, 1));
  const shown = useRef(REVEAL.minDensity);

  const time = useRef(0);
  useFrame((state, delta) => {
    const dt = Math.min(delta, 0.1);
    burst.current = Math.max(0, burst.current * (1 - REVEAL.burstDecay * dt) - 0.05 * dt);
    shown.current += (density - shown.current) * Math.min(1, dt * 2.5);
    time.current += dt;
    const fov = ((state.camera as PerspectiveCamera).fov * Math.PI) / 180;
    fx.update({
      time: time.current,
      burst: burst.current,
      density: shown.current,
      scale: (state.size.height * state.viewport.dpr) / (2 * Math.tan(fov / 2)),
    });
  });

  return (
    <group rotation={MODEL_ROOT_ROTATION}>
      <primitive object={fx.points} />
    </group>
  );
}
