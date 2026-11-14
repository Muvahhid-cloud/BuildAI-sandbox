"use client";

import {
  type AIGenerationOut,
  type BuildingSpecification,
  buildingSpecificationSchema,
} from "@buildai/schema";
import { useQueryClient } from "@tanstack/react-query";
import {
  Box,
  ChevronRight,
  CircleCheck,
  ClipboardList,
  GitBranch,
  GitCompareArrows,
  History,
  Plus,
  Wand2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  Badge,
  Button,
  Drawer,
  IconButton,
  Select,
  Skeleton,
  Spinner,
  Tabs,
  toast,
} from "@/components/ui";
import { materialCache } from "@/engine/materials/material-cache";
import { isTerminal, useAIGeneration } from "@/features/ai/api";
import { AIGeneratorPanel } from "@/features/ai/components/AIGeneratorPanel";
import { StageList } from "@/features/ai/components/AIGenerationStatus";
import { GenerationHistory } from "@/features/ai/components/GenerationHistory";
import { GenerationSummary } from "@/features/ai/components/GenerationSummary";
import { hasUnsavedEdits, useEditStore } from "@/features/editing/store";
import { GenerationPanel } from "@/features/generation/components/GenerationPanel";
import {
  type LiveCreation,
  liveFromGeneration,
  liveFromJob,
  useLiveCreation,
} from "@/features/live/live-creation";
import { ComparePanel } from "@/features/modification/components/ComparePanel";
import { ModifyPanel } from "@/features/modification/components/ModifyPanel";
import { projectKeys, useProject } from "@/features/projects/api";
import { useImportDemo, useVersion, useVersions, versionKeys } from "@/features/versions/api";
import { ReportPanel } from "@/features/versions/components/ReportPanel";
import { ApiError } from "@/lib/api/errors";
import type { Job, Version } from "@/lib/api/schemas";
import { useBuildingStore } from "@/stores/building-store";
import { useHighlightStore } from "@/stores/highlight-store";
import { useRevealStore } from "@/stores/reveal-store";
import { useProjectStore } from "@/stores/project-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";

import { RevealSurface } from "@/viewer/reveal/RevealSurface";
import { ViewerHost, ViewerSlot } from "@/viewer/ViewerHost";

import { BuildingEditor } from "./BuildingEditor";

type Drawer = "none" | "generate" | "report" | "history" | "modify" | "compare";
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
  // Live creation (docs/3d-engine.md §25): the design that is being made right now, as the
  // panel that follows it reports it — or the generation opened from the dashboard link.
  const [liveGeneration, setLiveGeneration] = useState<AIGenerationOut | null>(null);
  const [formJob, setFormJob] = useState<Job | null>(null);
  // After "Apply" in Modify with AI: the version whose changed elements grow again.
  const [pendingReveal, setPendingReveal] = useState<PendingReveal | null>(null);
  // The version-load effect reads the pending reveal without depending on it.
  const pendingRef = useRef<PendingReveal | null>(null);
  const playedRef = useRef<PendingReveal | null>(null);
  useEffect(() => {
    pendingRef.current = pendingReveal;
  }, [pendingReveal]);
  const queueReveal = setPendingReveal;
  // The summary card and the banner wait for the construction to end (they would cover it).
  const revealing = useRevealStore((s) => s.phase === "assembling" && s.mode === "build");
  const status = useBuildingStore((s) => s.status);
  const scene = useBuildingStore((s) => s.scene);
  const buildError = useBuildingStore((s) => s.error);

  // A generation followed from the dashboard link is live from the moment it is seen running
  // on this page (state adjusted during render: no effect, no extra commit).
  const [followedSummary, setFollowedSummary] = useState<string | null>(null);
  if (summary.data && !isTerminal(summary.data) && followedSummary !== summary.data.id) {
    setFollowedSummary(summary.data.id);
  }
  const source: LiveCreation | null = liveGeneration
    ? liveFromGeneration(liveGeneration)
    : formJob
      ? liveFromJob(formJob)
      : summary.data && summary.data.id === followedSummary
        ? liveFromGeneration(summary.data)
        : null;

  const projectNameRef = useRef<string | null>(null);
  useEffect(() => {
    projectNameRef.current = project.data?.name ?? null;
  }, [project.data?.name]);
  const versionRef = useRef<Version | null>(null);

  /** Shows a stored version: the model, the camera on the whole building, the edit session. */
  const openVersion = useCallback(
    (data: Version, load: boolean) => {
      if (load) {
        useBuildingStore.getState().load(data.model);
        useSelectionStore.getState().select(null);
        useViewerStore.getState().reset(); // frames the whole building (exterior camera)
      }
      const building = useBuildingStore.getState().index?.model.building;
      useProjectStore.getState().setProject({
        id: projectId,
        name: projectNameRef.current ?? building?.name ?? "Project",
        source: "project",
        description: building?.description ?? "",
      });
      // Plan edits are made on this version (docs/3d-engine.md §20).
      useEditStore.getState().begin(projectId, data);
      // The construction is seeded by the model hash: the same model, the same animation.
      useRevealStore.getState().setSeed(data.model_hash);
    },
    [projectId],
  );

  // A creation that fails, needs clarification or is left: back to what was open before.
  const restore = useCallback(() => {
    const data = versionRef.current;
    if (data) openVersion(data, true);
    else useBuildingStore.getState().clear();
  }, [openVersion]);
  const live = useLiveCreation(source, restore);
  const liveRef = useRef(live);
  useEffect(() => {
    liveRef.current = live;
  });

  useEffect(() => {
    const data = version.data;
    versionRef.current = data ?? null;
    if (!data) return;
    const reveal = useRevealStore.getState();
    const creation = liveRef.current;
    if (creation.active) {
      // The canvas belongs to the design being created; only its own version takes over.
      if (creation.versionId() !== data.id) return;
      if (creation.shownHash() === data.model_hash) {
        // The house on screen is exactly the saved model: nothing is reloaded, the canvas,
        // the camera and a running construction simply continue.
        openVersion(data, false);
        reveal.dispatch({ type: "saved" });
      } else {
        // Saved before the laid-out preview could be shown: build the stored model.
        useBuildingStore.getState().load(data.model);
        openVersion(data, false);
        reveal.play("build");
      }
      creation.finish();
      return;
    }
    openVersion(data, true);
    const pending = pendingRef.current;
    if (pending && pending.versionId === data.id && playedRef.current !== pending) {
      playedRef.current = pending; // each queued reveal plays once
      if (pending.ids.length > 0) reveal.play("changes", pending.ids);
    } else if (pending?.versionId !== data.id) {
      reveal.dispatch({ type: "reset" }); // another version: nothing left over from a reveal
    }
  }, [version.data, openVersion]);

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
      toast.success(`Version v${saved.number} is now open`);
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

  if (project.isPending) return <EditorSkeleton label="Loading project…" />;
  if (project.isError) {
    const notFound = project.error instanceof ApiError && project.error.status === 404;
    return (
      <Centered tone="error">
        {notFound ? "Project not found." : "Could not load the project."}{" "}
        <Link href="/projects" className="underline underline-offset-2">
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
  // The stage list of a generation nobody else on the page is showing (the dashboard link).
  const showStages = running && liveGeneration === null && drawer !== "generate";

  return (
    <ViewerHost>
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-2 border-b border-line bg-surface px-3 py-1.5">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1 text-sm">
            <Link
              href="/projects"
              className="rounded-md px-1.5 py-1 text-fg-subtle transition-colors hover:bg-neutral-100 hover:text-fg dark:hover:bg-neutral-800"
            >
              Projects
            </Link>
            <ChevronRight size={14} aria-hidden className="shrink-0 text-fg-subtle" />
            <h1 className="truncate px-1 font-semibold tracking-tight">{p.name}</h1>
          </nav>
          {hasVersions && (
            <span className="relative inline-flex items-center">
              <GitBranch
                size={13}
                aria-hidden
                className="pointer-events-none absolute left-2 text-fg-subtle"
              />
              <Select
                aria-label="Version"
                className="h-7 max-w-[16rem] truncate pl-7 text-xs font-medium"
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
              </Select>
            </span>
          )}
          <span className="hidden text-xs text-fg-subtle md:inline">
            {p.region_code} · {p.currency} · rules {p.rules_profile_id}
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-1">
            {version.data && (
              <DrawerButton
                drawer={drawer}
                value="modify"
                onToggle={setDrawer}
                icon={<Wand2 size={14} />}
              >
                Modify with AI
              </DrawerButton>
            )}
            {(versions.data?.length ?? 0) > 1 && (
              <DrawerButton
                drawer={drawer}
                value="compare"
                onToggle={setDrawer}
                icon={<GitCompareArrows size={14} />}
              >
                Compare
              </DrawerButton>
            )}
            <DrawerButton
              drawer={drawer}
              value="history"
              onToggle={setDrawer}
              icon={<History size={14} />}
            >
              History
            </DrawerButton>
            {version.data && (
              <DrawerButton
                drawer={drawer}
                value="report"
                onToggle={setDrawer}
                icon={<ClipboardList size={14} />}
              >
                Report
                {reportCount(version.data) > 0 && (
                  <Badge tone="warning" className="ml-0.5 px-1.5 py-0">
                    {reportCount(version.data)}
                  </Badge>
                )}
              </DrawerButton>
            )}
            {hasVersions && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setDrawer(drawer === "generate" ? "none" : "generate")}
                aria-pressed={drawer === "generate"}
                icon={<Plus size={14} />}
                className="ml-1"
              >
                New design
              </Button>
            )}
          </div>
        </div>

        {justGenerated && version.data?.id === justGenerated && !revealing && !live.active && (
          <GeneratedBanner
            version={version.data}
            onReport={() => setDrawer("report")}
            onDismiss={() => setJustGenerated(null)}
          />
        )}

        <div data-drawer-host className="relative flex min-h-0 flex-1 flex-col">
          {versions.isPending ? (
            <EditorSkeleton label="Loading versions…" />
          ) : !hasVersions ? (
            <StartView
              live={live.active}
              onProgress={setLiveGeneration}
              onFormProgress={setFormJob}
              projectId={projectId}
              currency={p.currency}
              mode={mode}
              onMode={setMode}
              generationId={summaryId}
              onGenerated={onGenerated}
              onAICompleted={onAICompleted}
            />
          ) : live.active ? (
            <LiveCanvas />
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
            <EditorSkeleton label="Building the 3D model…" />
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

          {hasVersions && (showSummary || showStages) && summary.data && !revealing && (
            <div className="pointer-events-none absolute right-3 top-3 z-[16] flex justify-end lg:right-[19rem] xl:right-[21rem]">
              <div className="pointer-events-auto">
                {showSummary ? (
                  <GenerationSummary
                    generation={summary.data}
                    onDismiss={() => setSummaryId(null)}
                    onOpenReport={() => setDrawer("report")}
                  />
                ) : (
                  <div className="glass w-[min(92vw,360px)] animate-rise-in rounded-2xl p-4 shadow-lg">
                    <StageList generation={summary.data} />
                  </div>
                )}
              </div>
            </div>
          )}

          {drawer !== "none" && (
            <Drawer key={drawer} label={DRAWER_LABEL[drawer]}>
              {drawer === "generate" ? (
                <>
                  <ModeTabs mode={mode} onMode={setMode} />
                  <div className="min-h-0 flex-1">
                    {mode === "ai" ? (
                      <AIGeneratorPanel
                        projectId={projectId}
                        currency={p.currency}
                        onCompleted={onAICompleted}
                        onProgress={setLiveGeneration}
                        onClose={() => setDrawer("none")}
                      />
                    ) : (
                      <GenerationPanel
                        projectId={projectId}
                        initialSpec={spec}
                        onGenerated={onGenerated}
                        onProgress={setFormJob}
                        onClose={() => setDrawer("none")}
                      />
                    )}
                  </div>
                </>
              ) : drawer === "modify" ? (
                <ModifyPanel
                  projectId={projectId}
                  versionNumber={version.data?.number ?? null}
                  onSaved={(v) => {
                    // Applied: the elements the preview marked as changed grow again, once.
                    const ids = [...useHighlightStore.getState().ids];
                    if (ids.length > 0) queueReveal({ versionId: v.id, ids });
                    void onEditsSaved(v);
                  }}
                  onClose={() => setDrawer("none")}
                />
              ) : drawer === "compare" ? (
                <ComparePanel
                  projectId={projectId}
                  versions={versions.data ?? []}
                  shownVersionId={version.data?.id ?? null}
                  onClose={() => setDrawer("none")}
                />
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
            </Drawer>
          )}
        </div>
      </div>
    </ViewerHost>
  );
}

/** The elements of a version that grow again once it is open (Modify with AI). */
interface PendingReveal {
  versionId: string;
  ids: string[];
}

/**
 * The canvas while a design is created: the same 3D canvas the editor then shows (ViewerHost),
 * with the waiting sheet, the blueprint and the construction of the laid-out model.
 */
function LiveCanvas() {
  return (
    <div className="relative min-h-[320px] flex-1 animate-fade-in bg-bg-subtle">
      <div className="absolute inset-0">
        <RevealSurface>
          <ViewerSlot scene={null} />
        </RevealSurface>
      </div>
    </div>
  );
}

const DRAWER_LABEL: Record<Exclude<Drawer, "none">, string> = {
  generate: "Generate a new design",
  history: "Generation history",
  modify: "Modify with AI",
  compare: "Compare versions",
  report: "Design report",
};

function DrawerButton({
  drawer,
  value,
  onToggle,
  icon,
  children,
}: {
  drawer: Drawer;
  value: Drawer;
  onToggle: (drawer: Drawer) => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  const open = drawer === value;
  return (
    <Button
      variant="ghost"
      size="sm"
      icon={icon}
      onClick={() => onToggle(open ? "none" : value)}
      aria-pressed={open}
      className={open ? "bg-accent-soft text-accent-text hover:bg-accent-soft" : undefined}
    >
      {children}
    </Button>
  );
}

const DESIGN_MODES = [
  { value: "ai", label: "Describe with AI" },
  { value: "form", label: "Specification form" },
] as const;

function ModeTabs({ mode, onMode }: { mode: DesignMode; onMode: (mode: DesignMode) => void }) {
  return (
    <Tabs label="How to create the design" items={DESIGN_MODES} value={mode} onChange={onMode} />
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
  live,
  onProgress,
  onFormProgress,
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
  /** A design is being created: the canvas takes the place of the introduction. */
  live: boolean;
  onProgress: (generation: AIGenerationOut | null) => void;
  onFormProgress: (job: Job | null) => void;
}) {
  const importDemo = useImportDemo(projectId);
  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <div className="flex min-h-0 flex-1 flex-col border-line lg:max-w-[560px] lg:border-r">
        <ModeTabs mode={mode} onMode={onMode} />
        <div className="min-h-0 flex-1">
          {mode === "ai" ? (
            <AIGeneratorPanel
              projectId={projectId}
              currency={currency}
              initialGenerationId={generationId}
              onCompleted={onAICompleted}
              onProgress={onProgress}
            />
          ) : (
            <GenerationPanel
              projectId={projectId}
              onGenerated={onGenerated}
              onProgress={onFormProgress}
            />
          )}
        </div>
      </div>
      {live ? <LiveCanvas /> : <StartIntro importDemo={importDemo} onGenerated={onGenerated} />}
    </div>
  );
}

function StartIntro({
  importDemo,
  onGenerated,
}: {
  importDemo: ReturnType<typeof useImportDemo>;
  onGenerated: (versionId: string) => void;
}) {
  return (
    <div className="hero-backdrop flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
      <span
        aria-hidden
        className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-accent-text"
      >
        <Box size={22} />
      </span>
      <p className="max-w-md text-sm text-fg-muted">
        This project has no design yet. Describe the house you want and the building appears here as
        an interactive 3D model — every wall, room, door and window is a real, selectable object.
        Each generation is saved as a new version.
      </p>
      <Button
        variant="outline"
        onClick={() =>
          importDemo.mutate(undefined, {
            onSuccess: (v) => {
              toast.success("Demo house imported");
              onGenerated(v.id);
            },
          })
        }
        disabled={importDemo.isPending}
      >
        {importDemo.isPending ? "Importing…" : "Or import the hand-authored demo house"}
      </Button>
      {importDemo.isError && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {importDemo.error.message}
        </p>
      )}
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
      className="flex animate-fade-in flex-wrap items-center gap-x-3 gap-y-1 border-b border-green-200 bg-green-50 px-4 py-1.5 text-sm text-green-900 dark:border-green-900 dark:bg-green-950/60 dark:text-green-200"
    >
      <CircleCheck size={15} aria-hidden className="text-green-600 dark:text-green-400" />
      <span className="font-semibold">
        {version.source === "manual" ? "Saved" : "Generated"} v{version.number}
      </span>
      <span className="tabular-nums">
        {s.storeys} floor{s.storeys > 1 ? "s" : ""} · {s.gross_floor_area_m2} m² · {s.rooms} rooms ·{" "}
        {s.bedrooms} bedrooms · {s.bathrooms} bathrooms
      </span>
      {count > 0 && (
        <button type="button" onClick={onReport} className="underline underline-offset-2">
          {count} note{count > 1 ? "s" : ""} to review
        </button>
      )}
      <IconButton
        label="Dismiss"
        onClick={onDismiss}
        size="sm"
        className="ml-auto text-green-800 hover:bg-green-100 hover:text-green-900 dark:text-green-300 dark:hover:bg-green-900"
      >
        <X size={14} />
      </IconButton>
    </div>
  );
}

function Centered({ children, tone }: { children: React.ReactNode; tone?: "error" }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div
        role={tone === "error" ? "alert" : "status"}
        className={
          "max-w-xl text-sm " +
          (tone === "error" ? "text-red-600 dark:text-red-400" : "text-fg-subtle")
        }
      >
        {children}
      </div>
    </div>
  );
}

/** The editor's shape while data loads: panels and viewport as skeletons, with a status text. */
function EditorSkeleton({ label }: { label: string }) {
  return (
    <div role="status" className="flex min-h-0 flex-1">
      <div className="hidden w-56 shrink-0 flex-col gap-3 border-r border-line p-3 lg:flex">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-24 w-full" />
      </div>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-bg-subtle p-8">
        <Spinner className="h-5 w-5 text-accent-text" />
        <p className="text-sm text-fg-subtle">{label}</p>
      </div>
      <div className="hidden w-72 shrink-0 flex-col gap-3 border-l border-line p-3 lg:flex">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    </div>
  );
}
