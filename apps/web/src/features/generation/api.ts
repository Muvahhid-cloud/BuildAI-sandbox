import type { BuildingSpecification } from "@buildai/schema";
import { useMutation, useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { apiRequest } from "@/lib/api/client";
import { jobSchema, specValidationSchema } from "@/lib/api/schemas";

// GET /design-options (K3): usable design systems, unavailable ones with the reason, and the
// facade color palette. Only the fields the form uses are validated.
const designSystemSchema = z.object({
  id: z.string(),
  name: z.string(),
  source: z.string(),
  style_tags: z.array(z.string()),
  roof: z.object({
    types: z.array(z.string()),
    default: z.string(),
    default_pitch_deg: z.number().nullable(),
  }),
  windows: z.object({ styles: z.array(z.string()), default: z.string() }),
  facade: z.object({
    materials: z.array(z.string()),
    default_material: z.string(),
    colors: z.array(z.string()),
    default_color: z.string().nullable(),
    custom_colors: z.boolean(),
  }),
});
export const designOptionsSchema = z.object({
  available: z.array(designSystemSchema),
  unavailable: z.array(z.object({ id: z.string(), name: z.string(), reason: z.string() })),
  palette: z.array(z.object({ name: z.string(), hex: z.string() })),
});
export type DesignOptions = z.infer<typeof designOptionsSchema>;
export type DesignSystemOption = z.infer<typeof designSystemSchema>;

export function useDesignOptions() {
  return useQuery({
    queryKey: ["design-options"],
    queryFn: () => apiRequest("/design-options", designOptionsSchema),
    staleTime: 60_000,
  });
}

const project = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`;

export function useValidateSpec(projectId: string) {
  return useMutation({
    mutationFn: (spec: BuildingSpecification) =>
      apiRequest(`${project(projectId)}/spec/validate`, specValidationSchema, {
        method: "POST",
        body: { spec },
      }),
  });
}

export interface GenerateInput {
  spec: BuildingSpecification;
  seed: number;
  label?: string;
}

export function useStartGeneration(projectId: string) {
  return useMutation({
    mutationFn: (input: GenerateInput) =>
      apiRequest(`${project(projectId)}/generate`, jobSchema, { method: "POST", body: input }),
  });
}

/** Polls a job until it finishes (the layout engine usually takes well under a few seconds). */
export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: ["jobs", jobId],
    queryFn: () => apiRequest(`/jobs/${encodeURIComponent(jobId ?? "")}`, jobSchema),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed" ? false : 400;
    },
  });
}

/** Real job stages in order (mirrors STAGES in app/modules/generation/service.py). */
export const GENERATION_STAGES = [
  { id: "queued", label: "Validating the specification" },
  { id: "layout", label: "Planning the layout" },
  { id: "checking", label: "Checking building rules" },
  { id: "saving", label: "Saving the new version" },
] as const;
