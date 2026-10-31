"use client";

import type { AIGenerationSummaryOut } from "@buildai/schema";

import { useProjectGenerations } from "../api";

const STATUS: Record<AIGenerationSummaryOut["status"], { label: string; tone: string }> = {
  queued: { label: "Queued", tone: "bg-neutral-100 text-neutral-700" },
  running: { label: "Running", tone: "bg-blue-100 text-blue-800" },
  completed: { label: "Completed", tone: "bg-green-100 text-green-800" },
  needs_clarification: { label: "Needs details", tone: "bg-amber-100 text-amber-800" },
  failed: { label: "Failed", tone: "bg-red-100 text-red-800" },
};

/** The project's natural-language generations, newest first. */
export function GenerationHistory({
  projectId,
  onOpen,
  onClose,
}: {
  projectId: string;
  onOpen: (generation: AIGenerationSummaryOut) => void;
  onClose: () => void;
}) {
  const history = useProjectGenerations(projectId);
  return (
    <div className="flex h-full min-h-0 flex-col text-sm">
      <div className="flex items-start justify-between border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
        <div>
          <h2 className="font-semibold">AI generation history</h2>
          <p className="text-xs text-neutral-500">Every description, what happened and why.</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close history"
          className="rounded-md px-2 text-lg leading-none text-neutral-400 hover:text-neutral-700"
        >
          ×
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {history.isPending && <p className="text-xs text-neutral-500">Loading…</p>}
        {history.isError && (
          <p role="alert" className="text-xs text-red-600">
            Could not load the history.
          </p>
        )}
        {history.data?.length === 0 && (
          <p className="text-xs text-neutral-500">No AI generations in this project yet.</p>
        )}
        <ul className="flex flex-col gap-2">
          {history.data?.map((g) => (
            <li
              key={g.id}
              className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
            >
              <div className="mb-1 flex items-center gap-2 text-xs">
                <span className={`rounded-full px-2 py-0.5 font-medium ${STATUS[g.status].tone}`}>
                  {STATUS[g.status].label}
                </span>
                <time className="text-neutral-500" dateTime={g.created_at}>
                  {new Date(g.created_at).toLocaleString()}
                </time>
                {g.version_number !== null && (
                  <span className="ml-auto font-medium">v{g.version_number}</span>
                )}
              </div>
              <p className="line-clamp-3 text-xs text-neutral-700 dark:text-neutral-300">
                {g.prompt}
              </p>
              {g.error && <p className="mt-1 text-xs text-red-600">{g.error.message}</p>}
              {g.status === "needs_clarification" && (
                <ul className="mt-1 list-disc pl-4 text-xs text-amber-800 dark:text-amber-300">
                  {g.clarification_questions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              )}
              <div className="mt-2 flex items-center justify-between text-[11px] text-neutral-400">
                <span>
                  {g.provider === "mock" ? "mock interpreter" : `${g.provider} · ${g.model}`}
                  {g.repair_count > 0 && ` · ${g.repair_count} repair`}
                  {g.duration_ms !== null && ` · ${(g.duration_ms / 1000).toFixed(1)} s`}
                </span>
                {g.version_id && (
                  <button
                    type="button"
                    onClick={() => onOpen(g)}
                    className="text-blue-600 hover:underline"
                  >
                    Open v{g.version_number}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
