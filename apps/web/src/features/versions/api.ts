import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { projectKeys } from "@/features/projects/api";
import { apiRequest } from "@/lib/api/client";
import { versionListSchema, versionSchema } from "@/lib/api/schemas";

export const versionKeys = {
  list: (projectId: string) => ["projects", projectId, "versions"] as const,
  detail: (projectId: string, versionId: string) =>
    ["projects", projectId, "versions", versionId] as const,
};

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/versions`;

export function useVersions(projectId: string) {
  return useQuery({
    queryKey: versionKeys.list(projectId),
    queryFn: async () => (await apiRequest(base(projectId), versionListSchema)).items,
  });
}

/** A version is immutable, so once loaded it never needs refetching. */
export function useVersion(projectId: string, versionId: string | null) {
  return useQuery({
    queryKey: versionKeys.detail(projectId, versionId ?? "none"),
    queryFn: () =>
      apiRequest(`${base(projectId)}/${encodeURIComponent(versionId ?? "")}`, versionSchema),
    enabled: versionId !== null,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useImportDemo(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest(`${base(projectId)}/demo`, versionSchema, { method: "POST" }),
    onSuccess: async (version) => {
      qc.setQueryData(versionKeys.detail(projectId, version.id), version);
      await Promise.all([
        qc.invalidateQueries({ queryKey: versionKeys.list(projectId) }),
        qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) }),
      ]);
    },
  });
}
