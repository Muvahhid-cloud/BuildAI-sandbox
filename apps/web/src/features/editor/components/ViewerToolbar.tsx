"use client";

import type { SceneGraph } from "@/engine/scene/build-scene";
import type { CameraPresetId } from "@/engine/scene/camera-presets";
import { DrawingDownloads, type DrawingInfo } from "@/features/drawing/components/DrawingDownloads";
import { useBuildingStore } from "@/stores/building-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";

import { SegmentButton } from "./panel-ui";

export function ViewerToolbar({ scene, drawing }: { scene: SceneGraph; drawing: DrawingInfo }) {
  const requestCamera = useViewerStore((s) => s.requestCamera);
  const projection = useViewerStore((s) => s.projection);
  const setProjection = useViewerStore((s) => s.setProjection);
  const viewMode = useViewerStore((s) => s.viewMode);
  const setViewMode = useViewerStore((s) => s.setViewMode);
  const planLevelId = useViewerStore((s) => s.planLevelId);
  const setPlanLevel = useViewerStore((s) => s.setPlanLevel);
  const effects = useViewerStore((s) => s.effects);
  const setEffects = useViewerStore((s) => s.setEffects);
  const showGrid = useViewerStore((s) => s.showGrid);
  const setShowGrid = useViewerStore((s) => s.setShowGrid);
  const selectedId = useSelectionStore((s) => s.selectedId);
  const buildMs = useBuildingStore((s) => s.buildMs);
  const selected = selectedId ? scene.index.elementsById.get(selectedId) : undefined;
  const levels = scene.index.levels;
  const planLevel = levels.find((l) => l.id === planLevelId) ?? levels[0];

  const presets: [CameraPresetId, string][] = [
    ["exterior", "Exterior"],
    ["front", "Front"],
    ["rear", "Rear"],
    ["top", "Top"],
    ...levels.map((l) => [`level:${l.id}`, l.name] as [CameraPresetId, string]),
    ["interior", "Interior"],
  ];

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-neutral-200 bg-white px-3 py-2 dark:border-neutral-800 dark:bg-neutral-950">
      <div className="flex items-center gap-1" role="group" aria-label="View mode">
        <SegmentButton active={viewMode === "3d"} onClick={() => setViewMode("3d")}>
          3D model
        </SegmentButton>
        <SegmentButton active={viewMode === "plan"} onClick={() => setViewMode("plan")}>
          Floor plan
        </SegmentButton>
      </div>
      {viewMode === "plan" ? (
        <>
          <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Plan level">
            <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
              Floor
            </span>
            {levels.map((l) => (
              <SegmentButton
                key={l.id}
                active={l.id === planLevel?.id}
                onClick={() => setPlanLevel(l.id)}
              >
                {l.name}
              </SegmentButton>
            ))}
          </div>
          <DrawingDownloads index={scene.index} info={drawing} />
        </>
      ) : (
        <>
          <div
            className="flex flex-wrap items-center gap-1"
            role="group"
            aria-label="Camera presets"
          >
            <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
              View
            </span>
            {presets.map(([id, label]) => (
              <SegmentButton key={id} onClick={() => requestCamera(id)}>
                {label}
              </SegmentButton>
            ))}
            <SegmentButton
              onClick={() => requestCamera("exterior")}
              title="Reset camera to the default exterior view"
            >
              Reset view
            </SegmentButton>
          </div>
          <div className="flex items-center gap-1" role="group" aria-label="Projection">
            <SegmentButton
              active={projection === "perspective"}
              onClick={() => setProjection("perspective")}
            >
              Perspective
            </SegmentButton>
            <SegmentButton
              active={projection === "orthographic"}
              onClick={() => setProjection("orthographic")}
            >
              Orthographic
            </SegmentButton>
          </div>
          <div className="flex items-center gap-1" role="group" aria-label="Display">
            <SegmentButton
              active={effects}
              onClick={() => setEffects(!effects)}
              title="Ambient occlusion and anti-aliasing (turn off on slow devices)"
            >
              Effects
            </SegmentButton>
            <SegmentButton
              active={showGrid}
              onClick={() => setShowGrid(!showGrid)}
              title="Reference grid (1 m cells, 5 m sections)"
            >
              Grid
            </SegmentButton>
          </div>
        </>
      )}
      <p className="ml-auto text-xs tabular-nums text-neutral-500" aria-live="polite">
        {selected ? (
          <>
            Selected{" "}
            <span className="font-medium text-neutral-800 dark:text-neutral-100">
              {selected.name}
            </span>{" "}
            · Esc to clear ·{" "}
          </>
        ) : viewMode === "plan" ? (
          "Click to select · drag to pan · scroll to zoom · "
        ) : (
          "Drag to orbit · right-drag to pan · scroll to zoom · "
        )}
        {scene.stats.elements} elements
        {viewMode === "3d" && (
          <>
            {" "}
            · {scene.stats.meshes} meshes · {Math.round(scene.stats.triangles / 1000)}k triangles
            {buildMs !== null && ` · built in ${Math.round(buildMs)} ms`}
          </>
        )}
      </p>
    </div>
  );
}
