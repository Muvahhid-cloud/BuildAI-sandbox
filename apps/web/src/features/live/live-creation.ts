// Live creation (docs/3d-engine.md §25, docs/ai-pipeline.md §6.1): one description of the
// design that is being made right now — an AI generation or a spec-form job — and the hook
// that drives the canvas from it: the waiting sheet while the backend works, the facts the AI
// has stated, the laid-out model as soon as the layout stage is done (before it is saved),
// and the failure path. Everything shown comes from the backend's real state.
import { type AIGenerationOut, type InterimFact, previewModelSchema } from "@buildai/schema";
import { useCallback, useEffect, useRef, useState } from "react";

import { apiRequest } from "@/lib/api/client";
import type { Job } from "@/lib/api/schemas";
import { useBuildingStore } from "@/stores/building-store";
import { useRevealStore } from "@/stores/reveal-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";
import { plotFor } from "@/viewer/reveal/waiting";
import { REVEAL } from "@/viewer/render-settings";

import { AI_STAGES } from "../ai/api";
import { GENERATION_STAGES } from "../generation/api";

export interface LiveCreation {
  /** The generation or job id. */
  key: string;
  status: "running" | "completed" | "failed" | "needs_clarification";
  /** Position of the backend's real stage (a change is one pulse of the waiting sheet). */
  stageIndex: number;
  /** What the AI has stated so far (interim; display only). */
  facts: readonly InterimFact[];
  /** Set while the laid-out model can be fetched from `previewPath`, before it is saved. */
  previewHash: string | null;
  previewPath: string;
  /** The version the creation produced (once completed). */
  versionId: string | null;
}

const NO_FACTS: readonly InterimFact[] = [];

export function liveFromGeneration(g: AIGenerationOut): LiveCreation {
  return {
    key: g.id,
    status: g.status === "queued" ? "running" : g.status,
    stageIndex: Math.max(
      AI_STAGES.findIndex((s) => s.id === g.stage),
      0,
    ),
    facts: g.interim_facts ?? NO_FACTS,
    previewHash: g.preview_model_hash ?? null,
    previewPath: `/ai/generations/${encodeURIComponent(g.id)}/preview`,
    versionId: g.status === "completed" ? (g.version_id ?? null) : null,
  };
}

export function liveFromJob(job: Job): LiveCreation {
  const version = job.status === "succeeded" ? job.result?.version_id : null;
  return {
    key: job.id,
    status:
      job.status === "succeeded" ? "completed" : job.status === "failed" ? "failed" : "running",
    stageIndex: Math.max(
      GENERATION_STAGES.findIndex((s) => s.id === job.stage),
      0,
    ),
    facts: NO_FACTS,
    previewHash: job.preview_model_hash ?? null,
    previewPath: `/jobs/${encodeURIComponent(job.id)}/preview`,
    versionId: typeof version === "string" ? version : null,
  };
}

const factNumber = (facts: readonly InterimFact[], key: string): number | null => {
  const value = facts.find((f) => f.key === key)?.value;
  return typeof value === "number" ? value : null;
};

export interface LiveCreationControl {
  /** A design is being created: the canvas belongs to it. */
  active: boolean;
  /** The id of the creation the canvas belongs to. */
  key: string | null;
  /** Model hash of the laid-out preview that is on screen (null: none shown). */
  shownHash: () => string | null;
  /** The version the creation produced, once the backend has saved it. */
  versionId: () => string | null;
  /** The saved version took over (or was loaded instead): the creation is over. */
  finish: () => void;
}

/**
 * Drives the canvas from `source`. `restore` puts back what was shown before (the open
 * version, or nothing) when the creation fails, needs clarification or is left.
 */
export function useLiveCreation(
  source: LiveCreation | null,
  restore: () => void,
): LiveCreationControl {
  const [active, setActive] = useState<string | null>(null);
  const shown = useRef<string | null>(null);
  const ended = useRef<string | null>(null);
  const lastStatus = useRef<LiveCreation["status"] | null>(null);
  const restoreRef = useRef(restore);
  useEffect(() => {
    restoreRef.current = restore;
  }, [restore]);

  const key = source?.key ?? null;
  const status = source?.status ?? null;
  const stageIndex = source?.stageIndex ?? -1;
  const facts = source?.facts ?? NO_FACTS;
  const previewHash = source?.previewHash ?? null;
  const previewPath = source?.previewPath ?? null;
  const versionId = source?.versionId ?? null;
  const version = useRef<string | null>(null);

  const stop = useCallback((putBack: boolean) => {
    shown.current = null;
    setActive((current) => {
      if (current !== null) ended.current = current;
      return null;
    });
    useRevealStore.getState().setPlot(null);
    if (putBack) restoreRef.current();
  }, []);

  // A creation starts: the canvas shows the empty site and the waiting sheet.
  useEffect(() => {
    if (key === null || status !== "running" || active === key || ended.current === key) return;
    shown.current = null;
    lastStatus.current = "running";
    version.current = null;
    useSelectionStore.getState().select(null);
    useBuildingStore.getState().clear();
    useViewerStore.getState().reset();
    useViewerStore.getState().setViewMode("3d");
    const reveal = useRevealStore.getState();
    reveal.dispatch({ type: "reset" });
    reveal.setPlot(null);
    setActive(key);
  }, [key, status, active]);

  const live = active !== null && active === key;

  // The backend's real stage (never an invented percentage).
  useEffect(() => {
    if (live && status === "running" && shown.current === null) {
      useRevealStore.getState().dispatch({ type: "wait", stageIndex });
    }
  }, [live, status, stageIndex]);

  // What the AI has stated so far; the plot outline is sized from the stated floor area.
  useEffect(() => {
    if (!live) return;
    const reveal = useRevealStore.getState();
    reveal.dispatch({ type: "facts", count: facts.length });
    reveal.setPlot(
      plotFor(factNumber(facts, "floor_area_m2"), factNumber(facts, "storeys"), REVEAL.waiting),
    );
  }, [live, facts]);

  // The layout is done: show the house now, while checking and saving continue.
  useEffect(() => {
    if (!live || previewHash === null || previewPath === null || shown.current !== null) return;
    let cancelled = false;
    apiRequest(previewPath, previewModelSchema)
      .then((preview) => {
        if (cancelled || shown.current !== null) return;
        const building = useBuildingStore.getState();
        building.load(preview.model);
        if (useBuildingStore.getState().status !== "ready") return; // the version decides
        shown.current = preview.model_hash;
        const reveal = useRevealStore.getState();
        reveal.setSeed(preview.model_hash);
        reveal.play("build", undefined, false);
      })
      .catch(() => {
        // Already saved (or failed) meanwhile: the generation's own outcome is shown instead.
      });
    return () => {
      cancelled = true;
    };
  }, [live, previewHash, previewPath]);

  // The creation ended without a version, or was left.
  const phase = useRevealStore((s) => s.phase);
  useEffect(() => {
    if (active === null) return;
    const reveal = useRevealStore.getState();
    const followed = key === active;
    if (followed) {
      lastStatus.current = status;
      version.current = versionId;
    }
    const last = lastStatus.current;
    if (last === "failed") {
      // A house that is on screen fades out first (machine: collapsing -> idle).
      if (reveal.phase !== "collapsing") reveal.dispatch({ type: "fail" });
      if (useRevealStore.getState().phase !== "collapsing") stop(true);
    } else if (last === "needs_clarification" || (!followed && last !== "completed")) {
      // Nothing to build, or the panel that followed the creation was closed. (A completed
      // creation is still waited for: its version takes over through `finish`.)
      reveal.dispatch({ type: "reset" });
      stop(true);
    }
  }, [active, key, status, versionId, phase, stop]);

  return {
    active: active !== null,
    key: active,
    shownHash: () => shown.current,
    versionId: () => version.current,
    finish: () => stop(false),
  };
}
