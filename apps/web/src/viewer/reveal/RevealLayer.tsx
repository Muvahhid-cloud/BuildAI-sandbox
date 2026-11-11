"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { type OrthographicCamera, type PerspectiveCamera, Plane, Vector3 } from "three";

import { MODEL_ROOT_ROTATION, modelToWorld } from "@/engine/math/coords";
import type { SceneGraph } from "@/engine/scene/build-scene";
import { useRevealStore } from "@/stores/reveal-store";
import { useViewerStore } from "@/stores/viewer-store";

import { REVEAL } from "../render-settings";
import { revealFrame } from "./machine";
import { createRevealBackdrop, createRevealParticles } from "./particles";
import { sampleSurfaces } from "./sampling";

const TIMELINE = {
  duration: REVEAL.duration,
  sweepStart: REVEAL.sweepStart,
  sweepEnd: REVEAL.sweepEnd,
  veilOpacity: REVEAL.veilOpacity,
};

/**
 * The assembly inside the 3D viewer: particles fly from the cloud to points sampled on the
 * scene's own geometry, then the real meshes are revealed bottom-up by a clipping plane (the
 * same mechanism as the section cut) while the particles fade. Mounted only while the reveal
 * runs; every GPU resource is disposed when it ends. Model, geometry, materials and picking
 * are untouched.
 */
export function RevealLayer({ scene }: { scene: SceneGraph }) {
  const phase = useRevealStore((s) => s.phase);
  const nonce = useRevealStore((s) => s.nonce);
  if (phase !== "assembling") return null;
  return <Assembly key={nonce} scene={scene} />;
}

function Assembly({ scene }: { scene: SceneGraph }) {
  const gl = useThree((s) => s.gl);
  const invalidate = useThree((s) => s.invalidate);
  const clock = useRef(0);

  const fx = useMemo(() => {
    const { mode, seed, changedIds } = useRevealStore.getState();
    const sparkle = mode === "sparkle";
    const sources = sparkle
      ? scene.descriptors.filter((d) => changedIds.has(d.elementId))
      : scene.descriptors;
    const count = sparkle ? REVEAL.sparkle.particleCount : REVEAL.particleCount;
    const sample = sampleSurfaces(sources, count, `${seed}:${mode}`);
    const particles = createRevealParticles(sample.positions, sample.seeds);
    const backdrop = sparkle ? null : createRevealBackdrop();
    const { min, max } = scene.bounds;
    const size = Math.max(max.x - min.x, max.y - min.y, max.z - min.z, 1);
    particles.setup({
      center: [(min.x + max.x) / 2, (min.y + max.y) / 2, (min.z + max.z) / 2 + size * 0.1],
      radius: size * REVEAL.cloudRadius,
      minZ: sample.minZ,
      maxZ: sample.maxZ,
      sparkle,
    });
    backdrop?.place(max.x - min.x + 4, max.y - min.y + 4, (min.x + max.x) / 2, (min.y + max.y) / 2);
    return {
      particles,
      backdrop,
      sparkle,
      plane: new Plane(UP_CLIP.clone(), 0),
      // The sweep starts just above the ground, so the ground itself is never clipped.
      minZ: Math.max(sample.minZ, 0) + 0.02,
      maxZ: sample.maxZ,
    };
  }, [scene]);

  useEffect(
    () => () => {
      fx.particles.dispose();
      fx.backdrop?.dispose();
      // Back to the section cut alone (or no clipping).
      const { section } = useViewerStore.getState();
      gl.clippingPlanes = section.enabled ? [sectionPlane(section.height)] : [];
      invalidate();
    },
    [fx, gl, invalidate],
  );

  useFrame((state, delta) => {
    const store = useRevealStore.getState();
    if (store.phase !== "assembling") return;
    if (!store.frozen) store.dispatch({ type: "tick", dt: Math.min(delta, 0.1) });
    const { elapsed, frozen } = useRevealStore.getState();
    clock.current = frozen ? elapsed : clock.current + delta;
    const camera = state.camera as PerspectiveCamera | OrthographicCamera;
    const ortho = "isOrthographicCamera" in camera && camera.isOrthographicCamera === true;
    const fov = (((camera as PerspectiveCamera).fov ?? 50) * Math.PI) / 180;
    const frame = fx.sparkle ? null : revealFrame(elapsed, TIMELINE, fx.minZ, fx.maxZ);
    fx.particles.update({
      time: clock.current,
      assemble: elapsed,
      ortho,
      scale: ortho
        ? camera.zoom * state.viewport.dpr
        : (state.size.height * state.viewport.dpr) / (2 * Math.tan(fov / 2)),
      sweepZ: frame && frame.sweep > 0 ? frame.sweepZ : -1e6,
      opacity: frame ? frame.particles : 1,
    });
    if (frame && fx.backdrop) {
      fx.backdrop.update({
        veil: frame.veil,
        // The sheet fades in as the sweep starts and out as it passes the top.
        sheet: Math.min(1, frame.sweep * 6) * Math.min(1, (1 - frame.sweep) * 6),
        sweepZ: frame.sweepZ,
      });
      // Everything above the sweep is clipped (world space), together with the section cut.
      const { section } = useViewerStore.getState();
      fx.plane.set(UP_CLIP, modelToWorld({ x: 0, y: 0, z: frame.sweepZ }).y);
      state.gl.clippingPlanes = section.enabled
        ? [fx.plane, sectionPlane(section.height)]
        : [fx.plane];
    }
    state.invalidate(); // frameloop="demand": keep drawing while the effect runs
  });

  return (
    <>
      {fx.backdrop && <primitive object={fx.backdrop.veil} />}
      <group rotation={MODEL_ROOT_ROTATION}>
        {fx.backdrop && <primitive object={fx.backdrop.sheet} />}
        <primitive object={fx.particles.points} />
      </group>
    </>
  );
}

/** Keeps what lies below a world height. */
const UP_CLIP = new Vector3(0, -1, 0);

function sectionPlane(height: number): Plane {
  return new Plane(UP_CLIP.clone(), modelToWorld({ x: 0, y: 0, z: height }).y);
}
