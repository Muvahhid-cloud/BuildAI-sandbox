"use client";

import { Box, Grid3x3, Map, RotateCcw, Sparkles, Trees, Wand2 } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Kbd } from "@/components/ui";
import type { SceneGraph } from "@/engine/scene/build-scene";
import type { CameraPresetId } from "@/engine/scene/camera-presets";
import { DrawingDownloads, type DrawingInfo } from "@/features/drawing/components/DrawingDownloads";
import { useBuildingStore } from "@/stores/building-store";
import { prefersReducedMotion, useRevealStore } from "@/stores/reveal-store";
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
  const showSite = useViewerStore((s) => s.showSite);
  const setShowSite = useViewerStore((s) => s.setShowSite);
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
    <div
      role="toolbar"
      aria-label="View tools"
      className="pointer-events-none absolute inset-x-3 bottom-3 z-10 flex flex-wrap items-end justify-center gap-2"
    >
      <Group label="View mode">
        <SegmentButton active={viewMode === "3d"} onClick={() => setViewMode("3d")}>
          <Box size={13} aria-hidden />
          3D model
        </SegmentButton>
        <SegmentButton active={viewMode === "plan"} onClick={() => setViewMode("plan")}>
          <Map size={13} aria-hidden />
          Floor plan
        </SegmentButton>
      </Group>
      {viewMode === "plan" ? (
        <>
          <Group label="Plan level" caption="Floor">
            {levels.map((l) => (
              <SegmentButton
                key={l.id}
                active={l.id === planLevel?.id}
                onClick={() => setPlanLevel(l.id)}
              >
                {l.name}
              </SegmentButton>
            ))}
          </Group>
          <div className="glass pointer-events-auto rounded-xl p-1 shadow-md">
            <DrawingDownloads index={scene.index} info={drawing} />
          </div>
        </>
      ) : (
        <>
          <Group label="Camera presets" caption="View">
            {presets.map(([id, label]) => (
              <SegmentButton key={id} onClick={() => requestCamera(id)}>
                {label}
              </SegmentButton>
            ))}
            <SegmentButton
              onClick={() => requestCamera("exterior")}
              title="Reset camera to the default exterior view"
            >
              <RotateCcw size={12} aria-hidden />
              Reset view
            </SegmentButton>
          </Group>
          <Group label="Projection">
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
          </Group>
          <Group label="Display">
            <SegmentButton
              active={effects}
              onClick={() => setEffects(!effects)}
              title="Ambient occlusion and anti-aliasing (turn off on slow devices)"
            >
              <Sparkles size={12} aria-hidden />
              Effects
            </SegmentButton>
            <SegmentButton
              active={showGrid}
              onClick={() => setShowGrid(!showGrid)}
              title="Reference grid (1 m cells, 5 m sections)"
            >
              <Grid3x3 size={12} aria-hidden />
              Grid
            </SegmentButton>
            <SegmentButton
              active={showSite}
              onClick={() => setShowSite(!showSite)}
              title="Site context: path, driveway, fence, trees and shrubs (not part of the model)"
            >
              <Trees size={12} aria-hidden />
              Site
            </SegmentButton>
            <ReplayButton />
          </Group>
        </>
      )}
    </div>
  );
}

/** Plays the build reveal of the shown model again (off with reduced motion). */
function ReplayButton() {
  const playing = useRevealStore((s) => s.phase === "assembling");
  const [reduced] = useState(prefersReducedMotion);
  return (
    <button
      type="button"
      aria-label="Replay build animation"
      title={
        reduced
          ? "Replay build animation (off: your system asks for reduced motion)"
          : "Replay build animation"
      }
      disabled={reduced || playing}
      onClick={() => useRevealStore.getState().play("build")}
      className="inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs font-medium text-fg-muted transition-colors duration-150 hover:bg-black/5 hover:text-fg disabled:opacity-50 dark:hover:bg-white/10"
    >
      <Wand2 size={12} aria-hidden />
      Replay
    </button>
  );
}

/** One floating glass group of the view toolbar. */
function Group({
  label,
  caption,
  children,
}: {
  label: string;
  caption?: string;
  children: ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="glass pointer-events-auto flex flex-wrap items-center gap-0.5 rounded-xl p-1 shadow-md"
    >
      {caption && (
        <span className="px-1.5 text-2xs font-semibold uppercase tracking-wider text-fg-subtle">
          {caption}
        </span>
      )}
      {children}
    </div>
  );
}

/** Status bar text under the viewport: selection, pointer hints with keys, model counts. */
export function ViewerStatus({ scene }: { scene: SceneGraph }) {
  const viewMode = useViewerStore((s) => s.viewMode);
  const selectedId = useSelectionStore((s) => s.selectedId);
  const buildMs = useBuildingStore((s) => s.buildMs);
  const selected = selectedId ? scene.index.elementsById.get(selectedId) : undefined;
  return (
    <p
      className="flex min-w-0 flex-1 items-center gap-x-1.5 overflow-hidden whitespace-nowrap text-xs tabular-nums text-fg-subtle"
      aria-live="polite"
    >
      <span className="min-w-0 truncate">
        {selected ? (
          <>
            Selected <span className="font-medium text-fg">{selected.name}</span> · <Kbd>Esc</Kbd>{" "}
            to clear ·{" "}
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
      </span>
      <span className="ml-auto hidden shrink-0 items-center gap-1 xl:inline-flex">
        <Kbd>[</Kbd>
        <Kbd>]</Kbd> panels
      </span>
    </p>
  );
}
