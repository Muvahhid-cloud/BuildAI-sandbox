"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Box3 } from "three";

import { MODEL_ROOT_ROTATION } from "@/engine/math/coords";
import { prefersReducedMotion, useRevealStore } from "@/stores/reveal-store";

import { REVEAL } from "../render-settings";
import { createWaitingSheet } from "./gpu";

/** Height of the site ground in model space (SceneEnvironment GROUND_Y) plus a hair. */
const GROUND_Z = -0.05 + 0.01;

/**
 * While the backend works, in the viewer's own canvas: a pale drafting sheet on the ground
 * with a subtle grid, a slow scanning line and — once the AI has stated the floor area — the
 * outline of the plot. A real stage change is one brighter pass of the line; nothing here
 * shows progress the backend did not report. It fades in when waiting starts and fades out
 * under the blueprint when the model arrives. With reduced motion the sheet is still.
 */
export function WaitingGround({ bounds }: { bounds: Box3 }) {
  const gathering = useRevealStore((s) => s.phase === "gathering");
  // Stays mounted while it fades out under the arriving model.
  const [mounted, setMounted] = useState(gathering);
  if (gathering && !mounted) setMounted(true);
  if (!mounted) return null;
  return <Sheet bounds={bounds} onGone={() => setMounted(false)} />;
}

function Sheet({ bounds, onGone }: { bounds: Box3; onGone: () => void }) {
  const w = REVEAL.waiting;
  const invalidate = useThree((s) => s.invalidate);
  const still = useMemo(() => prefersReducedMotion(), []);
  const fx = useMemo(
    () =>
      createWaitingSheet(
        [(bounds.min.x + bounds.max.x) / 2, (bounds.min.y + bounds.max.y) / 2],
        GROUND_Z,
      ),
    [bounds],
  );
  useEffect(() => {
    invalidate();
    return () => {
      fx.dispose();
      invalidate();
    };
  }, [fx, invalidate]);

  const state = useRef({
    time: 0,
    opacity: still ? 1 : 0,
    pulse: 0,
    bursts: useRevealStore.getState().bursts,
    plot: [0, 0] as [number, number],
    plotOpacity: 0,
  });

  useFrame((frame, delta) => {
    const s = state.current;
    const reveal = useRevealStore.getState();
    const dt = Math.min(delta, 0.1);
    const gathering = reveal.phase === "gathering";
    const ease = still ? 1 : 1 - Math.exp(-w.fade * dt);
    s.time += dt;
    s.opacity += ((gathering ? 1 : 0) - s.opacity) * ease;
    if (!gathering && s.opacity < 0.01) {
      onGone();
      return;
    }
    // A real stage change: one brighter pass, then it decays.
    if (reveal.bursts !== s.bursts) {
      s.bursts = reveal.bursts;
      s.pulse = still ? 0 : w.pulse;
    }
    s.pulse = Math.max(0, s.pulse - w.pulseDecay * s.pulse * dt - 0.02 * dt);
    // The plot eases to its size once the floor area is known.
    const plot = reveal.plot;
    if (plot) {
      const from = s.plotOpacity < 0.01 ? 0.6 : 1; // it opens up from a little smaller
      if (s.plotOpacity < 0.01) s.plot = [plot.halfWidth * from, plot.halfDepth * from];
      s.plot[0] += (plot.halfWidth - s.plot[0]) * ease;
      s.plot[1] += (plot.halfDepth - s.plot[1]) * ease;
    }
    s.plotOpacity += ((plot ? w.plotOpacity : 0) - s.plotOpacity) * ease;
    fx.update({
      opacity: s.opacity,
      // From the far edge towards the viewer, then again.
      scan: still ? 2 : 0.75 - 1.5 * ((s.time / w.scanPeriod) % 1),
      pulse: s.pulse,
      plot: s.plot,
      plotOpacity: s.plotOpacity,
    });
    // frameloop="demand": keep drawing while the sheet moves.
    if (!still || Math.abs(s.opacity - (gathering ? 1 : 0)) > 0.01) frame.invalidate();
  });

  return (
    <group rotation={MODEL_ROOT_ROTATION}>
      <primitive object={fx.mesh} />
    </group>
  );
}
