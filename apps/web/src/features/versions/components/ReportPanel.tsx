"use client";

import { buildingSpecificationSchema } from "@buildai/schema";

import { DISCLAIMER } from "@/lib/disclaimer";
import type { DesignEvaluation, Issue, PatternUse, Topology, Version } from "@/lib/api/schemas";
import { useSelectionStore } from "@/stores/selection-store";

/**
 * What the engine reported for this version (deviations from the spec, notes), the geometric
 * checks (Phase 3.5 K2.5: every element fits the geometry around it) and the rules findings,
 * both evaluated on read. Nothing is hidden: every departure from the request is listed.
 */
export function ReportPanel({ version, onClose }: { version: Version; onClose: () => void }) {
  const select = useSelectionStore((s) => s.select);
  const report = version.report;
  const deviations = report?.warnings.filter((w) => !w.rule_ref) ?? [];
  const rules = version.issues.filter((i) => i.rule_ref);
  const geometry = version.issues.filter((i) => !i.rule_ref && i.constraint);
  const model = version.issues.filter((i) => !i.rule_ref && !i.constraint);
  const metrics = report?.metrics ?? {};
  const parsedSpec = buildingSpecificationSchema.safeParse(version.spec);
  const assumptions = parsedSpec.success ? (parsedSpec.data.assumptions ?? []) : [];

  return (
    <div className="flex h-full min-h-0 flex-col text-sm">
      <div className="flex items-start justify-between border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
        <div>
          <h2 className="font-semibold">Design report · v{version.number}</h2>
          <p className="text-xs text-neutral-500">
            {version.engine_version} · rules {version.rules_profile}
            {version.seed !== null && ` · seed ${version.seed}`}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close report"
          className="rounded-md px-2 text-lg leading-none text-neutral-400 hover:text-neutral-700"
        >
          ×
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
          <dt className="text-neutral-500">Gross floor area</dt>
          <dd className="text-right tabular-nums">
            {version.summary.gross_floor_area_m2} m²
            {typeof metrics.target_gross_floor_area_m2 === "number" &&
              ` (asked ${metrics.target_gross_floor_area_m2} m²)`}
          </dd>
          <dt className="text-neutral-500">Net room area</dt>
          <dd className="text-right tabular-nums">{version.summary.net_floor_area_m2} m²</dd>
          <dt className="text-neutral-500">Floors · rooms</dt>
          <dd className="text-right tabular-nums">
            {version.summary.storeys} · {version.summary.rooms}
          </dd>
          <dt className="text-neutral-500">Bedrooms · bathrooms · WCs</dt>
          <dd className="text-right tabular-nums">
            {version.summary.bedrooms} · {version.summary.bathrooms} · {version.summary.wcs}
          </dd>
          {typeof metrics.candidates_evaluated === "number" && (
            <>
              <dt className="text-neutral-500">Layout candidates</dt>
              <dd className="text-right tabular-nums">{metrics.candidates_evaluated}</dd>
            </>
          )}
        </dl>

        {version.prompt && (
          <section className="mt-4">
            <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
              Request
            </h3>
            <p className="rounded-md bg-neutral-50 p-2 text-xs italic text-neutral-600 dark:bg-neutral-900 dark:text-neutral-300">
              “{version.prompt}”
            </p>
            {report?.generation && (
              <p className="mt-1 text-[11px] text-neutral-400">
                Interpreted by{" "}
                {report.generation.provider === "mock"
                  ? "the offline mock interpreter (development)"
                  : `${report.generation.provider} · ${report.generation.model}`}{" "}
                · prompt {report.generation.prompt_version}
              </p>
            )}
          </section>
        )}
        <Group
          title="Differences from the request"
          issues={deviations}
          onSelect={select}
          empty="None — the layout matches the request."
        />
        {report?.topology && <Footprint topology={report.topology} />}
        {report?.evaluation && <Evaluation evaluation={report.evaluation} />}
        {report?.patterns && report.patterns.length > 0 && <Patterns patterns={report.patterns} />}
        {assumptions.length > 0 && (
          <section className="mt-4">
            <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
              Assumptions <span className="tabular-nums">({assumptions.length})</span>
            </h3>
            <ul className="list-disc pl-4 text-xs text-neutral-600 dark:text-neutral-300">
              {assumptions.map((a, i) => (
                <li key={`${a.path}-${i}`}>{a.reason}</li>
              ))}
            </ul>
          </section>
        )}
        {report && report.notes.length > 0 && (
          <section className="mt-4">
            <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
              Engine notes
            </h3>
            <ul className="list-disc pl-4 text-xs text-neutral-600 dark:text-neutral-300">
              {report.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </section>
        )}
        <Group
          title="Geometry checks"
          issues={geometry}
          onSelect={select}
          empty="None — every opening, wall, room, stair, slab and roof fits the geometry around it."
        />
        <Group
          title={`Rules check · ${version.rules_profile}`}
          issues={rules}
          onSelect={select}
          empty="No findings under the active rules profile."
        />
        {model.length > 0 && (
          <Group title="Model checks" issues={model} onSelect={select} empty="" />
        )}
        <p className="mt-4 rounded-md bg-amber-50 p-2 text-[11px] leading-snug text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Rules profiles perform conceptual checks only; they are not a building-code compliance
          check. {DISCLAIMER}
        </p>
      </div>
    </div>
  );
}

/** Each requirement of the request (mandatory or preference, with the user's words) and the
 * soft criteria the chosen layout was ranked on (layout@1.4.0+). */
function Evaluation({ evaluation }: { evaluation: DesignEvaluation }) {
  return (
    <section className="mt-4" aria-label="Design evaluation">
      <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
        Design evaluation{" "}
        <span className="tabular-nums">· score {Math.round(evaluation.score * 100)}/100</span>
      </h3>
      {evaluation.requirements.length > 0 && (
        <ul className="mb-2 flex flex-col gap-1">
          {evaluation.requirements.map((r) => (
            <li key={r.path} className="text-xs">
              <span
                className={
                  r.met
                    ? "text-emerald-700 dark:text-emerald-400"
                    : "text-amber-800 dark:text-amber-300"
                }
              >
                {r.met ? "✓" : "✗"} {r.label}
              </span>{" "}
              <span className="rounded bg-neutral-100 px-1 text-[10px] uppercase text-neutral-500 dark:bg-neutral-800">
                {r.priority === "must" ? "required" : "preference"}
              </span>
              <span className="block pl-3 text-[11px] text-neutral-500">
                asked {r.expected} · got {r.delivered}
                {r.quote && <span className="italic"> · “{r.quote}”</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      <ul className="flex flex-col gap-0.5">
        {evaluation.criteria.map((c) => (
          <li key={c.key} className="text-xs text-neutral-600 dark:text-neutral-300">
            <span className="inline-block w-9 tabular-nums">{Math.round(c.score * 100)}%</span>
            {c.label}
            {c.weight > 2 && <span className="text-[10px] text-violet-600"> · priority</span>}
            <span className="block pl-9 text-[11px] text-neutral-500">{c.explanation}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const SHAPES: Record<string, string> = {
  rectangular: "Rectangular",
  l_shape: "L-shaped",
  t_shape: "T-shaped",
  u_shape: "U-shaped",
  courtyard: "Courtyard",
  other: "Other",
};

/** Which footprint topology the validated model has, and why it was chosen (layout@1.5.0+). A
 * requested shape that was not generated is shown as such, never as a success. */
function Footprint({ topology }: { topology: Topology }) {
  const missed = topology.requested !== null && topology.requested !== topology.generated;
  return (
    <section className="mt-4" aria-label="Footprint">
      <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
        Footprint
      </h3>
      <p className="text-xs text-neutral-700 dark:text-neutral-200">
        {SHAPES[topology.generated] ?? topology.generated}
        {topology.requested && (
          <span className={missed ? "text-amber-800 dark:text-amber-300" : "text-neutral-500"}>
            {" "}
            · {SHAPES[topology.requested] ?? topology.requested} requested
            {topology.mandatory ? " (required)" : " (preference)"}
            {missed ? " — not generated" : ""}
          </span>
        )}
      </p>
      {topology.limitation && (
        <p className="text-[11px] text-amber-800 dark:text-amber-300">
          Not generated yet: {topology.limitation}
        </p>
      )}
      <p className="text-[11px] text-neutral-500">{topology.explanation}</p>
    </section>
  );
}

/** Layout patterns that steered the search: unreviewed drafts are labelled as such. */
function Patterns({ patterns }: { patterns: PatternUse[] }) {
  return (
    <section className="mt-4" aria-label="Layout patterns">
      <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
        Layout patterns <span className="tabular-nums">({patterns.length})</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {patterns.map((p) => (
          <li key={p.id} className="text-xs text-neutral-600 dark:text-neutral-300">
            {p.name}{" "}
            <span className="rounded bg-amber-100 px-1 text-[10px] uppercase text-amber-900 dark:bg-amber-900 dark:text-amber-100">
              {p.status === "approved" ? "approved" : `${p.status} · experimental`}
            </span>
            <span className="block text-[11px] text-neutral-500">
              because {p.reasons.join("; ")}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[11px] text-neutral-400">
        Patterns are soft design heuristics, not verified architectural standards; they never
        override a requirement.
      </p>
    </section>
  );
}

function Group({
  title,
  issues,
  onSelect,
  empty,
}: {
  title: string;
  issues: Issue[];
  onSelect: (id: string | null) => void;
  empty: string;
}) {
  return (
    <section className="mt-4">
      <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
        {title} {issues.length > 0 && <span className="tabular-nums">({issues.length})</span>}
      </h3>
      {issues.length === 0 ? (
        <p className="text-xs text-neutral-500">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {issues.map((issue, i) => (
            <li key={`${issue.code}-${issue.path}-${i}`} className="text-xs">
              {issue.element_id ? (
                <button
                  type="button"
                  className="text-left text-amber-800 hover:underline dark:text-amber-300"
                  onClick={() => onSelect(issue.element_id ?? null)}
                >
                  {issue.message}
                </button>
              ) : (
                <span className="text-amber-800 dark:text-amber-300">{issue.message}</span>
              )}
              {(issue.rule_ref ?? issue.constraint) && (
                <span className="ml-1 font-mono text-[10px] text-neutral-400">
                  {issue.rule_ref ?? issue.constraint}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
