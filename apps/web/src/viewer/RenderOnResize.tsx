"use client";

import { useThree } from "@react-three/fiber";
import { useEffect } from "react";

/**
 * With frameloop="demand" a canvas resize (layout settling, window resize, panel reflow)
 * clears the drawing buffer without scheduling a new frame. Request one on every size change.
 */
export function RenderOnResize() {
  const width = useThree((s) => s.size.width);
  const height = useThree((s) => s.size.height);
  const dpr = useThree((s) => s.viewport.dpr);
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => {
    invalidate();
  }, [width, height, dpr, invalidate]);
  return null;
}
