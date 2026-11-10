// AI-assisted modification and version comparison (Phase 5, docs/ai-pipeline.md §11). The server
// interprets, resolves and validates; the client shows the plan and the model the server built.
import { apiRequest } from "@/lib/api/client";
import {
  compareSchema,
  type EditOperation,
  type ModifyAnswer,
  modifyPlanSchema,
  versionSchema,
} from "@/lib/api/schemas";

const modify = (projectId: string, versionId: string) =>
  `/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(versionId)}/modify`;

/** Natural-language request -> plan (AI interpretation + typed operations + validated preview). */
export function planModification(
  projectId: string,
  versionId: string,
  prompt: string,
  operations: readonly EditOperation[],
) {
  return apiRequest(`${modify(projectId, versionId)}/plan`, modifyPlanSchema, {
    method: "POST",
    body: { prompt, operations },
  });
}

/** The same interpretation resolved again with the user's answers (no AI call). */
export function resolveModification(
  projectId: string,
  versionId: string,
  prompt: string,
  draft: Record<string, unknown>,
  answers: readonly ModifyAnswer[],
  operations: readonly EditOperation[],
) {
  return apiRequest(`${modify(projectId, versionId)}/resolve`, modifyPlanSchema, {
    method: "POST",
    body: { prompt, draft, answers, operations },
  });
}

/** Make an earlier version current again, as a new version (versions are immutable). */
export function restoreVersion(projectId: string, versionId: string) {
  return apiRequest(
    `/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(versionId)}/restore`,
    versionSchema,
    { method: "POST" },
  );
}

export function compareVersions(projectId: string, a: string, b: string) {
  const q = new URLSearchParams({ a, b });
  return apiRequest(`/projects/${encodeURIComponent(projectId)}/compare?${q}`, compareSchema);
}
