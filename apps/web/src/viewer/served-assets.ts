"use client";

// Which material assets the server actually ships (public/materials/manifest.json, written by
// scripts/sync-materials.mjs). Models and textures are requested only when listed, so a
// missing file means "use the fallback" without a failing request.
import { useEffect, useState } from "react";

import { MATERIAL_ASSET_BASE } from "@/engine/materials/library";

let served: Promise<ReadonlySet<string>> | null = null;

export function servedAssets(): Promise<ReadonlySet<string>> {
  served ??= fetch(`${MATERIAL_ASSET_BASE}manifest.json`)
    .then((r) => (r.ok ? (r.json() as Promise<{ files?: unknown }>) : { files: [] }))
    .then((m) => new Set(Array.isArray(m.files) ? m.files.map(String) : []))
    .catch(() => new Set<string>());
  return served;
}

/** The served file set, or null while it is loading. */
export function useServedAssets(): ReadonlySet<string> | null {
  const [files, setFiles] = useState<ReadonlySet<string> | null>(null);
  useEffect(() => {
    let alive = true;
    void servedAssets().then((f) => {
      if (alive) setFiles(f);
    });
    return () => {
      alive = false;
    };
  }, []);
  return files;
}
