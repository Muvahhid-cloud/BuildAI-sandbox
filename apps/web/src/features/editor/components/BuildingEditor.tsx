"use client";

import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import { type RefObject, useEffect, useRef, useState } from "react";

import { IconButton, Kbd, Tooltip } from "@/components/ui";
import type { SceneGraph } from "@/engine/scene/build-scene";
import type { DrawingInfo } from "@/features/drawing/components/DrawingDownloads";
import { PlanView } from "@/features/drawing/components/PlanView";
import type { Version } from "@/lib/api/schemas";
import { cn } from "@/lib/cn";
import { useRevealStore } from "@/stores/reveal-store";
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
  const assembling = useRevealStore((s) => s.phase === "assembling" && s.mode === "build");
  // An open drawer covers the right part of the viewport: the floating toolbar keeps to the
  // part that is still visible (re-centred there, wrapping if it has to).
  const viewport = useRef<HTMLDivElement>(null);
  const overlap = useDrawerOverlap(viewport);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        // Esc first skips a running build animation, otherwise it clears the selection.
        const reveal = useRevealStore.getState();
        if (reveal.phase === "assembling") reveal.dispatch({ type: "skip" });
        else select(null);
      }
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
        <div ref={viewport} className="relative min-h-0 flex-1 bg-bg-subtle">
          <div className="absolute inset-0">
            {viewMode === "plan" ? (
              <PlanView index={scene.index} onEditsSaved={onEditsSaved} />
            ) : (
              <BuildingViewer scene={scene} />
            )}
          </div>
          {assembling && viewMode === "3d" && (
            <button
              type="button"
              aria-label="Skip the build animation"
              onClick={() => useRevealStore.getState().dispatch({ type: "skip" })}
              className="absolute inset-0 z-[5] flex cursor-pointer items-start justify-center bg-transparent pt-4"
            >
              <span className="glass flex animate-fade-in items-center gap-1.5 rounded-full px-3 py-1 text-xs text-fg-muted shadow-md">
                Click or <Kbd>Esc</Kbd> to skip
              </span>
            </button>
          )}
          <div className="pointer-events-none absolute inset-y-0 left-0" style={{ right: overlap }}>
            <ViewerToolbar scene={scene} drawing={drawing} />
          </div>
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

/**
 * How many pixels of `target`'s right side an open drawer (`[data-drawer]`) covers. Follows the
 * drawer opening and closing and both elements resizing; 0 where layout cannot be measured.
 */
function useDrawerOverlap(target: RefObject<HTMLElement | null>): number {
  const [overlap, setOverlap] = useState(0);
  useEffect(() => {
    const el = target.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const drawer = document.querySelector<HTMLElement>("[data-drawer]");
      const area = el.getBoundingClientRect();
      // The drawer is anchored to the right edge of its host and slides in with a transform:
      // use its layout width, not its animated position.
      const host = drawer?.offsetParent?.getBoundingClientRect();
      const covered = drawer && host ? area.right - (host.right - drawer.offsetWidth) : 0;
      setOverlap(Math.round(Math.min(Math.max(covered, 0), Math.max(area.width - 160, 0))));
    };
    const resize = new ResizeObserver(measure);
    resize.observe(el);
    // Drawers are mounted and unmounted next to the editor: watch for them.
    const root = el.closest("[data-drawer-host]") ?? document.body;
    const mutation = new MutationObserver(() => {
      const drawer = document.querySelector<HTMLElement>("[data-drawer]");
      if (drawer) resize.observe(drawer);
      measure();
    });
    mutation.observe(root, { childList: true, subtree: false });
    window.addEventListener("resize", measure);
    measure();
    return () => {
      resize.disconnect();
      mutation.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [target]);
  return overlap;
}
