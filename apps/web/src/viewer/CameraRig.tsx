"use client";

import { OrbitControls, OrthographicCamera, PerspectiveCamera } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { type ComponentRef, useCallback, useEffect, useRef, useState } from "react";
import {
  type Box3,
  type Camera,
  OrthographicCamera as ThreeOrthographicCamera,
  Vector3,
} from "three";

import { modelToWorld, type XYZ } from "@/engine/math/coords";
import type { ModelIndex } from "@/engine/model/model-index";
import { cameraPose } from "@/engine/scene/camera-presets";
import { useRevealStore } from "@/stores/reveal-store";
import { useViewerStore } from "@/stores/viewer-store";

import { waitingPose } from "./reveal/waiting";

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
export function CameraRig({ bounds, index }: { bounds: Box3; index: ModelIndex | null }) {
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
      const b = bounds;
      const extent = Math.max(b.max.x - b.min.x, b.max.y - b.min.y, b.max.z - b.min.z);
      camera.zoom = (Math.min(size.width, size.height) / extent) * 0.8;
      camera.updateProjectionMatrix();
    },
    [bounds, size.width, size.height],
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

  // No model yet (a design is being created): a calm view of the empty site. The build
  // then leaves this pose smoothly (reveal/RevealLayer).
  const waiting = index === null;
  useEffect(() => {
    if (!controls || !waiting) return;
    const pose = waitingPose(bounds);
    tween.current = null;
    controls.object.position.copy(modelToWorld(pose.position));
    controls.target.copy(modelToWorld(pose.target));
    lastPos.current.copy(controls.object.position);
    lastTarget.current.copy(controls.target);
    fitZoom(controls.object);
    controls.update();
    invalidate();
    // Only when waiting starts (or the controls are replaced); fitZoom is not a trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controls, waiting, invalidate]);

  // Apply each camera preset request exactly once (requests wait for a model).
  useEffect(() => {
    if (!controls || !request || appliedNonce.current === request.nonce) return;
    appliedNonce.current = request.nonce;
    if (!index) return; // asked for while there was no model: the waiting view stays
    const pose = cameraPose(request.preset, bounds, index);
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
  }, [controls, request, bounds, index, setLevelFilter, fitZoom, invalidate]);

  // Development aid for reproducible screenshots (docs/visual): set an exact pose in MODEL
  // coordinates. Never present in production builds.
  useEffect(() => {
    if (process.env.NODE_ENV === "production" || !controls) return;
    const w = window as unknown as { __buildaiViewer?: unknown };
    w.__buildaiViewer = {
      setPose: (position: XYZ, target: XYZ, levelFilter?: string) => {
        if (levelFilter) setLevelFilter(levelFilter);
        tween.current = null;
        controls.object.position.copy(modelToWorld(position));
        controls.target.copy(modelToWorld(target));
        controls.update();
        invalidate();
      },
    };
    // Construction at a fixed time (frame reviews, screenshots in docs/visual/reveal).
    const reveal = w as unknown as { __buildaiReveal?: unknown };
    reveal.__buildaiReveal = {
      // With element ids: the short re-assembly of those elements ("changes").
      // `holdCamera`: keep the camera where it is (a close-up set with __buildaiViewer).
      freeze: (elapsed: number, changedIds?: string[] | null, holdCamera = false) => {
        const store = useRevealStore.getState();
        const mode = changedIds ? "changes" : "build";
        if (store.phase !== "assembling" || store.mode !== mode) {
          store.play(mode, changedIds ?? undefined);
        }
        useRevealStore.getState().freeze(elapsed, holdCamera);
      },
    };
    return () => {
      delete w.__buildaiViewer;
      delete reveal.__buildaiReveal;
    };
  }, [controls, invalidate, setLevelFilter]);

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
