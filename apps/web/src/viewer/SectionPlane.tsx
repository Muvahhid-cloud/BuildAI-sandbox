"use client";

import { useThree } from "@react-three/fiber";
import { useEffect } from "react";
import { Plane, Vector3 } from "three";

import { modelToWorld } from "@/engine/math/coords";
import { useViewerStore } from "@/stores/viewer-store";

/** Horizontal section cut: everything above `height` (model z, meters) is clipped. */
export function SectionPlane() {
  const enabled = useViewerStore((s) => s.section.enabled);
  const height = useViewerStore((s) => s.section.height);
  const get = useThree((s) => s.get);
  const invalidate = useThree((s) => s.invalidate);

  useEffect(() => {
    const { gl } = get();
    const worldY = modelToWorld({ x: 0, y: 0, z: height }).y;
    // Keeps points where -y + worldY >= 0, i.e. below the cut.
    gl.clippingPlanes = enabled ? [new Plane(new Vector3(0, -1, 0), worldY)] : [];
    invalidate();
    return () => {
      gl.clippingPlanes = [];
    };
  }, [enabled, height, get, invalidate]);

  return null;
}
