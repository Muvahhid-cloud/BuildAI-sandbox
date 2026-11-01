"use client";

import { useThree } from "@react-three/fiber";
import { useEffect } from "react";

import { materialCache } from "@/engine/materials/material-cache";

/** Re-renders the on-demand canvas when a library texture finishes loading. */
export function MaterialTextures() {
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => materialCache.onChange(() => invalidate()), [invalidate]);
  return null;
}
