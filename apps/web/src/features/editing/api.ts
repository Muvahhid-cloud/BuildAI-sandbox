// Plan-editing requests (API: /projects/{id}/versions/{vid}/edits, docs/3d-engine.md §20).
// The server is authoritative: it replays the operations on the stored version and validates
// the result; the client only ever shows models the server returned.
import { apiRequest } from "@/lib/api/client";
import { type EditOperation, editPreviewSchema, versionSchema } from "@/lib/api/schemas";

const base = (projectId: string, versionId: string) =>
  `/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(versionId)}/edits`;

export function previewEdits(
  projectId: string,
  versionId: string,
  operations: readonly EditOperation[],
  signal?: AbortSignal,
) {
  return apiRequest(`${base(projectId, versionId)}/preview`, editPreviewSchema, {
    method: "POST",
    body: { operations },
    signal,
  });
}

export function saveEdits(
  projectId: string,
  versionId: string,
  operations: readonly EditOperation[],
  label?: string,
) {
  return apiRequest(base(projectId, versionId), versionSchema, {
    method: "POST",
    body: { operations, ...(label ? { label } : {}) },
  });
}
