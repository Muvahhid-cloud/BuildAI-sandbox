"use client";

import type { AIGenerationOut } from "@buildai/schema";
import { useState } from "react";

import { DISCLAIMER } from "@/lib/disclaimer";
import { formatMoney } from "@/lib/format";
import { useSelectionStore } from "@/stores/selection-store";

/**
 * Shown over the 3D view after an AI generation: what was built, how it compares with the
 * request, and every warning and assumption. Deviations are never hidden.
 */
export function GenerationSummary({
  generation,
  onDismiss,
  onOpenReport,
}: {
  generation: AIGenerationOut;
  onDismiss: () => void;
  onOpenReport?: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const select = useSelectionStore((s) => s.select);
  const spec = generation.specification;
  const s = generation.summary;
  const unmet = generation.checks.filter((c) => !c.met);
  const warnings = generation.warnings;

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className="rounded-full border border-green-200 bg-white/95 px-3 py-1.5 text-xs font-medium text-green-800 shadow-md backdrop-blur hover:bg-white dark:border-green-900 dark:bg-neutral-950/90 dark:text-green-300"
      >
        ✓ {spec?.name ?? "Generated building"} · {warnings.length} note
        {warnings.length === 1 ? "" : "s"} · show summary
      </button>
    );
  }

  return (
    <section
      aria-label="Generation summary"
      className="flex max-h-[min(70vh,640px)] w-[min(92vw,380px)] flex-col overflow-hidden rounded-xl border border-neutral-200 bg-white/95 text-sm shadow-xl backdrop-blur dark:border-neutral-800 dark:bg-neutral-950/95"
    >
      <header className="flex items-start gap-2 border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-wider text-green-700 dark:text-green-400">
            Building generated successfully
          </p>
          <h2 className="truncate text-base font-semibold">{spec?.name ?? "Generated building"}</h2>
          {generation.version_number !== null && (
            <p className="text-xs text-neutral-500">Saved as version {generation.version_number}</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          aria-label="Collapse summary"
          className="rounded px-1.5 text-neutral-400 hover:text-neutral-700"
        >
          –
        </button>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Close summary"
          className="rounded px-1.5 text-lg leading-none text-neutral-400 hover:text-neutral-700"
        >
          ×
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {s && (
          <dl className="grid grid-cols-3 gap-2 text-center">
            <Stat label={s.storeys === 1 ? "floor" : "floors"} value={s.storeys} />
            <Stat label="m² gross" value={s.gross_floor_area_m2} />
            <Stat label="rooms" value={s.rooms} />
            <Stat label="bedrooms" value={s.bedrooms} />
            <Stat label="bathrooms" value={s.bathrooms} />
            <Stat label="garage" value={s.garage ? "yes" : "no"} />
          </dl>
        )}

        {generation.checks.length > 0 && (
          <Block title="Requested vs generated">
            <table className="w-full text-xs">
              <tbody>
                {generation.checks.map((c) => (
                  <tr
                    key={c.key}
                    className="border-b border-neutral-100 last:border-0 dark:border-neutral-900"
                  >
                    <td className="py-1 text-neutral-500">{c.label}</td>
                    <td className="py-1 text-right tabular-nums">{c.requested}</td>
                    <td className="px-1 py-1 text-neutral-400">→</td>
                    <td className="py-1 tabular-nums">{c.delivered}</td>
                    <td className="py-1 text-right">
                      {c.met ? (
                        <span className="text-green-600" aria-label="met">
                          ✓
                        </span>
                      ) : (
                        <span className="text-amber-600" aria-label="deviation">
                          ⚠
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {unmet.length === 0 && (
              <p className="mt-1 text-xs text-green-700 dark:text-green-400">
                All key requirements were met.
              </p>
            )}
          </Block>
        )}

        <Block title={`Warnings (${warnings.length})`}>
          {warnings.length === 0 ? (
            <p className="text-xs text-neutral-500">None.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-xs">
              {warnings.map((w, i) => (
                <li key={`${w.code}-${i}`} className="text-amber-800 dark:text-amber-300">
                  {w.element_id ? (
                    <button
                      type="button"
                      onClick={() => select(w.element_id ?? null)}
                      className="text-left hover:underline"
                    >
                      {w.message}
                    </button>
                  ) : (
                    w.message
                  )}
                </li>
              ))}
            </ul>
          )}
        </Block>

        <Block title={`Assumptions (${generation.assumptions.length})`}>
          {generation.assumptions.length === 0 ? (
            <p className="text-xs text-neutral-500">None — everything came from your request.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-xs text-neutral-700 dark:text-neutral-300">
              {generation.assumptions.map((a, i) => (
                <li key={`${a.path}-${i}`}>{a.reason}</li>
              ))}
            </ul>
          )}
        </Block>

        {spec?.budget && (
          <Block title="Budget (constraint only)">
            <p className="text-xs">
              {formatMoney(spec.budget.amount, spec.budget.currency, { minorUnits: 0 })} — recorded
              with the design; no cost estimate is made in this version.
            </p>
          </Block>
        )}

        {generation.understanding && (
          <Block title="What the AI understood">
            <p className="text-xs text-neutral-600 dark:text-neutral-300">
              {generation.understanding}
            </p>
          </Block>
        )}

        <p className="mt-3 text-[11px] text-neutral-400">
          {generation.provider === "mock"
            ? "Offline mock interpreter (development)"
            : `${generation.provider} · ${generation.model}`}{" "}
          · {generation.engine_version} · rules {generation.rules_profile} · seed {generation.seed}
        </p>
        <p className="mt-2 text-[11px] leading-snug text-neutral-500">{DISCLAIMER}</p>
      </div>

      {onOpenReport && (
        <footer className="border-t border-neutral-200 px-4 py-2 dark:border-neutral-800">
          <button type="button" onClick={onOpenReport} className="text-xs text-blue-600 underline">
            Open the full design report
          </button>
        </footer>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md bg-neutral-50 px-2 py-1.5 dark:bg-neutral-900">
      <dd className="text-base font-semibold tabular-nums">{value}</dd>
      <dt className="text-[11px] text-neutral-500">{label}</dt>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-3">
      <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
        {title}
      </h3>
      {children}
    </section>
  );
}
