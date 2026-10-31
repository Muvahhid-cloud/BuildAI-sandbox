import { create } from "zustand";

import type { CameraPresetId } from "@/engine/scene/camera-presets";
import type { LevelFilter } from "@/engine/scene/visibility";

export type Projection = "perspective" | "orthographic";
/** The 3D model or its 2D floor-plan drawing (both derived from the same BuildingModel). */
export type ViewMode = "3d" | "plan";

export interface CameraRequest {
  preset: CameraPresetId;
  /** Increments on every request so repeating the same preset still re-applies it. */
  nonce: number;
  animate: boolean;
}

interface ViewerState {
  levelFilter: LevelFilter;
  showRoof: boolean;
  showExteriorWalls: boolean;
  projection: Projection;
  section: { enabled: boolean; height: number };
  cameraRequest: CameraRequest | null;
  viewMode: ViewMode;
  /** Level shown in the plan view (null = the first level). */
  planLevelId: string | null;

  /** Floor navigation: isolates a level and frames it; "all" keeps the current camera. */
  selectFloor: (filter: LevelFilter) => void;
  setLevelFilter: (filter: LevelFilter) => void;
  requestCamera: (preset: CameraPresetId, animate?: boolean) => void;
  setShowRoof: (show: boolean) => void;
  setShowExteriorWalls: (show: boolean) => void;
  setProjection: (projection: Projection) => void;
  setSection: (section: Partial<ViewerState["section"]>) => void;
  setViewMode: (viewMode: ViewMode) => void;
  setPlanLevel: (levelId: string | null) => void;
  /** Back to defaults for a newly loaded model; the 3D / plan choice is kept. */
  reset: () => void;
}

const INITIAL = {
  levelFilter: "all" as LevelFilter,
  showRoof: true,
  showExteriorWalls: true,
  projection: "perspective" as Projection,
  section: { enabled: false, height: 1.2 },
  cameraRequest: null as CameraRequest | null,
  planLevelId: null as string | null,
};

let nonce = 0;

export const useViewerStore = create<ViewerState>()((set) => ({
  ...INITIAL,
  viewMode: "3d",
  selectFloor: (filter) =>
    set(
      filter === "all"
        ? { levelFilter: "all" }
        : { levelFilter: filter, cameraRequest: request(`level:${filter}`) },
    ),
  setLevelFilter: (levelFilter) => set({ levelFilter }),
  requestCamera: (preset, animate = true) => set({ cameraRequest: request(preset, animate) }),
  setShowRoof: (showRoof) => set({ showRoof }),
  setShowExteriorWalls: (showExteriorWalls) => set({ showExteriorWalls }),
  setProjection: (projection) => set({ projection }),
  setSection: (section) => set((s) => ({ section: { ...s.section, ...section } })),
  setViewMode: (viewMode) => set({ viewMode }),
  setPlanLevel: (planLevelId) => set({ planLevelId }),
  reset: () => set({ ...INITIAL, cameraRequest: request("exterior", false) }),
}));

function request(preset: CameraPresetId, animate = true): CameraRequest {
  nonce += 1;
  return { preset, nonce, animate };
}
