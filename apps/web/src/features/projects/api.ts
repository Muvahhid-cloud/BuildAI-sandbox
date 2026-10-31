import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api/client";
import { projectListSchema, projectSchema } from "@/lib/api/schemas";

export const projectKeys = {
  all: ["projects"] as const,
  detail: (id: string) => ["projects", id] as const,
};

export interface ProjectCreateInput {
  name: string;
  description?: string;
  currency?: string;
  region_code?: string;
}

export function useProjects() {
  return useQuery({
    queryKey: projectKeys.all,
    queryFn: async () => (await apiRequest("/projects", projectListSchema)).items,
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: projectKeys.detail(id),
    queryFn: () => apiRequest(`/projects/${encodeURIComponent(id)}`, projectSchema),
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ProjectCreateInput) =>
      apiRequest("/projects", projectSchema, { method: "POST", body: input }),
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.all }),
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/projects/${encodeURIComponent(id)}`, null, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.all }),
  });
}
