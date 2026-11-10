"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Box, FolderPlus, Layers, Plus, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, IconButton, Input, Skeleton, toast } from "@/components/ui";
import { useStartAIGeneration } from "@/features/ai/api";
import { AIPromptForm } from "@/features/ai/components/AIPromptForm";
import { ApiError } from "@/lib/api/errors";
import type { Project } from "@/lib/api/schemas";

import { projectKeys, useCreateProject, useDeleteProject, useProjects } from "../api";

const STEPS = [
  { icon: Sparkles, title: "Describe", text: "Plain language: size, rooms, style, garage." },
  { icon: Layers, title: "Plan", text: "A validated specification and a rule-checked layout." },
  { icon: Box, title: "Explore", text: "Every wall, room, door and window is an object in 3D." },
] as const;

export function ProjectsDashboard() {
  const projects = useProjects();
  const create = useCreateProject();
  const remove = useDeleteProject();
  const start = useStartAIGeneration();
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");

  function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate(
      { name },
      {
        onSuccess: (project) => {
          setName("");
          toast.success(`Project “${project.name}” created`);
        },
      },
    );
  }

  function onDelete(project: Project) {
    if (!window.confirm(`Delete project "${project.name}"?`)) return;
    remove.mutate(project.id, {
      onSuccess: () => toast.success(`Project “${project.name}” deleted`),
      onError: (err) => toast.error(err instanceof Error ? err.message : "Could not delete it"),
    });
  }

  return (
    <div className="flex flex-col">
      <section aria-labelledby="ai-hero" className="hero-backdrop border-b border-line">
        <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-4 pb-10 pt-10 text-center sm:pt-16">
          <Badge tone="accent" className="animate-rise-in">
            <Sparkles size={11} aria-hidden /> AI-assisted conceptual design
          </Badge>
          <h1
            id="ai-hero"
            className="mt-4 animate-rise-in text-balance text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl"
          >
            Describe your building.
            <span className="block bg-gradient-to-r from-blue-600 to-violet-500 bg-clip-text text-transparent dark:from-blue-300 dark:to-violet-300">
              Explore it in 3D.
            </span>
          </h1>
          <p className="mt-4 max-w-xl animate-rise-in text-pretty text-[15px] text-fg-muted">
            The AI turns your words into a validated building specification, the layout engine plans
            every room, wall, door and window, and the result opens as an interactive model.
          </p>
          <div className="mt-8 w-full animate-rise-in text-left">
            <AIPromptForm
              size="hero"
              prompt={prompt}
              onPromptChange={setPrompt}
              pending={start.isPending}
              error={start.error instanceof Error ? start.error.message : null}
              onSubmit={(text, options) =>
                start.mutate(
                  { prompt: text, options },
                  {
                    onSuccess: (generation) => {
                      void qc.invalidateQueries({ queryKey: projectKeys.all });
                      router.push(`/projects/${generation.project_id}?generation=${generation.id}`);
                    },
                  },
                )
              }
            />
          </div>
          <ol className="mt-8 grid w-full gap-3 text-left sm:grid-cols-3">
            {STEPS.map(({ icon: Icon, title, text }, i) => (
              <li
                key={title}
                className="flex gap-3 rounded-xl border border-line bg-surface/70 p-3"
              >
                <span
                  aria-hidden
                  className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text"
                >
                  <Icon size={15} />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">
                    <span className="text-fg-subtle">{i + 1}.</span> {title}
                  </span>
                  <span className="block text-xs text-fg-subtle">{text}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section
        aria-labelledby="projects-title"
        className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-8"
      >
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="projects-title" className="text-lg font-semibold tracking-tight">
              Recent projects
            </h2>
            <p className="text-xs text-fg-subtle">
              Every generation and every saved edit is kept as a version.
            </p>
          </div>
          <form onSubmit={onCreate} className="flex w-full gap-2 sm:w-auto">
            <label htmlFor="new-project" className="sr-only">
              New project name
            </label>
            <Input
              id="new-project"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Empty project, e.g. Family house in Almaty"
              className="sm:w-72"
            />
            <Button
              type="submit"
              variant="outline"
              disabled={create.isPending || !name.trim()}
              icon={<Plus size={14} />}
            >
              Create
            </Button>
          </form>
        </div>
        {create.error instanceof ApiError && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {create.error.message}
          </p>
        )}

        {projects.isPending && (
          <div role="status" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <span className="sr-only">Loading projects…</span>
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-[136px] rounded-xl" />
            ))}
          </div>
        )}
        {projects.isError && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            Could not load projects.
          </p>
        )}
        {projects.data?.length === 0 && (
          <Card className="flex flex-col items-center gap-2 border-dashed px-6 py-12 text-center shadow-none">
            <span
              aria-hidden
              className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-accent-soft text-accent-text"
            >
              <FolderPlus size={20} />
            </span>
            <p className="font-medium">No projects yet</p>
            <p className="max-w-sm text-sm text-fg-subtle">
              Describe a building above to create your first one, or start with an empty project.
            </p>
          </Card>
        )}

        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.data?.map((p) => (
            <li key={p.id}>
              <Card interactive className="group relative flex h-full flex-col overflow-hidden">
                <Link
                  href={`/projects/${p.id}`}
                  className="flex flex-1 flex-col rounded-xl outline-offset-[-2px]"
                >
                  <ProjectArt id={p.id} empty={!p.current_version_id} />
                  <span className="flex flex-1 flex-col gap-1 px-3.5 pb-3 pt-2.5">
                    <span className="flex items-center gap-2 pr-7">
                      <span className="truncate font-medium">{p.name}</span>
                      <ArrowRight
                        size={14}
                        aria-hidden
                        className="shrink-0 -translate-x-1 text-fg-subtle opacity-0 transition-all duration-200 group-hover:translate-x-0 group-hover:opacity-100"
                      />
                    </span>
                    <span className="text-xs text-fg-subtle">
                      {p.region_code} · {p.currency} · {p.rules_profile_id}
                      {p.current_version_id ? "" : " · no design yet"}
                    </span>
                    <span className="mt-auto pt-1 text-2xs text-fg-subtle">
                      Updated {formatDate(p.updated_at)}
                    </span>
                  </span>
                </Link>
                <IconButton
                  label={`Delete project ${p.name}`}
                  onClick={() => onDelete(p)}
                  size="sm"
                  className="absolute bottom-2.5 right-2.5 opacity-60 hover:bg-red-50 hover:text-red-600 dark:hover:text-red-400 hover:opacity-100 focus-visible:opacity-100 dark:hover:bg-red-950"
                >
                  <Trash2 size={14} />
                </IconButton>
              </Card>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

/** ISO timestamp -> "12 Nov 2026" (fixed locale: the same text on server and client). */
function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/**
 * Decorative card header: an abstract massing sketch whose hue and proportions come from the
 * project id (stable, not a rendering of the model).
 */
function ProjectArt({ id, empty }: { id: string; empty: boolean }) {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  const hue = 225 + (hash % 50);
  const w = 54 + (hash % 5) * 7;
  const h = 26 + ((hash >> 3) % 4) * 6;
  const wing = 22 + ((hash >> 6) % 3) * 8;
  const base = 62;
  return (
    <svg
      viewBox="0 0 240 72"
      aria-hidden
      className="h-[72px] w-full border-b border-line bg-bg-subtle"
      preserveAspectRatio="xMidYMid slice"
    >
      <defs>
        <pattern id={`g-${id}`} width="12" height="12" patternUnits="userSpaceOnUse">
          <path d="M12 0H0V12" fill="none" stroke="currentColor" strokeOpacity="0.07" />
        </pattern>
      </defs>
      <rect width="240" height="72" fill={`url(#g-${id})`} className="text-fg" />
      {empty ? (
        <rect
          x={120 - w / 2}
          y={base - h}
          width={w}
          height={h}
          rx="2"
          fill="none"
          stroke={`hsl(${hue} 60% 62%)`}
          strokeDasharray="4 4"
        />
      ) : (
        <g>
          <rect
            x={120 - w / 2 - wing}
            y={base - h * 0.55}
            width={wing}
            height={h * 0.55}
            fill={`hsl(${hue} 70% 62% / 0.35)`}
          />
          <rect
            x={120 - w / 2}
            y={base - h}
            width={w}
            height={h}
            fill={`hsl(${hue} 72% 60% / 0.75)`}
          />
          <path
            d={`M${120 - w / 2 - 4} ${base - h} L120 ${base - h - 12} L${120 + w / 2 + 4} ${base - h} Z`}
            fill={`hsl(${hue} 60% 42% / 0.85)`}
          />
          <rect x={120 - 5} y={base - 12} width="10" height="12" fill="#fff" fillOpacity="0.7" />
        </g>
      )}
      <line x1="0" y1={base} x2="240" y2={base} stroke="currentColor" strokeOpacity="0.15" />
    </svg>
  );
}
