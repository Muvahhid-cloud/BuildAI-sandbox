"use client";

import { DrawerHeader } from "@/components/ui";
import { Sparkles } from "lucide-react";
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
  /** The generation being followed while it is still running (null once it ends or is left). */
  onProgress?: (generation: AIGenerationOut | null) => void;
  onClose?: () => void;
}

/** Describe -> generate -> watch real stages -> hand the finished version to the editor. */
export function AIGeneratorPanel({
  projectId,
  currency,
  initialGenerationId = null,
  onCompleted,
  onProgress,
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

  // Report the real backend stage upwards (the waiting cloud in the canvas area follows it).
  const live = generationId !== null && generation.data && !isTerminal(generation.data);
  const liveGeneration = live ? generation.data : null;
  useEffect(() => {
    onProgress?.(liveGeneration ?? null);
  }, [liveGeneration, onProgress]);
  useEffect(() => () => onProgress?.(null), [onProgress]);

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
      <DrawerHeader
        icon={<Sparkles size={15} />}
        title={<>Create your building with AI</>}
        description={
          <>
            Describe the house in your own words. The AI writes a building specification, the
            deterministic layout engine plans it, and the 3D editor opens the result.
          </>
        }
        onClose={onClose}
      />
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
          <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
            Could not read the generation status: {generation.error.message}
          </p>
        )}
      </div>
    </div>
  );
}
