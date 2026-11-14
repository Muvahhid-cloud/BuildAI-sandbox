"use client";

import type { AIGenerationOut } from "@buildai/schema";
import { Check } from "lucide-react";
import { useState } from "react";

import { Button, Callout, Input, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";

import { AI_STAGES } from "../api";
import { InterimFacts } from "./InterimFacts";

/**
 * Progress of one generation, driven only by the backend's real `stage` (no invented
 * percentages) and the facts the AI has stated so far, plus the clarification and failure
 * states.
 */
export function AIGenerationStatus({
  generation,
  onClarified,
  onRetry,
}: {
  generation: AIGenerationOut | undefined;
  /** Continue with the user's answers appended to the original description. */
  onClarified: (prompt: string) => void;
  /** Go back to the prompt to edit it. */
  onRetry: () => void;
}) {
  if (!generation) {
    return (
      <div role="status" className="flex flex-col gap-3">
        <span className="text-sm text-fg-subtle">Starting the generation…</span>
        <Skeleton className="h-1 w-full" />
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }
  if (generation.status === "needs_clarification") {
    return <Clarification generation={generation} onContinue={onClarified} onEdit={onRetry} />;
  }
  if (generation.status === "failed") {
    return <Failure generation={generation} onRetry={onRetry} />;
  }
  return <StageList generation={generation} />;
}

export function StageList({ generation }: { generation: AIGenerationOut }) {
  const stages = AI_STAGES.filter(
    (s) => s.id !== "repairing" || generation.stage === "repairing" || generation.repair_count > 0,
  );
  const done = generation.status === "completed";
  const current = stages.findIndex((s) => s.id === generation.stage);
  // Only what the backend reports: a step is done when the backend has moved past it.
  const steps: { id: string; label: string; state: StepState }[] = stages.map((stage, i) => ({
    id: stage.id as string,
    label: stage.label as string,
    state: (done || i < current ? "done" : i === current ? "active" : "pending") as StepState,
  }));
  const active = steps.find((s) => s.state === "active");
  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-[15px] font-semibold leading-tight tracking-tight">
          Designing your building
        </p>
        <p className="mt-0.5 text-xs text-fg-subtle">Every step below is the real backend stage</p>
        <p className="sr-only" aria-live="polite">
          {done ? "The new version is saved." : active ? `${active.label}…` : "Waiting to start…"}
        </p>
      </div>
      <p className="rounded-lg border border-line bg-bg-subtle p-3 text-sm italic text-fg-muted">
        “{generation.prompt}”
      </p>
      <ol aria-label="Generation progress" className="flex flex-col text-sm">
        {steps.map((step, i) => (
          <li key={step.id} className="relative flex items-center gap-3 py-1.5">
            {i < steps.length - 1 && (
              <span
                aria-hidden
                className={cn(
                  "absolute left-[9px] top-[26px] h-[calc(100%-18px)] w-px transition-colors duration-500",
                  step.state === "done" ? "bg-accent/50" : "bg-line",
                )}
              />
            )}
            <StepIcon state={step.state} />
            <span
              className={cn(
                "transition-colors duration-300",
                step.state === "pending"
                  ? "text-fg-subtle"
                  : step.state === "active"
                    ? "font-medium text-fg"
                    : "text-fg-muted",
              )}
            >
              {step.label}
            </span>
          </li>
        ))}
      </ol>
      <InterimFacts facts={generation.interim_facts ?? []} />
      {generation.understanding && (
        <p className="text-xs text-fg-subtle">
          <span className="font-medium text-fg-muted">In one sentence:</span>{" "}
          {generation.understanding}
        </p>
      )}
      <p className="text-xs text-fg-subtle">
        {generation.provider === "mock"
          ? "Offline mock interpreter (development mode)"
          : `AI: ${generation.provider} · ${generation.model}`}
      </p>
    </div>
  );
}

type StepState = "done" | "active" | "pending";

function StepIcon({ state }: { state: StepState }) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative z-10 inline-flex h-[19px] w-[19px] shrink-0 items-center justify-center rounded-full transition-colors duration-300",
        state === "done"
          ? "bg-accent text-accent-fg"
          : state === "active"
            ? "border-2 border-accent bg-surface"
            : "border border-line-strong bg-surface",
      )}
    >
      {state === "done" && (
        <>
          <span className="sr-only">✓</span>
          <Check size={12} strokeWidth={3} />
        </>
      )}
      {state === "active" && <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />}
    </span>
  );
}

function Clarification({
  generation,
  onContinue,
  onEdit,
}: {
  generation: AIGenerationOut;
  onContinue: (prompt: string) => void;
  onEdit: () => void;
}) {
  const [answers, setAnswers] = useState<string[]>(() =>
    generation.clarification_questions.map(() => ""),
  );
  const answered = generation.clarification_questions
    .map((q, i) => [q, answers[i]?.trim() ?? ""] as const)
    .filter(([, a]) => a.length > 0);
  const nonBuilding = generation.warnings.filter((w) => w.code === "AI_UNSUPPORTED_REQUEST");

  return (
    <div className="flex flex-col gap-3" role="group" aria-label="Clarification needed">
      <Callout tone="warning">
        <p className="font-medium">A few details are needed before designing the building.</p>
        {generation.understanding && <p className="mt-1 text-xs">{generation.understanding}</p>}
        {nonBuilding.map((w) => (
          <p key={w.message} className="mt-1 text-xs">
            {w.message}
          </p>
        ))}
      </Callout>
      {generation.clarification_questions.map((question, i) => (
        <label key={question} className="flex flex-col gap-1 text-sm">
          <span>{question}</span>
          <Input
            value={answers[i] ?? ""}
            onChange={(e) =>
              setAnswers((prev) => prev.map((a, j) => (j === i ? e.target.value : a)))
            }
          />
        </label>
      ))}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onEdit}>
          Edit description
        </Button>
        <Button
          variant="primary"
          disabled={answered.length === 0}
          onClick={() =>
            onContinue(
              `${generation.prompt}\n\nAdditional details:\n` +
                answered.map(([q, a]) => `- ${q} ${a}`).join("\n"),
            )
          }
        >
          Continue
        </Button>
      </div>
    </div>
  );
}

function Failure({ generation, onRetry }: { generation: AIGenerationOut; onRetry: () => void }) {
  const error = generation.error;
  const details = error?.details ?? [];
  return (
    <div className="flex flex-col gap-3">
      <Callout tone="danger" role="alert">
        <p className="font-medium">{error?.message ?? "Generation failed."}</p>
        {details.length > 0 && (
          <ul className="mt-2 list-disc pl-4 text-xs">
            {details.slice(0, 8).map((d, i) => (
              <li key={i}>
                {d.message}
                {d.suggestion && <span className="opacity-75"> — {d.suggestion}</span>}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 font-mono text-[10px] opacity-60">
          {error?.code} · stage {generation.stage}
        </p>
      </Callout>
      {generation.warnings.length > 0 && (
        <Callout tone="warning" className="text-xs">
          <p className="font-medium">Also noted while reading your request:</p>
          <ul className="mt-1 list-disc pl-4">
            {generation.warnings.map((w, i) => (
              <li key={`${w.code}-${i}`}>{w.message}</li>
            ))}
          </ul>
        </Callout>
      )}
      <Button variant="primary" onClick={onRetry} className="self-end">
        Edit and try again
      </Button>
    </div>
  );
}
