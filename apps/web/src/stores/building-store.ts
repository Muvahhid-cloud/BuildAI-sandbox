import { create } from "zustand";

import type { ModelIndex } from "@/engine/model/model-index";
import { parseBuildingModel } from "@/engine/model/parse";
import { buildScene, disposeScene, type SceneGraph } from "@/engine/scene/build-scene";

interface BuildingState {
  status: "empty" | "ready" | "error";
  /** The validated BuildingModel (source of truth) and its lookup index. */
  index: ModelIndex | null;
  /** Derived render data. Rebuilt from the model, never edited directly. */
  scene: SceneGraph | null;
  error: string | null;
  buildMs: number | null;
  /** Validate + index + build. Geometry of unchanged elements is reused from the previous scene. */
  load: (json: unknown) => void;
  clear: () => void;
}

export const useBuildingStore = create<BuildingState>()((set, get) => ({
  status: "empty",
  index: null,
  scene: null,
  error: null,
  buildMs: null,

  load: (json) => {
    const previous = get().scene ?? undefined;
    try {
      const started = performance.now();
      const index = parseBuildingModel(json);
      const scene = buildScene(index, undefined, previous);
      if (previous) disposeScene(previous, scene);
      set({ status: "ready", index, scene, error: null, buildMs: performance.now() - started });
    } catch (err) {
      set({ status: "error", error: err instanceof Error ? err.message : String(err) });
    }
  },

  clear: () => {
    const { scene } = get();
    if (scene) disposeScene(scene);
    set({ status: "empty", index: null, scene: null, error: null, buildMs: null });
  },
}));
