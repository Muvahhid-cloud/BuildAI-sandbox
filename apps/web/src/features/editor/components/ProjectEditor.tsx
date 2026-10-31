"use client";

import {
  type AIGenerationOut,
  type BuildingSpecification,
  buildingSpecificationSchema,
} from "@buildai/schema";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { materialCache } from "@/engine/materials/material-cache";
import { isTerminal, useAIGeneration } from "@/features/ai/api";
import { AIGeneratorPanel } from "@/features/ai/components/AIGeneratorPanel";
import { StageList } from "@/features/ai/components/AIGenerationStatus";
import { GenerationHistory } from "@/features/ai/components/GenerationHistory";
import { GenerationSummary } from "@/features/ai/components/GenerationSummary";
import { hasUnsavedEdits, useEditStore } from "@/features/editing/store";
import { GenerationPanel } from "@/features/generation/components/GenerationPanel";
import { projectKeys, useProject } from "@/features/projects/api";
import { useImportDemo, useVersion, useVersions, versionKeys } from "@/features/versions/api";
import { ReportPanel } from "@/features/versions/components/ReportPanel";
import { ApiError } from "@/lib/api/errors";
import type { Version } from "@/lib/api/schemas";
import { useBuildingStore } from "@/stores/building-store";
import { useProjectStore } from "@/stores/project-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";

import { BuildingEditor } from "./BuildingEditor";

type Drawer = "none" | "generate" | "report" | "history";
type DesignMode = "ai" | "form";

/**
 * Project editor: shows one version of the project in the Phase 1 viewer. The model comes from
 * the stored version (validated by the generated schema in the building store). New versions
 * come from a natural-language description (AI -> spec -> layout engine) or from the
 * specification form (layout engine directly).
 */
export function ProjectEditor({
  projectId,
  generationId = null,
  onGenerationReleased,
}: {
  projectId: string;
  /** An AI generation to follow (started from the projects dashboard). */
  generationId?: string | null;
  /**
   * Another version than `generationId`'s is now open (saved plan edits, the version menu,
   * history, a new design): the caller drops the generation link (the URL), so that reloading
   * opens the project's latest version instead of the generation's older one.
   */
  onGenerationReleased?: () => void;
}) {
  const project = useProject(projectId);
  const versions = useVersions(projectId);
  const [chosen, setChosen] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<Drawer>("none");
  const [mode, setMode] = useState<DesignMode>("ai");
  const [justGenerated, setJustGenerated] = useState<string | null>(null);
  // The AI generation whose summary is shown over the 3D view (and whose version is opened).
  const [summaryId, setSummaryId] = useState<string | null>(generationId);
  const summary = useAIGeneration(summaryId);
  const summaryVersion =
    summary.data?.status === "completed" ? (summary.data.version_id ?? null) : null;
  const versionId = chosen ?? summaryVersion ?? project.data?.current_version_id ?? null;
  const version = useVersion(projectId, versionId);
  const qc = useQueryClient();
  const unsaved = useEditStore(hasUnsavedEdits);
  const unsavedCount = useEditStore((s) => s.cursor);
  // The version the generation link opens (only known once that generation has completed).
  const linked = useAIGeneration(generationId);
  const linkedVersion =
    linked.data?.status === "completed" ? (linked.data.version_id ?? null) : null;
  const openId = version.data?.id ?? null;

  useEffect(() => {
    if (linkedVersion !== null && openId !== null && openId !== linkedVersion) {
      onGenerationReleased?.();
    }
  }, [linkedVersion, openId, onGenerationReleased]);
  const status = useBuildingStore((s) => s.status);
  const scene = useBuildingStore((s) => s.scene);
  const buildError = useBuildingStore((s) => s.error);

  useEffect(() => {
    const data = version.data;
    if (!data) return;
    useBuildingStore.getState().load(data.model);
    const building = useBuildingStore.getState().index?.model.building;
    useProjectStore.getState().setProject({
      id: projectId,
      name: project.data?.name ?? building?.name ?? "Project",
      source: "project",
      description: building?.description ?? "",
    });
    useSelectionStore.getState().select(null);
    useViewerStore.getState().reset(); // frames the whole building (exterior camera)
    // Plan edits are made on this version (docs/3d-engine.md §20).
    useEditStore.getState().begin(projectId, data);
  }, [version.data, projectId, project.data?.name]);

  // Unsaved plan edits live only in this tab: warn before they are lost.
  useEffect(() => {
    if (!unsaved) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [unsaved]);

  useEffect(
    () => () => {
      useBuildingStore.getState().clear();
      useProjectStore.getState().setProject(null);
      useEditStore.getState().end();
      materialCache.dispose();
    },
    [],
  );

  /** Switch versions, asking first when the plan has unsaved edits. */
  const confirmLeavingEdits = useCallback(
    () =>
      !hasUnsavedEdits(useEditStore.getState()) ||
      window.confirm("Discard the unsaved plan edits?"),
    [],
  );

  const onEditsSaved = useCallback(
    async (saved: Version) => {
      qc.setQueryData(versionKeys.detail(projectId, saved.id), saved);
      setChosen(saved.id);
      setJustGenerated(saved.id);
      setSummaryId(null);
      await Promise.all([
        qc.invalidateQueries({ queryKey: versionKeys.list(projectId) }),
        qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) }),
      ]);
    },
    [qc, projectId],
  );

  const onGenerated = useCallback((id: string) => {
    setChosen(id);
    setJustGenerated(id);
    setSummaryId(null);
    setDrawer("none");
  }, []);

  const onAICompleted = useCallback((generation: AIGenerationOut) => {
    setChosen(generation.version_id ?? null);
    setJustGenerated(null);
    setSummaryId(generation.id);
    setDrawer("none");
  }, []);

  if (project.isPending) return <Centered>Loading project…</Centered>;
  if (project.isError) {
    const notFound = project.error instanceof ApiError && project.error.status === 404;
    return (
      <Centered tone="error">
        {notFound ? "Project not found." : "Could not load the project."}{" "}
        <Link href="/projects" className="underline">
          Back to projects
        </Link>
      </Centered>
    );
  }

  const p = project.data;
  const hasVersions = (versions.data?.length ?? 0) > 0;
  const spec = specOf(version.data);
  const running = summary.data !== undefined && !isTerminal(summary.data);
  const showSummary =
    summary.data?.status === "completed" && version.data?.id === summary.data.version_id;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-neutral-200 px-4 py-2 dark:border-neutral-800">
        <Link href="/projects" className="text-sm text-neutral-500 hover:underline">
          Projects
        </Link>
        <span className="text-neutral-400">/</span>
        <h1 className="font-medium">{p.name}</h1>
        {hasVersions && (
          <select
            aria-label="Version"
            className="rounded-md border border-neutral-300 bg-white px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900"
            value={versionId ?? ""}
            onChange={(e) => {
              if (!confirmLeavingEdits()) return;
              setChosen(e.target.value);
              setJustGenerated(null);
            }}
          >
            {versions.data?.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.number} · {v.label}
                {v.id === p.current_version_id ? " (latest)" : ""}
              </option>
            ))}
          </select>
        )}
        <span className="text-xs text-neutral-500">
          {p.region_code} · {p.currency} · rules {p.rules_profile_id}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <DrawerButton drawer={drawer} value="history" onToggle={setDrawer}>
            History
          </DrawerButton>
          {version.data && (
            <DrawerButton drawer={drawer} value="report" onToggle={setDrawer}>
              Report
              {reportCount(version.data) > 0 && (
                <span className="ml-1 rounded-full bg-amber-100 px-1.5 text-xs text-amber-800">
                  {reportCount(version.data)}
                </span>
              )}
            </DrawerButton>
          )}
          {hasVersions && (
            <button
              type="button"
              onClick={() => setDrawer(drawer === "generate" ? "none" : "generate")}
              aria-pressed={drawer === "generate"}
              className="rounded-md bg-blue-600 px-3 py-1 text-sm font-semibold text-white hover:bg-blue-700"
            >
              New design
            </button>
          )}
        </div>
      </div>

      {justGenerated && version.data?.id === justGenerated && (
        <GeneratedBanner
          version={version.data}
          onReport={() => setDrawer("report")}
          onDismiss={() => setJustGenerated(null)}
        />
      )}

      <div className="relative flex min-h-0 flex-1 flex-col">
        {versions.isPending ? (
          <Centered>Loading versions…</Centered>
        ) : !hasVersions ? (
          <StartView
            projectId={projectId}
            currency={p.currency}
            mode={mode}
            onMode={setMode}
            generationId={summaryId}
            onGenerated={onGenerated}
            onAICompleted={onAICompleted}
          />
        ) : version.isError ? (
          <Centered tone="error">Could not load this version.</Centered>
        ) : status === "error" ? (
          <Centered tone="error">
            <span className="block font-medium">The building model is invalid</span>
            <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap text-xs">
              {buildError}
            </pre>
          </Centered>
        ) : !scene || !version.data ? (
          <Centered>Building the 3D model…</Centered>
        ) : (
          <BuildingEditor
            scene={scene}
            onEditsSaved={(v) => void onEditsSaved(v)}
            drawing={{
              projectName: p.name,
              versionLabel: drawingVersionLabel(version.data, unsavedCount),
            }}
          />
        )}

        {hasVersions && (showSummary || running) && summary.data && (
          <div className="pointer-events-none absolute right-3 top-3 z-10 flex justify-end lg:right-[19rem] xl:right-[21rem]">
            <div className="pointer-events-auto">
              {showSummary ? (
                <GenerationSummary
                  generation={summary.data}
                  onDismiss={() => setSummaryId(null)}
                  onOpenReport={() => setDrawer("report")}
                />
              ) : (
                <div className="w-[min(92vw,360px)] rounded-xl border border-neutral-200 bg-white/95 p-4 shadow-xl dark:border-neutral-800 dark:bg-neutral-950/95">
                  <StageList generation={summary.data} />
                </div>
              )}
            </div>
          </div>
        )}

        {drawer !== "none" && (
          <aside
            aria-label={
              drawer === "generate"
                ? "Generate a new design"
                : drawer === "history"
                  ? "Generation history"
                  : "Design report"
            }
            className="absolute inset-y-0 right-0 z-20 flex w-full max-w-[520px] flex-col border-l border-neutral-200 bg-white shadow-xl dark:border-neutral-800 dark:bg-neutral-950"
          >
            {drawer === "generate" ? (
              <>
                <ModeTabs mode={mode} onMode={setMode} />
                <div className="min-h-0 flex-1">
                  {mode === "ai" ? (
                    <AIGeneratorPanel
                      projectId={projectId}
                      currency={p.currency}
                      onCompleted={onAICompleted}
                      onClose={() => setDrawer("none")}
                    />
                  ) : (
                    <GenerationPanel
                      projectId={projectId}
                      initialSpec={spec}
                      onGenerated={onGenerated}
                      onClose={() => setDrawer("none")}
                    />
                  )}
                </div>
              </>
            ) : drawer === "history" ? (
              <GenerationHistory
                projectId={projectId}
                onClose={() => setDrawer("none")}
                onOpen={(g) => {
                  if (!confirmLeavingEdits()) return;
                  setChosen(g.version_id);
                  setSummaryId(g.id);
                  setDrawer("none");
                }}
              />
            ) : version.data ? (
              <ReportPanel version={version.data} onClose={() => setDrawer("none")} />
            ) : null}
          </aside>
        )}
      </div>
    </div>
  );
}

function DrawerButton({
  drawer,
  value,
  onToggle,
  children,
}: {
  drawer: Drawer;
  value: Drawer;
  onToggle: (drawer: Drawer) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={() => onToggle(drawer === value ? "none" : value)}
      aria-pressed={drawer === value}
      className="rounded-md px-3 py-1 text-sm text-neutral-700 hover:bg-neutral-100 dark:text-neutral-200 dark:hover:bg-neutral-800"
    >
      {children}
    </button>
  );
}

function ModeTabs({ mode, onMode }: { mode: DesignMode; onMode: (mode: DesignMode) => void }) {
  const tab = (value: DesignMode, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === value}
      onClick={() => onMode(value)}
      className={
        "border-b-2 px-3 py-2 text-sm " +
        (mode === value
          ? "border-blue-600 font-medium text-blue-700 dark:text-blue-400"
          : "border-transparent text-neutral-500 hover:text-neutral-800")
      }
    >
      {label}
    </button>
  );
  return (
    <div
      role="tablist"
      aria-label="How to create the design"
      className="flex gap-1 border-b border-neutral-200 px-3 dark:border-neutral-800"
    >
      {tab("ai", "Describe with AI")}
      {tab("form", "Specification form")}
    </div>
  );
}

function specOf(version: Version | undefined): BuildingSpecification | null {
  if (!version?.spec) return null;
  const parsed = buildingSpecificationSchema.safeParse(version.spec);
  return parsed.success ? parsed.data : null;
}

/** Title-block label of a drawing: the version, and the plan edits not saved yet. */
export function drawingVersionLabel(
  version: Pick<Version, "number" | "label">,
  unsaved = 0,
): string {
  const base = `v${version.number} · ${version.label}`;
  return unsaved > 0 ? `${base} + ${unsaved} unsaved change${unsaved > 1 ? "s" : ""}` : base;
}

function reportCount(version: Version): number {
  const deviations = version.report?.warnings.filter((w) => !w.rule_ref).length ?? 0;
  return deviations + version.issues.length;
}

function StartView({
  projectId,
  currency,
  mode,
  onMode,
  generationId,
  onGenerated,
  onAICompleted,
}: {
  projectId: string;
  currency: string;
  mode: DesignMode;
  onMode: (mode: DesignMode) => void;
  generationId: string | null;
  onGenerated: (versionId: string) => void;
  onAICompleted: (generation: AIGenerationOut) => void;
}) {
  const importDemo = useImportDemo(projectId);
  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <div className="flex min-h-0 flex-1 flex-col border-neutral-200 lg:max-w-[560px] lg:border-r dark:border-neutral-800">
        <ModeTabs mode={mode} onMode={onMode} />
        <div className="min-h-0 flex-1">
          {mode === "ai" ? (
            <AIGeneratorPanel
              projectId={projectId}
              currency={currency}
              initialGenerationId={generationId}
              onCompleted={onAICompleted}
            />
          ) : (
            <GenerationPanel projectId={projectId} onGenerated={onGenerated} />
          )}
        </div>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center gap-4 bg-gradient-to-br from-neutral-50 to-blue-50 p-8 text-center dark:from-neutral-900 dark:to-neutral-950">
        <p className="max-w-md text-sm text-neutral-600 dark:text-neutral-300">
          This project has no design yet. Describe the house you want and the building appears here
          as an interactive 3D model — every wall, room, door and window is a real, selectable
          object. Each generation is saved as a new version.
        </p>
        <button
          type="button"
          onClick={() => importDemo.mutate(undefined, { onSuccess: (v) => onGenerated(v.id) })}
          disabled={importDemo.isPending}
          className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm hover:bg-white disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          {importDemo.isPending ? "Importing…" : "Or import the hand-authored demo house"}
        </button>
        {importDemo.isError && (
          <p role="alert" className="text-sm text-red-600">
            {importDemo.error.message}
          </p>
        )}
      </div>
    </div>
  );
}

function GeneratedBanner({
  version,
  onReport,
  onDismiss,
}: {
  version: Version;
  onReport: () => void;
  onDismiss: () => void;
}) {
  const s = version.summary;
  const count = reportCount(version);
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-green-200 bg-green-50 px-4 py-2 text-sm text-green-900 dark:border-green-900 dark:bg-green-950 dark:text-green-200"
    >
      <span className="font-semibold">
        {version.source === "manual" ? "Saved" : "Generated"} v{version.number}
      </span>
      <span className="tabular-nums">
        {s.storeys} floor{s.storeys > 1 ? "s" : ""} · {s.gross_floor_area_m2} m² · {s.rooms} rooms ·{" "}
        {s.bedrooms} bedrooms · {s.bathrooms} bathrooms
      </span>
      {count > 0 && (
        <button type="button" onClick={onReport} className="underline">
          {count} note{count > 1 ? "s" : ""} to review
        </button>
      )}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="ml-auto text-green-700 hover:text-green-900"
      >
        ×
      </button>
    </div>
  );
}

function Centered({ children, tone }: { children: React.ReactNode; tone?: "error" }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div
        role={tone === "error" ? "alert" : "status"}
        className={"max-w-xl text-sm " + (tone === "error" ? "text-red-600" : "text-neutral-500")}
      >
        {children}
      </div>
    </div>
  );
}
