"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import { Color, Mesh, PlaneGeometry, ShaderMaterial } from "three";

import { prefersReducedMotion } from "@/stores/reveal-store";

import { REVEAL } from "../render-settings";

/** WebGL is needed for the grid; without it (or in tests) only the stage text is shown. */
function canUseWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export interface WaitingBlueprintProps {
  /** The backend's current stage, in the product's own words (AI_STAGES label). */
  label: string;
  /** Index of that stage: a change is one brighter pass of the scanning line. */
  stageIndex: number;
  /** Shown under the label (never a percentage: no invented progress). */
  hint?: string;
}

/**
 * The waiting phase: a calm drafting table in the canvas area while the design is generated —
 * a faint ground grid and a slow scanning line — with the backend's real stage label. Nothing
 * here shows progress the backend did not report. With reduced motion or without WebGL it is a
 * quiet panel with the same text.
 */
export function WaitingBlueprint({ label, stageIndex, hint }: WaitingBlueprintProps) {
  // Decided once on mount (this component only ever renders in the browser).
  const [animated] = useState(
    () => typeof document !== "undefined" && !prefersReducedMotion() && canUseWebGL(),
  );
  return (
    <div
      data-theme="light"
      className="relative flex h-full w-full items-end justify-center overflow-hidden text-fg"
      style={{ background: REVEAL.waiting.background }}
    >
      {animated && (
        <div className="absolute inset-0" aria-hidden>
          <Canvas
            dpr={[1, 2]}
            gl={{ antialias: true, alpha: false }}
            camera={{ position: [0, 5.2, 15], fov: 38, near: 0.1, far: 120 }}
            onCreated={({ gl, camera }) => {
              gl.setClearColor(REVEAL.waiting.background);
              camera.lookAt(0, 0, 0);
            }}
          >
            <Grid stageIndex={stageIndex} />
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

const VERTEX = /* glsl */ `
  varying vec2 vPlan;
  void main() {
    vPlan = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const FRAGMENT = /* glsl */ `
  uniform vec3 uLine;
  uniform float uCell;
  uniform float uGrid;
  uniform float uReach;
  uniform float uScan;      // position of the scanning line across the grid, -1..1
  uniform float uScanOpacity;
  uniform float uPulse;
  varying vec2 vPlan;
  void main() {
    vec2 cell = vPlan / uCell;
    vec2 w = max(fwidth(cell), vec2(1e-5));
    vec2 g = abs(fract(cell - 0.5) - 0.5) / w;
    float minor = 1.0 - min(min(g.x, g.y), 1.0);
    vec2 g5 = abs(fract(cell / 5.0 - 0.5) - 0.5) / (w / 5.0);
    float major = 1.0 - min(min(g5.x, g5.y), 1.0);
    float fade = 1.0 - smoothstep(0.35, 1.0, length(vPlan) / uReach);
    // The scanning line travels across the grid; lines glow softly in its wake.
    float d = vPlan.y - uScan * uReach;
    float line = 1.0 - smoothstep(0.0, 0.05 + fwidth(vPlan.y) * 1.5, abs(d));
    float wake = exp(-max(d, 0.0) * 0.3) * step(0.0, d);
    float grid = max(minor * 0.55, major);
    float a = grid * uGrid * (1.0 + wake * (1.5 + 3.0 * uPulse))
      + line * uScanOpacity * (1.0 + uPulse)
      + wake * 0.07;
    gl_FragColor = vec4(uLine, clamp(a * fade, 0.0, 1.0));
    #include <colorspace_fragment>
  }
`;

function Grid({ stageIndex }: { stageIndex: number }) {
  const w = REVEAL.waiting;
  const fx = useMemo(() => createGrid(), []);
  useEffect(() => () => fx.dispose(), [fx]);

  // A real stage change: one brighter pass, then it decays.
  const pulse = useRef(0);
  const seen = useRef(stageIndex);
  useEffect(() => {
    if (seen.current !== stageIndex) {
      seen.current = stageIndex;
      pulse.current = w.pulse;
    }
  }, [stageIndex, w]);

  const time = useRef(0);
  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.1);
    time.current += dt;
    pulse.current = Math.max(0, pulse.current - w.pulseDecay * pulse.current * dt - 0.02 * dt);
    // From the far edge towards the viewer, then again.
    fx.update(0.75 - 1.5 * ((time.current / w.scanPeriod) % 1), pulse.current);
  });

  return <primitive object={fx.mesh} />;
}

/** The ground grid: one quad with a small shader; created and disposed by `Grid`. */
function createGrid() {
  const w = REVEAL.waiting;
  const uniforms = {
    uLine: { value: new Color(w.line) },
    uCell: { value: w.grid },
    uGrid: { value: w.gridOpacity },
    uReach: { value: w.reach },
    uScan: { value: 0.75 },
    uScanOpacity: { value: w.scanOpacity },
    uPulse: { value: 0 },
  };
  const mesh = new Mesh(
    new PlaneGeometry(w.reach * 2, w.reach * 2),
    new ShaderMaterial({
      vertexShader: VERTEX,
      fragmentShader: FRAGMENT,
      transparent: true,
      depthWrite: false,
      toneMapped: false,
      uniforms,
    }),
  );
  mesh.rotation.x = -Math.PI / 2; // the grid lies on the ground (a world Y-up canvas of its own)
  mesh.raycast = () => undefined;
  return {
    mesh,
    update: (scan: number, pulse: number) => {
      uniforms.uScan.value = scan;
      uniforms.uPulse.value = pulse;
    },
    dispose: () => {
      mesh.geometry.dispose();
      mesh.material.dispose();
    },
  };
}
