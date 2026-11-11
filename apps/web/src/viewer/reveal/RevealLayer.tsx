"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { type Camera, Group, type Material, Mesh, type Vector3 } from "three";

import type { RenderDescriptor } from "@/engine/builders/types";
import { materialCache } from "@/engine/materials/material-cache";
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
import { orbitPose } from "./camera";
import { gateScene, ungateScene } from "./gate";
import { createRevealBlueprint, createRevealPieces } from "./gpu";
import { buildRevealPlan } from "./plan";

interface Fade {
  group: Group;
  materials: Material[];
  /** Opacity of each material when fully shown. */
  opacity: number[];
}

/**
 * A copy of an element's meshes with their own (cloned) materials: only its opacity changes;
 * when it is opaque the real mesh takes over, pixel for pixel. Never pickable.
 */
function fadeCopy(parts: readonly RenderDescriptor[]): Fade {
  const fade: Fade = { group: new Group(), materials: [], opacity: [] };
  for (const d of parts) {
    const list = d.materials.map((id) => {
      const mat = materialCache.get(id).clone();
      fade.materials.push(mat);
      fade.opacity.push(mat.opacity);
      mat.transparent = true;
      return mat;
    });
    const mesh = new Mesh(d.geometry, list.length === 1 ? list[0] : list);
    mesh.matrixAutoUpdate = false;
    mesh.matrix.copy(d.matrix);
    mesh.castShadow = d.castShadow;
    mesh.receiveShadow = true;
    mesh.raycast = () => undefined;
    fade.group.add(mesh);
  }
  return fade;
}

/** Height of the site ground in model space (SceneEnvironment GROUND_Y) plus a hair. */
const GROUND_Z = -0.05 + 0.012;

interface OrbitTarget {
  object: Camera;
  target: Vector3;
  update: () => void;
}

/**
 * The construction of the model inside the 3D viewer: the ground-floor plan draws itself, then
 * every element assembles from small pieces in construction order; when an element's pieces
 * have landed its real mesh fades in and the pieces shrink away. Mounted only while the reveal
 * runs; every GPU resource is disposed when it ends. Model, geometry, materials and picking are
 * untouched: unbuilt meshes are only moved to a hidden camera layer (gate.ts).
 */
export function RevealLayer({ scene }: { scene: SceneGraph }) {
  const phase = useRevealStore((s) => s.phase);
  const nonce = useRevealStore((s) => s.nonce);
  if (phase !== "assembling") return null;
  return <Assembly key={nonce} scene={scene} />;
}

function Assembly({ scene }: { scene: SceneGraph }) {
  const root = useThree((s) => s.scene);
  const invalidate = useThree((s) => s.invalidate);
  const controls = useThree((s) => s.controls) as unknown as OrbitTarget | null;
  const served = useServedAssets();
  const fades = useRef(new Map<string, Fade>());
  const fadeRoot = useMemo(() => new Group(), []);
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
      short: !build,
    });
    const pieces = createRevealPieces(plan.pieces, plan.motion);
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

  /** Hides what is not built yet; fades in what has just been completed. */
  const apply = (elapsed: number) => {
    const { timings } = fx.plan.schedule;
    const models = new Set<string>();
    // Hidden until the pieces have landed; while the copy fades in, the copy stands in.
    gateScene(
      root,
      (key) => {
        const t = timings.get(key);
        return t !== undefined && elapsed < (models.has(key) ? t.landed : t.shown);
      },
      models,
    );
    for (const step of fx.plan.steps) {
      const t = timings.get(step.id)!;
      const parts = scene.byElement.get(step.id);
      const fading = parts && !models.has(step.id) && elapsed >= t.landed && elapsed < t.shown;
      let fade = fades.current.get(step.id);
      if (!fading) {
        if (fade) {
          fadeRoot.remove(fade.group);
          fade.materials.forEach((mat) => mat.dispose());
          fades.current.delete(step.id);
        }
        continue;
      }
      if (!fade) {
        fade = fadeCopy(parts);
        fadeRoot.add(fade.group);
        fades.current.set(step.id, fade);
      }
      const k = (elapsed - t.landed) / Math.max(t.shown - t.landed, 1e-6);
      fade.materials.forEach((mat, i) => {
        mat.opacity = fade!.opacity[i]! * k;
      });
    }
  };

  useLayoutEffect(() => {
    // Fading copies use the transparent variant of each material's shader. One zero-size
    // copy per material is drawn from the first frame (while the blueprint draws), so no
    // shader is compiled in the middle of the build.
    const warm: Fade[] = [];
    const warmed = new Set<string>();
    for (const step of fx.plan.steps) {
      for (const d of scene.byElement.get(step.id) ?? []) {
        if (d.materials.every((id) => warmed.has(id))) continue;
        d.materials.forEach((id) => warmed.add(id));
        const copy = fadeCopy([d]);
        copy.materials.forEach((mat) => (mat.opacity = 0));
        copy.group.children.forEach((mesh) => {
          mesh.matrix.makeScale(0, 0, 0);
          mesh.castShadow = false;
          mesh.frustumCulled = false;
        });
        fadeRoot.add(copy.group);
        warm.push(copy);
      }
    }
    const store = useRevealStore.getState();
    store.setDuration(store.mode, fx.plan.schedule.duration);
    apply(store.elapsed); // before the first frame: the finished model never flashes
    const live = fades.current;
    return () => {
      fx.pieces.dispose();
      fx.blueprint?.dispose();
      fx.plan.owned.forEach((g) => g.dispose());
      for (const fade of [...live.values(), ...warm]) {
        fadeRoot.remove(fade.group);
        fade.materials.forEach((mat) => mat.dispose());
      }
      live.clear();
      ungateScene(root);
      invalidate();
    };
    // `apply` reads only fx, scene and refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fx, root, invalidate]);

  // The build ends on the default exterior view — also when it is skipped.
  useEffect(() => {
    if (!fx.build || !controls) return;
    return () => {
      controls.object.position.copy(modelToWorld(fx.end.position));
      controls.target.copy(modelToWorld(fx.end.target));
      controls.update();
    };
  }, [fx, controls]);

  // A frame frozen at another time (screenshots) is drawn once.
  const frozenAt = useRevealStore((s) => (s.frozen ? s.elapsed : -1));
  useEffect(() => invalidate(), [frozenAt, invalidate]);

  useFrame((state, delta) => {
    const store = useRevealStore.getState();
    if (store.phase !== "assembling") return;
    if (!store.frozen) store.dispatch({ type: "tick", dt: Math.min(delta, 0.1) });
    const { elapsed, frozen, phase } = useRevealStore.getState();
    if (phase !== "assembling") return; // finished on this tick: the cleanup shows everything
    const duration = fx.plan.schedule.duration;
    fx.pieces.update(elapsed);
    apply(elapsed);
    fx.blueprint?.update(blueprintFrame(elapsed, duration, REVEAL.blueprint));
    if (fx.build && controls) {
      const pose = orbitPose(fx.end, elapsed / duration, REVEAL.camera);
      const position = modelToWorld(pose.position);
      const target = modelToWorld(pose.target);
      // Leave the camera's current pose smoothly (a replay can start from anywhere).
      from.current ??= {
        position: controls.object.position.clone(),
        target: controls.target.clone(),
      };
      const blend = frozen ? 1 : Math.min(elapsed / REVEAL.camera.blend, 1);
      const k = blend * blend * (3 - 2 * blend);
      controls.object.position.lerpVectors(from.current.position, position, k);
      controls.target.lerpVectors(from.current.target, target, k);
      controls.update();
    }
    // frameloop="demand": keep drawing while the effect runs (a frozen frame is drawn once).
    if (!frozen) state.invalidate();
  });

  return (
    <group rotation={MODEL_ROOT_ROTATION}>
      {fx.blueprint && <primitive object={fx.blueprint.sheet} />}
      {fx.blueprint && <primitive object={fx.blueprint.lines} />}
      <primitive object={fadeRoot} />
      <primitive object={fx.pieces.mesh} />
    </group>
  );
}
