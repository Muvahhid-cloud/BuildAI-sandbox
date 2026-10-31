"use client";

import type { AIGenerationOut, GenerationOptions } from "@buildai/schema";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { projectKeys } from "@/features/projects/api";
import { versionKeys } from "@/features/versions/api";

import { aiKeys, isTerminal, useAIGeneration, useStartAIGeneration } from "../api";
import { AIGenerationStatus } from "./AIGenerationStatus";
import { AIPromptForm } from "./AIPromptForm";

export interface AIGeneratorPanelProps {
  projectId: string;
  currency?: string;
  /** Resume a generation started elsewhere (e.g. from the projects dashboard). */
  initialGenerationId?: string | null;
  onCompleted: (generation: AIGenerationOut) => void;
  onClose?: () => void;
}

/** Describe -> generate -> watch real stages -> hand the finished version to the editor. */
export function AIGeneratorPanel({
  projectId,
  currency,
  initialGenerationId = null,
  onCompleted,
  onClose,
}: AIGeneratorPanelProps) {
  const qc = useQueryClient();
  const [prompt, setPrompt] = useState("");
  const [generationId, setGenerationId] = useState<string | null>(initialGenerationId);
  const start = useStartAIGeneration();
  const generation = useAIGeneration(generationId);
  const handled = useRef<string | null>(null);

  useEffect(() => {
    const data = generation.data;
    if (!data || !isTerminal(data) || handled.current === data.id) return;
    handled.current = data.id;
    void qc.invalidateQueries({ queryKey: aiKeys.history(projectId) });
    if (data.status !== "completed") return;
    void Promise.all([
      qc.invalidateQueries({ queryKey: versionKeys.list(projectId) }),
      qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) }),
      qc.invalidateQueries({ queryKey: projectKeys.all }),
    ]).then(() => onCompleted(data));
  }, [generation.data, projectId, qc, onCompleted]);

  function run(text: string, options: Partial<GenerationOptions>) {
    setPrompt(text);
    start.mutate(
      { projectId, prompt: text, options },
      { onSuccess: (created) => setGenerationId(created.id) },
    );
  }

  const active = generationId !== null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
        <div>
          <h2 className="font-semibold">Create your building with AI</h2>
          <p className="text-xs text-neutral-500">
            Describe the house in your own words. The AI writes a building specification, the
            deterministic layout engine plans it, and the 3D editor opens the result.
          </p>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md px-2 text-lg leading-none text-neutral-400 hover:text-neutral-700"
          >
            ×
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {active ? (
          <AIGenerationStatus
            generation={generation.data}
            onClarified={(next) => run(next, generation.data?.options ?? {})}
            onRetry={() => {
              // Back to the (editable) description of the generation that needs changes.
              if (generation.data) setPrompt(generation.data.prompt);
              setGenerationId(null);
              start.reset();
            }}
          />
        ) : (
          <AIPromptForm
            prompt={prompt}
            onPromptChange={setPrompt}
            onSubmit={run}
            pending={start.isPending}
            error={start.error?.message ?? null}
            defaultCurrency={currency}
          />
        )}
        {generation.isError && (
          <p role="alert" className="mt-3 text-sm text-red-600">
            Could not read the generation status: {generation.error.message}
          </p>
        )}
      </div>
    </div>
  );
}
