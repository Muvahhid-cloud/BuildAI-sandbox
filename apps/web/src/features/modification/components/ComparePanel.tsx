"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/errors";
import type { VersionCompare, VersionSummary } from "@/lib/api/schemas";
import { useHighlightStore } from "@/stores/highlight-store";

import { compareVersions } from "../api";

/**
 * Compare two versions of a project (Phase 5): measured differences computed by the server from
 * both BuildingModels — rooms resized, added, removed, renamed or retyped, doors and windows,
 * walls, gross floor area. When the newer version is the one on screen, its added and changed
 * elements are highlighted in amber in the plan and in 3D.
 */
export function ComparePanel({
  projectId,
  versions,
  shownVersionId,
  onClose,
}: {
  projectId: string;
  versions: readonly VersionSummary[];
  shownVersionId: string | null;
  onClose: () => void;
}) {
  // Newest first: by default the version on screen against its parent (or the one before).
  const shown = versions.find((v) => v.id === shownVersionId) ?? versions[0];
  const parent =
    versions.find((v) => v.id === shown?.parent_version_id) ??
    versions.find((v) => shown && v.number < shown.number);
  const [a, setA] = useState(parent?.id ?? "");
  const [b, setB] = useState(shown?.id ?? "");
  const [result, setResult] = useState<VersionCompare | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => () => useHighlightStore.getState().setIds(null), []);

  const compare = async () => {
    if (!a || !b || a === b) return;
    setBusy(true);
    setError(null);
    try {
      const out = await compareVersions(projectId, a, b);
      setResult(out);
      useHighlightStore
        .getState()
        .setIds(out.b === shownVersionId ? [...out.diff.added, ...out.diff.changed] : null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The versions could not be compared.");
    } finally {
      setBusy(false);
    }
  };

  const option = (v: VersionSummary) => (
    <option key={v.id} value={v.id}>
      v{v.number} · {v.label}
    </option>
  );

  return (
    <div className="flex h-full flex-col" aria-label="Compare versions">
      <header className="flex items-center justify-between border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
        <div>
          <h2 className="font-semibold">Compare versions</h2>
          <p className="text-xs text-neutral-500">
            Every difference is measured on the two models.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="rounded px-2 text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
        >
          ×
        </button>
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 text-xs">
            From
            <select
              aria-label="From version"
              value={a}
              onChange={(e) => setA(e.target.value)}
              className="rounded border border-neutral-300 px-1 py-1 dark:border-neutral-700 dark:bg-neutral-900"
            >
              {versions.map(option)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            To
            <select
              aria-label="To version"
              value={b}
              onChange={(e) => setB(e.target.value)}
              className="rounded border border-neutral-300 px-1 py-1 dark:border-neutral-700 dark:bg-neutral-900"
            >
              {versions.map(option)}
            </select>
          </label>
        </div>
        <button
          type="button"
          onClick={() => void compare()}
          disabled={busy || !a || !b || a === b}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-40"
        >
          {busy ? "Comparing…" : "Compare"}
        </button>
        {error && (
          <p
            role="alert"
            className="rounded-md bg-red-50 p-2 text-xs text-red-800 ring-1 ring-red-200"
          >
            {error}
          </p>
        )}
        {result && (
          <section aria-label="Differences">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-neutral-500">
              v{result.a_number} → v{result.b_number}
            </h3>
            {result.diff.lines.length === 0 ? (
              <p className="text-xs text-neutral-600">The two versions have the same design.</p>
            ) : (
              <ul className="list-disc space-y-0.5 pl-4 text-xs">
                {result.diff.lines.map((l, k) => (
                  <li key={k}>{l.text}</li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-[11px] text-neutral-500">
              {result.b === shownVersionId
                ? `${result.diff.added.length + result.diff.changed.length} added or changed elements are amber in the plan and in 3D.`
                : `Open v${result.b_number} to see its changes highlighted.`}
            </p>
          </section>
        )}
      </div>
    </div>
  );
}
