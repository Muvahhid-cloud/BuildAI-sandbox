"use client";

import { DrawerHeader } from "@/components/ui";
import { Wand2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useEditStore } from "@/features/editing/store";
import { saveEdits } from "@/features/editing/api";
import { ApiError } from "@/lib/api/errors";
import type {
  ClarificationQuestion,
  EditOperation,
  ModifyAnswer,
  ModifyPlan,
  PlannedChange,
  Version,
} from "@/lib/api/schemas";
import { useBuildingStore } from "@/stores/building-store";
import { useHighlightStore } from "@/stores/highlight-store";

import { planModification, resolveModification, restoreVersion } from "../api";

const EXAMPLES = [
  "Make the kitchen 2 metres wider and add another window to the master bedroom",
  "Rename bedroom 3 to Guest bedroom and turn the storage into a laundry",
  "Move the bathroom wall and increase the living room size",
];

const STATUS_STYLE: Record<PlannedChange["status"], { label: string; cls: string }> = {
  planned: { label: "Planned", cls: "bg-green-50 text-green-800 ring-green-200" },
  needs_clarification: { label: "Question", cls: "bg-blue-50 text-blue-800 ring-blue-200" },
  refused: { label: "Not possible", cls: "bg-red-50 text-red-800 ring-red-200" },
  unsupported: { label: "Not supported", cls: "bg-neutral-100 text-fg-muted ring-line" },
};

function errorText(err: unknown): string {
  return err instanceof ApiError
    ? err.message
    : "The request could not be processed. Is the server running?";
}

/**
 * Change an existing design in plain language (Phase 5, docs/ai-pipeline.md §11). The AI only
 * interprets the request; the server turns it into the same typed operations as manual plan
 * editing, asks when something is unclear, and validates the candidate. The candidate is shown in
 * the plan and in 3D (changed elements in amber) until it is applied — saved as a new version —
 * or discarded. After applying, the change can be undone by restoring the previous version.
 */
export function ModifyPanel({
  projectId,
  versionNumber,
  onSaved,
  onClose,
}: {
  projectId: string;
  /** Number of the version being edited (shown when offering to undo). */
  versionNumber: number | null;
  onSaved: (version: Version) => void;
  onClose: () => void;
}) {
  const versionId = useEditStore((s) => s.versionId);
  const ops = useEditStore((s) => s.ops);
  const cursor = useEditStore((s) => s.cursor);
  const sessionOps = useMemo(() => ops.slice(0, cursor), [ops, cursor]);
  const [prompt, setPrompt] = useState("");
  const [plan, setPlan] = useState<ModifyPlan | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"plan" | "resolve" | "apply" | "undo" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ version: Version; base: string; baseLabel: string } | null>(
    null,
  );
  // The session's model before the preview replaced it in the viewer (restored on discard).
  const snapshot = useRef<unknown>(null);
  // Another version opened (not by applying this plan): the plan belonged to the old one.
  const [planFor, setPlanFor] = useState(versionId);
  if (planFor !== versionId) {
    setPlanFor(versionId);
    if (plan !== null) {
      setPlan(null);
      setAnswers({});
    }
  }

  const showPreview = (next: ModifyPlan | null) => {
    const building = useBuildingStore.getState();
    const model = next?.preview?.valid ? next.preview.model : null;
    if (model) {
      if (snapshot.current === null) snapshot.current = building.index?.model ?? null;
      building.load(model);
      useHighlightStore.getState().setIds(next?.preview?.changed_ids ?? []);
    } else {
      restoreSession();
    }
  };

  const restoreSession = () => {
    if (snapshot.current !== null) {
      useBuildingStore.getState().load(snapshot.current);
      snapshot.current = null;
    }
    useHighlightStore.getState().setIds(null);
  };

  // Closing the panel without applying puts the session's model back.
  useEffect(
    () => () => {
      if (snapshot.current !== null) useBuildingStore.getState().load(snapshot.current);
      useHighlightStore.getState().setIds(null);
    },
    [],
  );

  const run = async (kind: "plan" | "resolve", answerList: ModifyAnswer[]) => {
    if (!versionId) return;
    setBusy(kind);
    setError(null);
    try {
      const next =
        kind === "plan" || !plan
          ? await planModification(projectId, versionId, prompt.trim(), sessionOps)
          : await resolveModification(
              projectId,
              versionId,
              plan.prompt,
              plan.draft,
              answerList,
              sessionOps,
            );
      setPlan(next);
      showPreview(next);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const submitAnswers = () => {
    const list = Object.entries(answers)
      .filter(([, v]) => v.trim() !== "")
      .map(([question_id, value]) => ({ question_id, value: value.trim() }));
    // Keep earlier answers too: questions of a later round build on them.
    const merged = new Map((plan?.answers ?? []).map((a) => [a.question_id, a.value]));
    for (const a of list) merged.set(a.question_id, a.value);
    void run(
      "resolve",
      [...merged.entries()].map(([question_id, value]) => ({ question_id, value })),
    );
  };

  const discard = () => {
    restoreSession();
    setPlan(null);
    setAnswers({});
    setError(null);
  };

  const apply = async () => {
    if (!plan || !versionId || !canApply) return;
    setBusy("apply");
    setError(null);
    try {
      const ops = [...sessionOps, ...(plan.operations as unknown as EditOperation[])];
      const version = await saveEdits(projectId, versionId, ops, undefined, {
        prompt: plan.prompt,
      });
      snapshot.current = null; // the saved version replaces the session's model
      useHighlightStore.getState().setIds(plan.preview?.changed_ids ?? []);
      useEditStore.getState().end();
      setSaved({
        version,
        base: versionId,
        baseLabel: versionNumber !== null ? `v${versionNumber}` : "the previous version",
      });
      setPlan(null);
      onSaved(version);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const undo = async () => {
    if (!saved) return;
    setBusy("undo");
    setError(null);
    try {
      const restored = await restoreVersion(projectId, saved.base);
      useHighlightStore.getState().setIds(null);
      setSaved(null);
      onSaved(restored);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const questions = plan?.questions ?? [];
  const planned = plan?.changes.filter((c) => c.status === "planned").length ?? 0;
  const canApply =
    plan !== null &&
    questions.length === 0 &&
    planned > 0 &&
    plan.preview?.valid === true &&
    busy === null;

  return (
    <div className="flex h-full flex-col" aria-label="Modify with AI">
      <DrawerHeader
        icon={<Wand2 size={15} />}
        title={<>Modify with AI</>}
        description={<>Describe changes in plain language. Nothing is saved until you apply it.</>}
        onClose={onClose}
      />

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3 text-sm">
        {saved ? (
          <div
            role="status"
            className="rounded-md bg-green-50 p-3 text-green-900 ring-1 ring-green-200"
          >
            <p className="font-medium">
              Saved as v{saved.version.number} · {saved.version.label}
            </p>
            <p className="mt-1 text-xs">
              The 2D plan and the 3D view show the new version; changed elements are amber.
            </p>
            <div className="mt-2 flex gap-2">
              <PanelButton onClick={() => void undo()} disabled={busy !== null}>
                {busy === "undo" ? "Restoring…" : `Undo — restore ${saved.baseLabel}`}
              </PanelButton>
              <PanelButton
                onClick={() => {
                  useHighlightStore.getState().setIds(null);
                  setSaved(null);
                  setPrompt("");
                }}
              >
                New request
              </PanelButton>
            </div>
          </div>
        ) : (
          <>
            <div>
              <label htmlFor="modify-prompt" className="mb-1 block text-xs font-medium">
                What should change?
              </label>
              <textarea
                id="modify-prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && prompt.trim().length >= 3) {
                    void run("plan", []);
                  }
                }}
                rows={4}
                maxLength={2000}
                placeholder="e.g. Make the kitchen 2 metres wider and add another window to the master bedroom"
                className="w-full rounded-md border border-line-strong bg-surface px-2 py-1.5"
              />
              <div className="mt-1 flex flex-wrap gap-1">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => setPrompt(ex)}
                    className="rounded-full bg-neutral-100 px-2 py-0.5 text-2xs text-fg-muted hover:bg-neutral-200 dark:bg-neutral-800"
                  >
                    {ex}
                  </button>
                ))}
              </div>
              <div className="mt-2 flex gap-2">
                <PanelButton
                  primary
                  onClick={() => void run("plan", [])}
                  disabled={busy !== null || prompt.trim().length < 3 || !versionId}
                >
                  {busy === "plan" ? "Interpreting…" : "Preview changes"}
                </PanelButton>
                {plan && (
                  <PanelButton onClick={discard} disabled={busy !== null}>
                    Discard
                  </PanelButton>
                )}
              </div>
              {sessionOps.length > 0 && (
                <p className="mt-1 text-2xs text-fg-subtle">
                  Builds on your {sessionOps.length} unsaved plan edit
                  {sessionOps.length > 1 ? "s" : ""}; applying saves them too.
                </p>
              )}
            </div>

            {plan && (
              <PlanView
                plan={plan}
                answers={answers}
                onAnswer={(id, value) => setAnswers((a) => ({ ...a, [id]: value }))}
                onSubmitAnswers={submitAnswers}
                busy={busy}
              />
            )}
          </>
        )}

        {error && (
          <p
            role="alert"
            className="rounded-md bg-red-50 p-2 text-xs text-red-800 ring-1 ring-red-200"
          >
            {error}
          </p>
        )}
      </div>

      {plan && !saved && (
        <footer className="border-t border-line px-4 py-3">
          {questions.length > 0 ? (
            <p className="text-xs text-fg-muted">Answer the questions above to continue.</p>
          ) : planned === 0 ? (
            <p className="text-xs text-fg-muted">Nothing in this request can be applied.</p>
          ) : (
            <p className="mb-2 text-xs text-fg-muted">
              {planned} change{planned > 1 ? "s" : ""} ready
              {plan.status === "partial" ? " — the rest cannot be applied (see above)" : ""}.
              Applying saves a new version; the current one stays unchanged.
            </p>
          )}
          <div className="flex gap-2">
            <PanelButton primary onClick={() => void apply()} disabled={!canApply}>
              {busy === "apply" ? "Saving…" : "Apply & save as new version"}
            </PanelButton>
            <PanelButton onClick={discard} disabled={busy !== null}>
              Discard
            </PanelButton>
          </div>
        </footer>
      )}
    </div>
  );
}

function PlanView({
  plan,
  answers,
  onAnswer,
  onSubmitAnswers,
  busy,
}: {
  plan: ModifyPlan;
  answers: Record<string, string>;
  onAnswer: (id: string, value: string) => void;
  onSubmitAnswers: () => void;
  busy: string | null;
}) {
  const preview = plan.preview;
  return (
    <div className="space-y-3">
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-fg-subtle">
          Understood
        </h3>
        <p className="text-fg">{plan.understanding}</p>
      </section>

      <section aria-label="Requested changes">
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-fg-subtle">
          Requested changes
        </h3>
        <ol className="space-y-1.5">
          {plan.changes.map((c) => (
            <li key={c.index} className="rounded-md border border-line p-2">
              <div className="flex items-start gap-2">
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${STATUS_STYLE[c.status].cls}`}
                >
                  {STATUS_STYLE[c.status].label}
                </span>
                <div className="min-w-0">
                  <p className="text-xs italic text-fg-subtle">“{c.quote}”</p>
                  <p className="text-xs">
                    {c.status === "refused" ? (c.reason ?? c.summary) : c.summary}
                  </p>
                </div>
              </div>
            </li>
          ))}
          {plan.unsupported.map((u, k) => (
            <li key={`u${k}`} className="rounded-md border border-line p-2">
              <div className="flex items-start gap-2">
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${STATUS_STYLE.unsupported.cls}`}
                >
                  {STATUS_STYLE.unsupported.label}
                </span>
                <div className="min-w-0">
                  <p className="text-xs italic text-fg-subtle">“{u.quote}”</p>
                  <p className="text-xs">{u.reason}</p>
                </div>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {plan.questions.length > 0 && (
        <section
          aria-label="Questions"
          className="rounded-md bg-blue-50/60 p-2 ring-1 ring-blue-200 dark:bg-blue-950/20"
        >
          <h3 className="mb-1 text-xs font-semibold text-blue-900 dark:text-blue-300">
            Please clarify
          </h3>
          <div className="space-y-2">
            {plan.questions.map((q) => (
              <Question key={q.id} question={q} value={answers[q.id] ?? ""} onChange={onAnswer} />
            ))}
          </div>
          <div className="mt-2">
            <PanelButton
              primary
              onClick={onSubmitAnswers}
              disabled={busy !== null || plan.questions.some((q) => !(answers[q.id] ?? "").trim())}
            >
              {busy === "resolve" ? "Checking…" : "Continue"}
            </PanelButton>
          </div>
        </section>
      )}

      {plan.diff && plan.diff.lines.length > 0 && (
        <section aria-label="Measured changes">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-fg-subtle">
            What changes (measured on the model)
          </h3>
          <ul className="list-disc space-y-0.5 pl-4 text-xs">
            {plan.diff.lines.map((l, k) => (
              <li key={k}>{l.text}</li>
            ))}
          </ul>
          <p className="mt-1 text-2xs text-fg-subtle">
            Shown in the plan and in 3D; changed elements are amber.
          </p>
        </section>
      )}

      {preview && !preview.valid && (
        <p
          role="alert"
          className="rounded-md bg-red-50 p-2 text-xs text-red-800 ring-1 ring-red-200"
        >
          {preview.rejection?.message ?? "The combined changes are not valid."}
        </p>
      )}
      {preview?.valid && preview.warnings.length > 0 && (
        <ul className="list-disc rounded-md bg-amber-50 p-2 pl-6 text-xs text-amber-900 ring-1 ring-amber-200">
          {preview.warnings.slice(0, 5).map((w, k) => (
            <li key={k}>{w.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Question({
  question: q,
  value,
  onChange,
}: {
  question: ClarificationQuestion;
  value: string;
  onChange: (id: string, value: string) => void;
}) {
  return (
    <fieldset>
      <legend className="mb-1 text-xs text-fg">{q.text}</legend>
      {q.options.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {q.options.map((o) => (
            <button
              key={o.value}
              type="button"
              aria-pressed={value === o.value}
              onClick={() => onChange(q.id, o.value)}
              className={
                "rounded px-2 py-1 text-xs ring-1 " +
                (value === o.value
                  ? "bg-blue-600 text-white ring-blue-600"
                  : "bg-surface text-fg ring-line hover:bg-neutral-50")
              }
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
      {q.input !== "choice" && (
        <input
          type={q.input === "number" ? "number" : "text"}
          aria-label={q.text}
          min={q.input === "number" ? 0.05 : undefined}
          step={q.input === "number" ? 0.05 : undefined}
          value={value}
          onChange={(e) => onChange(q.id, e.target.value)}
          className="mt-1 w-40 rounded border border-line-strong px-1.5 py-0.5 text-xs"
          placeholder={q.input === "number" ? "metres" : ""}
        />
      )}
    </fieldset>
  );
}

function PanelButton({
  onClick,
  disabled,
  primary,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={
        "rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-40 " +
        (primary
          ? "bg-blue-600 text-white hover:bg-blue-700"
          : "bg-neutral-100 text-fg hover:bg-neutral-200 dark:bg-neutral-800")
      }
    >
      {children}
    </button>
  );
}
