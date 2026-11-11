"use client";

import { useLoader } from "@react-three/fiber";
import { Component, type ReactNode, Suspense, useMemo } from "react";
import { type Matrix4, Mesh, type Object3D } from "three";
import { type GLTF, GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

import { MATERIAL_ASSET_BASE } from "@/engine/materials/library";
import type { ModelEntry } from "@/engine/materials/models";

import { revealTag } from "./reveal/gate";

const NO_RAYCAST = () => undefined;
const prepared = new WeakSet<GLTF>();

/**
 * Once per loaded file: shadows on, picking off (the element's placeholder box stays the pick
 * proxy), and alpha-blended foliage switched to alpha-test so it sorts and casts proper shadows.
 */
function prepare(gltf: GLTF): GLTF {
  if (prepared.has(gltf)) return gltf;
  prepared.add(gltf);
  gltf.scene.traverse((o: Object3D) => {
    if (!(o instanceof Mesh)) return;
    o.castShadow = true;
    o.receiveShadow = true;
    o.raycast = NO_RAYCAST;
    for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
      if (m.transparent && m.map) {
        m.transparent = false;
        m.alphaTest = 0.5;
        m.depthWrite = true;
        m.needsUpdate = true;
      }
    }
  });
  return gltf;
}

function LoadedModel({
  model,
  matrix,
  revealKey,
}: {
  model: ModelEntry;
  matrix: Matrix4;
  revealKey?: string;
}) {
  const gltf = useLoader(GLTFLoader, `${MATERIAL_ASSET_BASE}${model.file}`, (loader) => {
    loader.setMeshoptDecoder(MeshoptDecoder);
  });
  // Clones share geometry and materials with the cached file (cheap per instance).
  const object = useMemo(() => prepare(gltf).scene.clone(true), [gltf]);
  // The build reveal shows the model when the pieces of `revealKey` have landed (§25).
  const userData = useMemo(() => (revealKey ? revealTag(revealKey) : {}), [revealKey]);
  return (
    <group matrix={matrix} matrixAutoUpdate={false} userData={userData}>
      <primitive object={object} />
    </group>
  );
}

class ModelBoundary extends Component<{ fallback: ReactNode; children: ReactNode }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.info("[viewer] model not available, using the placeholder:", String(error));
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/**
 * A CC0 glTF model placed by `matrix` (model space, Z-up). While loading, or if the file cannot
 * be loaded, `fallback` (the procedural placeholder) is shown instead.
 */
export function ModelInstance({
  model,
  matrix,
  fallback = null,
  revealKey,
}: {
  model: ModelEntry;
  matrix: Matrix4;
  fallback?: ReactNode;
  /** Element id (or site key) the build reveal assembles this model for. */
  revealKey?: string;
}) {
  return (
    <ModelBoundary fallback={fallback}>
      <Suspense fallback={fallback}>
        <LoadedModel model={model} matrix={matrix} revealKey={revealKey} />
      </Suspense>
    </ModelBoundary>
  );
}
