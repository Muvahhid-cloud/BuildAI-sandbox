"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useStartAIGeneration } from "@/features/ai/api";
import { AIPromptForm } from "@/features/ai/components/AIPromptForm";
import { ApiError } from "@/lib/api/errors";

import { projectKeys, useCreateProject, useDeleteProject, useProjects } from "../api";

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
    create.mutate({ name }, { onSuccess: () => setName("") });
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 p-6">
      <section
        aria-labelledby="ai-hero"
        className="rounded-2xl border border-blue-100 bg-gradient-to-br from-white to-blue-50 p-6 shadow-sm dark:border-neutral-800 dark:from-neutral-950 dark:to-neutral-900"
      >
        <h1 id="ai-hero" className="text-2xl font-semibold tracking-tight">
          Create your building with AI
        </h1>
        <p className="mb-4 mt-1 max-w-2xl text-sm text-neutral-600 dark:text-neutral-300">
          Describe the house in plain language. The AI turns it into a validated building
          specification, the layout engine plans every room, wall, door and window, and the result
          opens as an interactive 3D model you can explore and inspect.
        </p>
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
      </section>

      <section aria-labelledby="projects-title" className="flex flex-col gap-4">
        <h2 id="projects-title" className="text-lg font-semibold">
          Projects
        </h2>
        <form onSubmit={onCreate} className="flex gap-2">
          <label htmlFor="new-project" className="sr-only">
            New project name
          </label>
          <input
            id="new-project"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Or create an empty project, e.g. Family house in Almaty"
            className="flex-1 rounded-md border border-neutral-300 bg-transparent px-3 py-2 text-sm dark:border-neutral-700"
          />
          <button
            type="submit"
            disabled={create.isPending || !name.trim()}
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
          >
            Create
          </button>
        </form>
        {create.error instanceof ApiError && (
          <p role="alert" className="text-sm text-red-600">
            {create.error.message}
          </p>
        )}

        {projects.isPending && <p className="text-sm text-neutral-500">Loading projects…</p>}
        {projects.isError && (
          <p role="alert" className="text-sm text-red-600">
            Could not load projects.
          </p>
        )}
        {projects.data?.length === 0 && (
          <p className="text-sm text-neutral-500">
            No projects yet. Describe a building above to create your first one.
          </p>
        )}

        <ul className="flex flex-col divide-y divide-neutral-200 dark:divide-neutral-800">
          {projects.data?.map((p) => (
            <li key={p.id} className="flex items-center justify-between py-3">
              <Link href={`/projects/${p.id}`} className="flex flex-col">
                <span className="font-medium">{p.name}</span>
                <span className="text-xs text-neutral-500">
                  {p.region_code} · {p.currency} · {p.rules_profile_id}
                  {p.current_version_id ? "" : " · no design yet"}
                </span>
              </Link>
              <button
                type="button"
                onClick={() => {
                  if (window.confirm(`Delete project "${p.name}"?`)) remove.mutate(p.id);
                }}
                className="text-sm text-neutral-500 hover:text-red-600"
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
