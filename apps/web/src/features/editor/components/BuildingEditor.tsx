"use client";

import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import { useEffect } from "react";

import { IconButton, Kbd, Tooltip } from "@/components/ui";
import type { SceneGraph } from "@/engine/scene/build-scene";
import type { DrawingInfo } from "@/features/drawing/components/DrawingDownloads";
import { PlanView } from "@/features/drawing/components/PlanView";
import type { Version } from "@/lib/api/schemas";
import { cn } from "@/lib/cn";
import { useSelectionStore } from "@/stores/selection-store";
import { useUIStore } from "@/stores/ui-store";
import { useViewerStore } from "@/stores/viewer-store";
import { BuildingViewer } from "@/viewer/BuildingViewer";

import { LeftPanel } from "./LeftPanel";
import { PropertiesPanel } from "./PropertiesPanel";
import { ViewerStatus, ViewerToolbar } from "./ViewerToolbar";

const PANEL = "border-line bg-surface";

/** Typing in a field must never trigger an editor shortcut. */
function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
}

/**
 * Editor layout. Large screens: controls (left) · 3D viewport or floor plan (center) ·
 * properties (right); both side panels collapse ([ and ]). The view tools float over the
 * viewport, hints and counts sit in the status bar under it. Narrow screens: the viewport
 * comes first, panels stack below. 3D and plan are two renderings of the same BuildingModel.
 */
export function BuildingEditor({
  scene,
  drawing,
  onEditsSaved,
}: {
  scene: SceneGraph;
  drawing: DrawingInfo;
  /** A plan-editing session was saved as this new version (project editor only). */
  onEditsSaved?: (version: Version) => void;
}) {
  const select = useSelectionStore((s) => s.select);
  const viewMode = useViewerStore((s) => s.viewMode);
  const left = useUIStore((s) => s.left);
  const right = useUIStore((s) => s.right);
  const toggle = useUIStore((s) => s.toggle);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") select(null);
      if (isTyping(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "[") toggle("left");
      if (e.key === "]") toggle("right");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [select, toggle]);

  return (
    <div className="flex flex-1 flex-col lg:min-h-[480px] lg:flex-row lg:overflow-hidden">
      <div className="order-1 flex h-[72vh] min-h-[360px] min-w-0 flex-col lg:order-2 lg:h-auto lg:flex-1">
        <div className="relative min-h-0 flex-1 bg-bg-subtle">
          <div className="absolute inset-0">
            {viewMode === "plan" ? (
              <PlanView index={scene.index} onEditsSaved={onEditsSaved} />
            ) : (
              <BuildingViewer scene={scene} />
            )}
          </div>
          <ViewerToolbar scene={scene} drawing={drawing} />
        </div>
        <div className="flex h-8 shrink-0 items-center gap-2 border-t border-line bg-surface px-1.5">
          <span className="hidden lg:inline-flex">
            <Tooltip
              content={
                <>
                  {left ? "Hide" : "Show"} the left panel <Kbd>[</Kbd>
                </>
              }
            >
              <IconButton
                label={left ? "Hide the left panel" : "Show the left panel"}
                title=""
                size="sm"
                pressed={left}
                onClick={() => toggle("left")}
              >
                {left ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}
              </IconButton>
            </Tooltip>
          </span>
          <ViewerStatus scene={scene} />
          <span className="hidden lg:inline-flex">
            <Tooltip
              align="end"
              content={
                <>
                  {right ? "Hide" : "Show"} the properties panel <Kbd>]</Kbd>
                </>
              }
            >
              <IconButton
                label={right ? "Hide the properties panel" : "Show the properties panel"}
                title=""
                size="sm"
                pressed={right}
                onClick={() => toggle("right")}
              >
                {right ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
              </IconButton>
            </Tooltip>
          </span>
        </div>
      </div>
      <aside
        aria-label="Model controls"
        className={cn(
          "order-2 border-t lg:order-1 lg:w-56 lg:shrink-0 lg:overflow-y-auto lg:border-r lg:border-t-0 xl:w-60",
          PANEL,
          !left && "lg:hidden",
        )}
      >
        <LeftPanel index={scene.index} sectionMax={Math.max(1, Math.ceil(scene.bounds.max.z))} />
      </aside>
      <aside
        aria-label="Inspector"
        className={cn(
          "order-3 border-t lg:w-72 lg:shrink-0 lg:overflow-y-auto lg:border-l lg:border-t-0 xl:w-80",
          PANEL,
          !right && "lg:hidden",
        )}
      >
        <PropertiesPanel index={scene.index} />
      </aside>
    </div>
  );
}
