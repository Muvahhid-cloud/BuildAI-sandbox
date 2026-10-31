"use client";

import { Grid } from "@react-three/drei";
import { useMemo } from "react";
import { type Box3, Object3D, Vector3 } from "three";

import { modelToWorld } from "@/engine/math/coords";
import { useViewerStore } from "@/stores/viewer-store";

// Environment (not part of the BuildingModel): lighting, ground and reference grid, in WORLD
// space. The sun direction is defined in model space (from south-west, high) and converted.
const SUN_DIRECTION_MODEL = { x: -0.55, y: -0.9, z: 1.35 };
const GROUND_COLOR = "#dfe3da";

export function SceneEnvironment({ bounds }: { bounds: Box3 }) {
  // Renderer clipping planes do not apply to the shadow pass: a sectioned house would still
  // cast its full shadow, so sun shadows are switched off while a section cut is active.
  const sectioned = useViewerStore((s) => s.section.enabled);
  const { center, radius, sunPosition, target } = useMemo(() => {
    const c = bounds.getCenter(new Vector3());
    const r = Math.max(bounds.getSize(new Vector3()).length() / 2, 5);
    const centerWorld = modelToWorld(c);
    const dir = modelToWorld(SUN_DIRECTION_MODEL).normalize();
    const t = new Object3D();
    t.position.copy(centerWorld);
    return {
      center: centerWorld,
      radius: r,
      sunPosition: centerWorld.clone().addScaledVector(dir, r * 3),
      target: t,
    };
  }, [bounds]);

  return (
    <>
      <hemisphereLight args={["#f4f7fb", "#a89c8a", 1.1]} />
      <ambientLight intensity={0.25} />
      <primitive object={target} />
      <directionalLight
        castShadow={!sectioned}
        position={sunPosition}
        target={target}
        intensity={2.4}
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0004}
        shadow-normalBias={0.03}
        shadow-camera-left={-radius * 1.3}
        shadow-camera-right={radius * 1.3}
        shadow-camera-top={radius * 1.3}
        shadow-camera-bottom={-radius * 1.3}
        shadow-camera-near={0.5}
        shadow-camera-far={radius * 6}
      />
      <mesh rotation-x={-Math.PI / 2} position={[center.x, -0.05, center.z]} receiveShadow>
        <circleGeometry args={[Math.max(60, radius * 6), 64]} />
        <meshStandardMaterial color={GROUND_COLOR} roughness={1} />
      </mesh>
      <Grid
        position={[0, -0.045, 0]}
        infiniteGrid
        cellSize={1}
        sectionSize={5}
        cellThickness={0.6}
        sectionThickness={1}
        cellColor="#c3c9ce"
        sectionColor="#97a1aa"
        fadeDistance={90}
        fadeStrength={1.5}
      />
    </>
  );
}
