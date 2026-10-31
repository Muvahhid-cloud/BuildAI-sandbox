"use client";

import { OrbitControls, OrthographicCamera, PerspectiveCamera } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { type ComponentRef, useCallback, useEffect, useRef, useState } from "react";
import { type Camera, OrthographicCamera as ThreeOrthographicCamera, Vector3 } from "three";

import { modelToWorld } from "@/engine/math/coords";
import type { SceneGraph } from "@/engine/scene/build-scene";
import { cameraPose } from "@/engine/scene/camera-presets";
import { useViewerStore } from "@/stores/viewer-store";

const ANIMATION_MS = 700;

type Controls = ComponentRef<typeof OrbitControls>;

interface Tween {
  fromPos: Vector3;
  toPos: Vector3;
  fromTarget: Vector3;
  toTarget: Vector3;
  start: number;
}

const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

/**
 * Orbit/zoom/pan (drei OrbitControls), perspective/orthographic cameras and camera presets.
 * Presets are computed in model space and converted once via modelToWorld.
 *
 * drei recreates OrbitControls whenever the default camera changes (initial mount, projection
 * switch), so the controls instance is tracked in state and every pose is applied to the camera
 * those controls drive (`controls.object`).
 */
export function CameraRig({ scene }: { scene: SceneGraph }) {
  const projection = useViewerStore((s) => s.projection);
  const request = useViewerStore((s) => s.cameraRequest);
  const setLevelFilter = useViewerStore((s) => s.setLevelFilter);
  const size = useThree((s) => s.size);
  const invalidate = useThree((s) => s.invalidate);
  const [controls, setControls] = useState<Controls | null>(null);
  const tween = useRef<Tween | null>(null);
  const appliedNonce = useRef<number | null>(null);
  // Current pose, carried over when the camera/controls are replaced.
  const lastPos = useRef(new Vector3(30, 20, 30));
  const lastTarget = useRef(new Vector3(6, 2, -5));

  const fitZoom = useCallback(
    (camera: Camera) => {
      if (!(camera instanceof ThreeOrthographicCamera)) return;
      const b = scene.bounds;
      const extent = Math.max(b.max.x - b.min.x, b.max.y - b.min.y, b.max.z - b.min.z);
      camera.zoom = (Math.min(size.width, size.height) / extent) * 0.8;
      camera.updateProjectionMatrix();
    },
    [scene.bounds, size.width, size.height],
  );

  // New camera/controls: keep looking where we were looking.
  useEffect(() => {
    if (!controls) return;
    controls.object.position.copy(lastPos.current);
    controls.target.copy(lastTarget.current);
    fitZoom(controls.object);
    controls.update();
    invalidate();
    // Only when the controls instance changes; fitZoom deliberately not a trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controls, invalidate]);

  // Apply each camera preset request exactly once.
  useEffect(() => {
    if (!controls || !request || appliedNonce.current === request.nonce) return;
    appliedNonce.current = request.nonce;
    const pose = cameraPose(request.preset, scene.bounds, scene.index);
    if (pose.levelFilter) setLevelFilter(pose.levelFilter);
    const camera = controls.object;
    const toPos = modelToWorld(pose.position);
    const toTarget = modelToWorld(pose.target);
    fitZoom(camera);
    if (request.animate) {
      tween.current = {
        fromPos: camera.position.clone(),
        toPos,
        fromTarget: controls.target.clone(),
        toTarget,
        start: performance.now(),
      };
    } else {
      tween.current = null;
      camera.position.copy(toPos);
      controls.target.copy(toTarget);
      lastPos.current.copy(toPos);
      lastTarget.current.copy(toTarget);
      controls.update();
    }
    invalidate();
  }, [controls, request, scene, setLevelFilter, fitZoom, invalidate]);

  useFrame((state) => {
    if (!controls) return;
    const t = tween.current;
    if (t) {
      const k = Math.min(1, (performance.now() - t.start) / ANIMATION_MS);
      controls.object.position.lerpVectors(t.fromPos, t.toPos, ease(k));
      controls.target.lerpVectors(t.fromTarget, t.toTarget, ease(k));
      controls.update();
      if (k < 1) state.invalidate();
      else tween.current = null;
    }
    lastPos.current.copy(controls.object.position);
    lastTarget.current.copy(controls.target);
  });

  return (
    <>
      {projection === "perspective" ? (
        <PerspectiveCamera makeDefault fov={45} near={0.05} far={600} />
      ) : (
        <OrthographicCamera makeDefault near={0.05} far={1200} />
      )}
      <OrbitControls
        ref={setControls}
        makeDefault
        enableDamping
        dampingFactor={0.12}
        minDistance={0.4}
        maxDistance={250}
        maxPolarAngle={Math.PI * 0.495}
        screenSpacePanning
      />
    </>
  );
}
