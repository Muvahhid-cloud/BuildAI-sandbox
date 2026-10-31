import {
  type AIGenerationOut,
  type GenerationOptions,
  aiGenerationListSchema,
  aiGenerationSchema,
} from "@buildai/schema";
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api/client";

export const aiKeys = {
  generation: (id: string) => ["ai", "generations", id] as const,
  history: (projectId: string) => ["projects", projectId, "generations"] as const,
};

export interface StartGenerationInput {
  /** Omit to create a new project for the design. */
  projectId?: string;
  prompt: string;
  options: Partial<GenerationOptions>;
}

export function useStartAIGeneration() {
  return useMutation({
    mutationFn: ({ projectId, prompt, options }: StartGenerationInput) =>
      apiRequest("/ai/generate-building", aiGenerationSchema, {
        method: "POST",
        body: { project_id: projectId ?? null, prompt, options },
      }),
  });
}

export function isTerminal(generation: AIGenerationOut | undefined): boolean {
  return (
    generation?.status === "completed" ||
    generation?.status === "failed" ||
    generation?.status === "needs_clarification"
  );
}

/** Polls a generation until it completes, fails or needs clarification. */
export function useAIGeneration(id: string | null) {
  return useQuery({
    queryKey: aiKeys.generation(id ?? "none"),
    queryFn: () =>
      apiRequest(`/ai/generations/${encodeURIComponent(id ?? "")}`, aiGenerationSchema),
    enabled: id !== null,
    refetchInterval: (query) => (isTerminal(query.state.data) ? false : 600),
    staleTime: (query) => (isTerminal(query.state.data) ? Number.POSITIVE_INFINITY : 0),
  });
}

export function useProjectGenerations(projectId: string) {
  return useQuery({
    queryKey: aiKeys.history(projectId),
    queryFn: async () =>
      (
        await apiRequest(
          `/projects/${encodeURIComponent(projectId)}/generations`,
          aiGenerationListSchema,
        )
      ).items,
  });
}

/**
 * Real backend stages in order (mirrors GenerationStage in
 * app/modules/ai/schemas/responses.py). "repairing" is only shown when it happened.
 */
export const AI_STAGES = [
  { id: "interpreting", label: "Understanding your requirements" },
  { id: "validating", label: "Validating the building specification" },
  { id: "repairing", label: "Correcting the specification" },
  { id: "layout", label: "Generating the layout" },
  { id: "checking", label: "Checking building rules" },
  { id: "saving", label: "Saving the new version" },
] as const;

export const EXAMPLE_PROMPTS = [
  "Create a modern two-story family house of approximately 280 square meters with four bedrooms, three bathrooms, a large living room connected to the kitchen, a two-car garage, a balcony on the second floor, large windows and minimalist interior design.",
  "Minimalist villa with four bedrooms, a large terrace and panoramic windows.",
  "Small modern home for a family of four with a garage.",
  "Classic brick three-storey house of 360 m² with five bedrooms, a study and two balconies.",
] as const;
