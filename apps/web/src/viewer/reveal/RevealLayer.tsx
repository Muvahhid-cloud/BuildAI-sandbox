"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { type Box3, type Camera, Group, type Object3D, type Vector3 } from "three";

import { modelsFor } from "@/engine/materials/models";
import { MODEL_ROOT_ROTATION, modelToWorld } from "@/engine/math/coords";
import type { SceneGraph } from "@/engine/scene/build-scene";
import { cameraPose } from "@/engine/scene/camera-presets";
import { visibilityMap } from "@/engine/scene/visibility";
import { useLayerStore } from "@/stores/layer-store";
import { useRevealStore } from "@/stores/reveal-store";
import { useViewerStore } from "@/stores/viewer-store";

import { REVEAL } from "../render-settings";
import { useServedAssets } from "../served-assets";
import { blueprintFrame, blueprintPlan } from "./blueprint";
import { easeInOut, orbitPose } from "./camera";
import { gateScene, ungateScene } from "./gate";
import { createRevealBlueprint, createRevealPieces } from "./gpu";
import { createGrowth, createObjectGrowth, type Growth } from "./growth";
import { growthAt } from "./order";
import { buildRevealPlan } from "./plan";
import { WaitingGround } from "./WaitingGround";

/** Height of the site ground in model space (SceneEnvironment GROUND_Y) plus a hair. */
const GROUND_Z = -0.05 + 0.012;
/** The front starts a hair below the base, so nothing of the element shows before it grows. */
const BELOW_BASE = 0.003;

interface OrbitTarget {
  object: Camera;
  target: Vector3;
  update: () => void;
}

const smoothstep = (a: number, b: number, x: number) => {
  const t = Math.min(Math.max((x - a) / (b - a), 0), 1);
  return t * t * (3 - 2 * t);
};

/**
 * Live creation inside the 3D viewer's own canvas: the drafting sheet while the backend works
 * (`WaitingGround`), then — as soon as there is a model — its ground-floor plan draws itself
 * and the building is constructed: every element grows from its base to its top, with thin
 * slices of its own material settling at the growing front. Mounted only while it runs; every
 * GPU resource is disposed when it ends. Model, geometry, materials and picking are untouched:
 * unfinished meshes only wait on a hidden camera layer (gate.ts).
 */
export function RevealLayer({ scene, bounds }: { scene: SceneGraph | null; bounds: Box3 }) {
  const phase = useRevealStore((s) => s.phase);
  const nonce = useRevealStore((s) => s.nonce);
  return (
    <>
      <WaitingGround bounds={bounds} />
      {phase === "assembling" && scene && <Assembly key={nonce} scene={scene} />}
    </>
  );
}

function Assembly({ scene }: { scene: SceneGraph }) {
  const root = useThree((s) => s.scene);
  const gl = useThree((s) => s.gl);
  const invalidate = useThree((s) => s.invalidate);
  const controls = useThree((s) => s.controls) as unknown as OrbitTarget | null;
  const served = useServedAssets();
  const growths = useRef(new Map<string, Growth>());
  const modelRoot = useMemo(() => new Group(), []);
  const worldRoot = useMemo(() => new Group(), []);
  const from = useRef<{ position: Vector3; target: Vector3 } | null>(null);

  const fx = useMemo(() => {
    const { mode, seed, changedIds } = useRevealStore.getState();
    const view = useViewerStore.getState();
    const build = mode === "build";
    // Only what the viewer shows takes part (isolated levels, hidden layers stay as they are).
    const modes = visibilityMap(scene.index, {
      levelFilter: view.levelFilter,
      layers: useLayerStore.getState().visible,
      showRoof: view.showRoof,
      showExteriorWalls: view.showExteriorWalls,
    });
    const visible = (id: string) => (modes.get(id) ?? "visible") === "visible";
    // Plants are drawn only when their model file is served (SiteLayer).
    const plants = new Set<"tree" | "bush">();
    if (build && view.showSite && served) {
      for (const kind of ["tree", "bush"] as const) {
        if (modelsFor(kind).some((m) => served.has(m.file))) plants.add(kind);
      }
    }
    const plan = buildRevealPlan(scene, {
      seed: `${seed}:${mode}`,
      include: build ? visible : (id) => visible(id) && changedIds.has(id),
      site: build && view.showSite ? { plants } : null,
      modelServed: (file) => served?.has(file) ?? false,
      short: !build,
    });
    const pieces = createRevealPieces(plan.pieces, plan.front);
    const { min, max } = scene.bounds;
    const m = REVEAL.blueprint.margin;
    const blueprint = build
      ? createRevealBlueprint(
          blueprintPlan(
            scene.index,
            plan.steps.map((s) => s.id),
          ),
          [min.x - m, min.y - m, max.x + m, max.y + m],
          GROUND_Z,
        )
      : null;
    return {
      build,
      plan,
      pieces,
      blueprint,
      end: cameraPose("exterior", scene.bounds, scene.index),
    };
  }, [scene, served]);

  const drop = (key: string) => {
    growths.current.get(key)?.dispose();
    growths.current.delete(key);
  };

  /** Hides what is not complete yet; grows what is being built right now. */
  const apply = (elapsed: number) => {
    const { timings } = fx.plan.schedule;
    const g = REVEAL.growth;
    const tagged = new Map<string, Object3D>();
    // The real mesh waits until its front has reached the top; its stand-in grows meanwhile.
    gateScene(
      root,
      (key) => {
        const t = timings.get(key);
        return t !== undefined && elapsed < t.end;
      },
      tagged,
    );
    for (const step of fx.plan.steps) {
      const t = timings.get(step.id)!;
      if (elapsed < t.start || elapsed >= t.end) {
        if (growths.current.has(step.id)) drop(step.id);
        continue;
      }
      let growth = growths.current.get(step.id);
      if (!growth) {
        // Drawn by an object of its own (glTF model, site mesh, plant): grown from that
        // object, once it is loaded; otherwise from the element's render descriptors.
        const object = tagged.get(step.id);
        const parts = scene.byElement.get(step.id);
        if (fx.plan.objects.has(step.id)) {
          if (!object) continue;
          growth = createObjectGrowth(object);
        } else if (parts) {
          growth = createGrowth(parts);
        } else {
          continue;
        }
        (growth.space === "model" ? modelRoot : worldRoot).add(growth.object);
        growths.current.set(step.id, growth);
      }
      const share = growthAt(t, elapsed);
      const height = t.topZ - t.baseZ + g.overshoot + BELOW_BASE;
      growth.setFront(
        t.baseZ - BELOW_BASE + share * height,
        g.edgeGain * (1 - smoothstep(1 - g.edgeFadeOut, 1, share)),
      );
    }
  };

  useLayoutEffect(() => {
    // Growing stand-ins and cut surfaces use clipped variants of the material shaders. One
    // zero-size stand-in per material is drawn from the first frame (while the blueprint
    // draws), so no shader is compiled in the middle of the build.
    const warm: Growth[] = [];
    const warmed = new Set<string>();
    for (const step of fx.plan.steps) {
      if (fx.plan.objects.has(step.id)) continue;
      for (const d of scene.byElement.get(step.id) ?? []) {
        if (d.materials.every((id) => warmed.has(id))) continue;
        d.materials.forEach((id) => warmed.add(id));
        const growth = createGrowth([d]);
        growth.object.children.forEach((mesh) => {
          mesh.matrix.makeScale(0, 0, 0);
          mesh.castShadow = false;
          mesh.frustumCulled = false;
        });
        modelRoot.add(growth.object);
        warm.push(growth);
      }
    }
    // Each stand-in is cut by its own plane (three.js local clipping).
    const localClipping = gl.localClippingEnabled;
    gl.localClippingEnabled = true;
    const store = useRevealStore.getState();
    store.setDuration(store.mode, fx.plan.schedule.duration);
    apply(store.elapsed); // before the first frame: the finished model never flashes
    const live = growths.current;
    return () => {
      fx.pieces.dispose();
      fx.blueprint?.dispose();
      fx.plan.owned.forEach((geometry) => geometry.dispose());
      for (const growth of [...live.values(), ...warm]) growth.dispose();
      live.clear();
      gl.localClippingEnabled = localClipping;
      ungateScene(root);
      invalidate();
    };
    // `apply` reads only fx, scene and refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fx, root, gl, invalidate]);

  // A frame frozen at another time (screenshots) is drawn once.
  const frozenAt = useRevealStore((s) => (s.frozen ? s.elapsed : -1));
  useEffect(() => invalidate(), [frozenAt, invalidate]);

  useFrame((state, delta) => {
    const store = useRevealStore.getState();
    if (store.phase !== "assembling") return;
    if (!store.frozen) store.dispatch({ type: "tick", dt: Math.min(delta, 0.1) });
    const { elapsed, frozen, cameraHeld, phase } = useRevealStore.getState();
    const duration = fx.plan.schedule.duration;
    if (phase !== "assembling") {
      // Built to the end on this tick: the camera rests exactly on the exterior view (a
      // skipped build leaves the camera where the user took it over). The cleanup shows all.
      if (fx.build && controls && phase === "done") {
        controls.object.position.copy(modelToWorld(fx.end.position));
        controls.target.copy(modelToWorld(fx.end.target));
        controls.update();
      }
      return;
    }
    fx.pieces.update(elapsed);
    apply(elapsed);
    fx.blueprint?.update(blueprintFrame(elapsed, duration, REVEAL.blueprint));
    if (fx.build && controls && !cameraHeld) {
      const pose = orbitPose(fx.end, elapsed / duration, REVEAL.camera);
      const position = modelToWorld(pose.position);
      const target = modelToWorld(pose.target);
      // Leave the camera's current pose smoothly (the waiting view, or wherever a replay
      // starts from).
      from.current ??= {
        position: controls.object.position.clone(),
        target: controls.target.clone(),
      };
      const k = frozen ? 1 : easeInOut(elapsed / REVEAL.camera.blend);
      controls.object.position.lerpVectors(from.current.position, position, k);
      controls.target.lerpVectors(from.current.target, target, k);
      controls.update();
    }
    // frameloop="demand": keep drawing while the effect runs (a frozen frame is drawn once).
    if (!frozen) state.invalidate();
  });

  return (
    <>
      <group rotation={MODEL_ROOT_ROTATION}>
        {fx.blueprint && <primitive object={fx.blueprint.sheet} />}
        {fx.blueprint && <primitive object={fx.blueprint.lines} />}
        <primitive object={modelRoot} />
        <primitive object={fx.pieces.group} />
      </group>
      <primitive object={worldRoot} />
    </>
  );
}
