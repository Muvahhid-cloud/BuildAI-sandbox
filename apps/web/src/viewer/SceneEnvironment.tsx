"use client";

import { ContactShadows, Environment, Grid } from "@react-three/drei";
import { Component, type ReactNode, Suspense, useEffect, useMemo } from "react";
import {
  BackSide,
  type Box3,
  Color,
  Float32BufferAttribute,
  MeshBasicMaterial,
  Object3D,
  SphereGeometry,
  Vector3,
} from "three";

import { SITE_GROUND_MATERIAL } from "@/engine/materials/library";
import { materialCache } from "@/engine/materials/material-cache";
import { modelToWorld } from "@/engine/math/coords";
import { groundDiscGeometry, siteRadius } from "@/engine/scene/site";
import { useViewerStore } from "@/stores/viewer-store";

import { RENDER } from "./render-settings";

// Environment (not part of the BuildingModel): image-based lighting from a local HDRI, the sun
// with soft shadows, contact shadows, a textured site ground, a neutral sky and the optional
// reference grid — in WORLD space. The sun direction is defined in model space (from the
// south-west, high) and converted.
const SUN_DIRECTION_MODEL = { x: -0.55, y: -0.9, z: 1.35 };
const GROUND_Y = -0.05;
const NO_RAYCAST = () => undefined;

export function SceneEnvironment({ bounds }: { bounds: Box3 }) {
  // Renderer clipping planes do not apply to the shadow pass: a sectioned house would still
  // cast its full shadow, so sun and contact shadows are switched off while a section is active.
  const sectioned = useViewerStore((s) => s.section.enabled);
  const showGrid = useViewerStore((s) => s.showGrid);
  const { center, radius, ground, sunPosition, target, footprint } = useMemo(() => {
    const c = bounds.getCenter(new Vector3());
    const size = bounds.getSize(new Vector3());
    const r = Math.max(size.length() / 2, 5);
    const centerWorld = modelToWorld(c);
    const dir = modelToWorld(SUN_DIRECTION_MODEL).normalize();
    const t = new Object3D();
    t.position.copy(centerWorld);
    return {
      center: centerWorld,
      radius: r,
      ground: siteRadius(bounds),
      sunPosition: centerWorld.clone().addScaledVector(dir, r * 3),
      target: t,
      footprint: Math.max(size.x, size.y) * 1.6 + 4,
    };
  }, [bounds]);

  return (
    <>
      <EnvironmentLighting />
      <fog attach="fog" args={[RENDER.sky.horizon, ground * 0.35, ground * 0.95]} />
      <primitive object={target} />
      <directionalLight
        castShadow={!sectioned}
        position={sunPosition}
        target={target}
        color={RENDER.sunColor}
        intensity={RENDER.sunIntensity}
        shadow-mapSize={[RENDER.shadowMapSize, RENDER.shadowMapSize]}
        shadow-radius={RENDER.shadowRadius}
        shadow-bias={-0.0004}
        shadow-normalBias={0.03}
        shadow-camera-left={-radius * 1.3}
        shadow-camera-right={radius * 1.3}
        shadow-camera-top={radius * 1.3}
        shadow-camera-bottom={-radius * 1.3}
        shadow-camera-near={0.5}
        shadow-camera-far={radius * 6}
      />
      <SkyDome center={center} radius={ground * 1.5} />
      <SiteGround center={center} radius={ground} />
      {!sectioned && (
        <ContactShadows
          position={[center.x, GROUND_Y + 0.004, center.z]}
          scale={footprint}
          opacity={RENDER.contactShadow.opacity}
          blur={RENDER.contactShadow.blur}
          far={RENDER.contactShadow.far}
          resolution={RENDER.contactShadow.resolution}
          color="#1d2124"
        />
      )}
      {showGrid && (
        <Grid
          position={[0, GROUND_Y + 0.006, 0]}
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
      )}
    </>
  );
}

/** HDRI image-based lighting; falls back to a hemisphere light if the file cannot load. */
function EnvironmentLighting() {
  const h = RENDER.fallbackHemisphere;
  const fallback = <hemisphereLight args={[h.sky, h.ground, h.intensity]} />;
  return (
    <LoadBoundary fallback={fallback}>
      <Suspense fallback={fallback}>
        <Environment
          files={RENDER.hdriUrl}
          environmentIntensity={RENDER.environmentIntensity}
          background={false}
        />
      </Suspense>
    </LoadBoundary>
  );
}

class LoadBoundary extends Component<{ fallback: ReactNode; children: ReactNode }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.info("[viewer] HDRI not available, using hemisphere light:", String(error));
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** Textured grass disc (library material `site_grass`, UVs in meters). */
function SiteGround({ center, radius }: { center: Vector3; radius: number }) {
  const geometry = useMemo(() => groundDiscGeometry(radius), [radius]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  const material = materialCache.get(SITE_GROUND_MATERIAL);
  return (
    <mesh
      rotation-x={-Math.PI / 2}
      position={[center.x, GROUND_Y, center.z]}
      geometry={geometry}
      material={material}
      receiveShadow
      raycast={NO_RAYCAST}
      dispose={null}
    />
  );
}

/** Neutral vertical gradient sky (deterministic vertex colors, not tone mapped). */
function SkyDome({ center, radius }: { center: Vector3; radius: number }) {
  const { geometry, material } = useMemo(() => {
    const g = new SphereGeometry(radius, 32, 16);
    const zenith = new Color(RENDER.sky.zenith);
    const horizon = new Color(RENDER.sky.horizon);
    const pos = g.getAttribute("position");
    const colors: number[] = [];
    const c = new Color();
    for (let i = 0; i < pos.count; i++) {
      const t = Math.max(0, pos.getY(i) / radius);
      c.copy(horizon).lerp(zenith, Math.pow(t, 0.6));
      colors.push(c.r, c.g, c.b);
    }
    g.setAttribute("color", new Float32BufferAttribute(colors, 3));
    const m = new MeshBasicMaterial({
      vertexColors: true,
      side: BackSide,
      depthWrite: false,
      toneMapped: false,
      fog: false,
    });
    return { geometry: g, material: m };
  }, [radius]);
  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
    },
    [geometry, material],
  );
  return (
    <mesh
      position={[center.x, 0, center.z]}
      geometry={geometry}
      material={material}
      renderOrder={-1}
      raycast={NO_RAYCAST}
    />
  );
}
