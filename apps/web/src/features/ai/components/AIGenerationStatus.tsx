"use client";

import type { AIGenerationOut } from "@buildai/schema";
import { useState } from "react";

import { AI_STAGES } from "../api";

/**
 * Progress of one generation, driven only by the backend's real `stage` (no invented
 * percentages), plus the clarification and failure states.
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
    return <p className="text-sm text-neutral-500">Starting the generation…</p>;
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
  return (
    <div className="flex flex-col gap-3">
      <p className="rounded-md bg-neutral-50 p-3 text-sm italic text-neutral-600 dark:bg-neutral-900 dark:text-neutral-300">
        “{generation.prompt}”
      </p>
      <ol aria-label="Generation progress" className="flex flex-col gap-2 text-sm">
        {stages.map((stage, i) => {
          const state =
            done || i < current ? "done" : i === current ? "active" : ("pending" as const);
          return (
            <li key={stage.id} className="flex items-center gap-2.5">
              <StepIcon state={state} />
              <span
                className={
                  state === "pending"
                    ? "text-neutral-400"
                    : state === "active"
                      ? "font-medium"
                      : "text-neutral-700 dark:text-neutral-300"
                }
              >
                {stage.label}
              </span>
            </li>
          );
        })}
        <li className="flex items-center gap-2.5">
          <StepIcon state={done ? "active" : "pending"} />
          <span className={done ? "font-medium" : "text-neutral-400"}>
            Building the 3D model and opening the project
          </span>
        </li>
      </ol>
      {generation.understanding && (
        <p className="text-xs text-neutral-500">
          <span className="font-medium">Understood:</span> {generation.understanding}
        </p>
      )}
      <p className="text-xs text-neutral-400">
        {generation.provider === "mock"
          ? "Offline mock interpreter (development mode)"
          : `AI: ${generation.provider} · ${generation.model}`}
      </p>
    </div>
  );
}

function StepIcon({ state }: { state: "done" | "active" | "pending" }) {
  return (
    <span
      aria-hidden
      className={
        "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] " +
        (state === "done"
          ? "bg-green-600 text-white"
          : state === "active"
            ? "animate-pulse bg-blue-600 text-white"
            : "border border-neutral-300 dark:border-neutral-700")
      }
    >
      {state === "done" ? "✓" : ""}
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
      <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
        <p className="font-medium">A few details are needed before designing the building.</p>
        {generation.understanding && <p className="mt-1 text-xs">{generation.understanding}</p>}
        {nonBuilding.map((w) => (
          <p key={w.message} className="mt-1 text-xs">
            {w.message}
          </p>
        ))}
      </div>
      {generation.clarification_questions.map((question, i) => (
        <label key={question} className="flex flex-col gap-1 text-sm">
          <span>{question}</span>
          <input
            value={answers[i] ?? ""}
            onChange={(e) =>
              setAnswers((prev) => prev.map((a, j) => (j === i ? e.target.value : a)))
            }
            className="rounded-md border border-neutral-300 bg-white px-2 py-1.5 dark:border-neutral-700 dark:bg-neutral-900"
          />
        </label>
      ))}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onEdit}
          className="rounded-md px-3 py-1.5 text-sm text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
        >
          Edit description
        </button>
        <button
          type="button"
          disabled={answered.length === 0}
          onClick={() =>
            onContinue(
              `${generation.prompt}\n\nAdditional details:\n` +
                answered.map(([q, a]) => `- ${q} ${a}`).join("\n"),
            )
          }
          className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Continue
        </button>
      </div>
    </div>
  );
}

function Failure({ generation, onRetry }: { generation: AIGenerationOut; onRetry: () => void }) {
  const error = generation.error;
  const details = error?.details ?? [];
  return (
    <div className="flex flex-col gap-3">
      <div
        role="alert"
        className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
      >
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
      </div>
      {generation.warnings.length > 0 && (
        <div className="rounded-md bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <p className="font-medium">Also noted while reading your request:</p>
          <ul className="mt-1 list-disc pl-4">
            {generation.warnings.map((w, i) => (
              <li key={`${w.code}-${i}`}>{w.message}</li>
            ))}
          </ul>
        </div>
      )}
      <button
        type="button"
        onClick={onRetry}
        className="self-end rounded-md bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-blue-700"
      >
        Edit and try again
      </button>
    </div>
  );
}
