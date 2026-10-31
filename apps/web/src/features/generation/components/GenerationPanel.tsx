"use client";

import type { BuildingSpecification } from "@buildai/schema";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { projectKeys } from "@/features/projects/api";
import { versionKeys } from "@/features/versions/api";
import { ApiError } from "@/lib/api/errors";
import type { Issue, Job } from "@/lib/api/schemas";

import {
  GENERATION_STAGES,
  useDesignOptions,
  useJob,
  useStartGeneration,
  useValidateSpec,
} from "../api";
import { emptySpec } from "../spec-presets";
import { checkSpecShape, SpecForm } from "./SpecForm";

export interface GenerationPanelProps {
  projectId: string;
  /** Pre-fill (e.g. the spec of the version on screen). */
  initialSpec?: BuildingSpecification | null;
  onGenerated: (versionId: string) => void;
  onClose?: () => void;
}

export function GenerationPanel({
  projectId,
  initialSpec,
  onGenerated,
  onClose,
}: GenerationPanelProps) {
  const qc = useQueryClient();
  const [spec, setSpec] = useState<BuildingSpecification>(() =>
    initialSpec ? structuredClone(initialSpec) : emptySpec(),
  );
  const [seed, setSeed] = useState(0);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [checked, setChecked] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const validate = useValidateSpec(projectId);
  const start = useStartGeneration(projectId);
  const job = useJob(jobId);
  const designOptions = useDesignOptions();
  const handled = useRef<string | null>(null);

  const running = start.isPending || (jobId !== null && !isFinished(job.data));

  useEffect(() => {
    const data = job.data;
    if (!data || handled.current === data.id || data.status !== "succeeded") return;
    handled.current = data.id;
    const versionId = String(data.result?.version_id ?? "");
    void Promise.all([
      qc.invalidateQueries({ queryKey: versionKeys.list(projectId) }),
      qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) }),
    ]).then(() => onGenerated(versionId));
  }, [job.data, projectId, qc, onGenerated]);

  function edit(next: BuildingSpecification) {
    setSpec(next);
    setChecked(false);
  }

  async function check(): Promise<boolean> {
    const local = checkSpecShape(spec);
    if (local.length > 0) {
      setIssues(local);
      return false;
    }
    try {
      const result = await validate.mutateAsync(spec);
      setIssues(result.issues);
      setChecked(true);
      return result.valid;
    } catch (err) {
      setIssues(issuesFromError(err));
      return false;
    }
  }

  async function generate() {
    setJobId(null);
    handled.current = null;
    if (!(await check())) return;
    try {
      const created = await start.mutateAsync({ spec, seed });
      setJobId(created.id);
    } catch (err) {
      setIssues(issuesFromError(err));
    }
  }

  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
        <div>
          <h2 className="font-semibold">Generate a house from a specification</h2>
          <p className="text-xs text-neutral-500">
            Set the program precisely; the deterministic layout engine plans the rooms, walls,
            openings, stairs and roof. Prefer plain language? Use “Describe with AI”.
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
        <SpecForm
          spec={spec}
          onChange={edit}
          seed={seed}
          onSeedChange={setSeed}
          issues={issues}
          disabled={running}
          designOptions={designOptions.data}
        />
      </div>

      <div className="flex flex-col gap-3 border-t border-neutral-200 px-4 py-3 dark:border-neutral-800">
        {(errors.length > 0 || warnings.length > 0) && (
          <ul aria-label="Specification issues" className="max-h-32 overflow-y-auto text-xs">
            {errors.map((i) => (
              <li key={i.code + i.path} className="text-red-600">
                {i.message}
                {i.suggestion && <span className="text-neutral-500"> — {i.suggestion}</span>}
              </li>
            ))}
            {warnings.map((i) => (
              <li key={i.code + i.path} className="text-amber-700 dark:text-amber-400">
                {i.message}
              </li>
            ))}
          </ul>
        )}
        {checked && errors.length === 0 && jobId === null && (
          <p className="text-xs text-green-700 dark:text-green-400">
            Specification is valid under the project&apos;s rules profile.
          </p>
        )}
        {jobId !== null && <GenerationProgress job={job.data} />}
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => void check()}
            disabled={running || validate.isPending}
            className="rounded-md px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-100 disabled:opacity-50 dark:text-neutral-200 dark:hover:bg-neutral-800"
          >
            Check specification
          </button>
          <button
            type="button"
            onClick={() => void generate()}
            disabled={running}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {running ? "Generating…" : "Generate house"}
          </button>
        </div>
      </div>
    </div>
  );
}

function isFinished(job: Job | undefined): boolean {
  return job?.status === "succeeded" || job?.status === "failed";
}

function issuesFromError(err: unknown): Issue[] {
  if (err instanceof ApiError) {
    const details = err.details
      .filter((d) => typeof d.message === "string")
      .map((d) => ({
        severity: "error" as const,
        code: String((d as { code?: unknown }).code ?? err.code),
        path: d.path ?? "",
        message: d.message,
        suggestion: (d as { suggestion?: string | null }).suggestion ?? null,
      }));
    return details.length > 0
      ? details
      : [{ severity: "error", code: err.code, path: "", message: err.message }];
  }
  return [{ severity: "error", code: "ERROR", path: "", message: String(err) }];
}

/** Stage list driven by the job's real `stage`; no invented percentages. */
export function GenerationProgress({ job }: { job: Job | undefined }) {
  if (!job) return <p className="text-xs text-neutral-500">Starting…</p>;
  if (job.status === "failed") {
    return (
      <div
        role="alert"
        className="rounded-md bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300"
      >
        <p className="font-medium">{job.error?.message ?? "Generation failed"}</p>
        <ul className="mt-1 list-disc pl-4">
          {job.error?.details.map((d, i) => (
            <li key={i}>{d.message}</li>
          ))}
        </ul>
      </div>
    );
  }
  const current = GENERATION_STAGES.findIndex((s) => s.id === job.stage);
  const done = job.status === "succeeded";
  return (
    <ol aria-label="Generation progress" className="flex flex-col gap-1 text-xs">
      {GENERATION_STAGES.map((stage, i) => {
        const state = done || i < current ? "done" : i === current ? "active" : "pending";
        return (
          <li key={stage.id} className="flex items-center gap-2">
            <span
              aria-hidden
              className={
                "inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] " +
                (state === "done"
                  ? "bg-green-600 text-white"
                  : state === "active"
                    ? "animate-pulse bg-blue-600 text-white"
                    : "bg-neutral-200 dark:bg-neutral-800")
              }
            >
              {state === "done" ? "✓" : ""}
            </span>
            <span className={state === "pending" ? "text-neutral-400" : ""}>{stage.label}</span>
          </li>
        );
      })}
      {done && (
        <li className="font-medium text-green-700 dark:text-green-400">Opening the new version…</li>
      )}
    </ol>
  );
}
