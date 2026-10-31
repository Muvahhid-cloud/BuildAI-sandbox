"use client";

import type { ArchitecturalStyle, GenerationOptions } from "@buildai/schema";
import { useId, useState, type FormEvent } from "react";

import { EXAMPLE_PROMPTS } from "../api";

export const MAX_PROMPT_CHARS = 4000;

const STYLES: ArchitecturalStyle[] = [
  "modern",
  "minimalist",
  "contemporary",
  "classic",
  "traditional",
  "scandinavian",
  "industrial",
  "mediterranean",
  "luxury",
];

export interface AIPromptFormProps {
  prompt: string;
  onPromptChange: (prompt: string) => void;
  onSubmit: (prompt: string, options: Partial<GenerationOptions>) => void;
  pending?: boolean;
  error?: string | null;
  defaultCurrency?: string;
  /** Larger typography for the dashboard hero. */
  size?: "hero" | "panel";
}

interface Details {
  area: string;
  storeys: string;
  style: string;
  budget: string;
  currency: string;
  region: string;
}

/**
 * The natural-language description is the main input; the structured details are optional
 * and, when filled, are sent as explicit requirements the AI must honour.
 */
export function AIPromptForm({
  prompt,
  onPromptChange,
  onSubmit,
  pending = false,
  error,
  defaultCurrency = "KZT",
  size = "panel",
}: AIPromptFormProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState<Details>({
    area: "",
    storeys: "",
    style: "",
    budget: "",
    currency: defaultCurrency,
    region: "",
  });
  const trimmed = prompt.trim();
  const tooLong = prompt.length > MAX_PROMPT_CHARS;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (trimmed.length < 3 || tooLong || pending) return;
    onSubmit(trimmed, toOptions(details));
  }

  const set = (patch: Partial<Details>) => setDetails((d) => ({ ...d, ...patch }));
  const input =
    "w-full rounded-md border border-neutral-300 bg-white px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900";

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" aria-label="Describe your building">
      <label htmlFor={`${id}-prompt`} className="sr-only">
        Building description
      </label>
      <textarea
        id={`${id}-prompt`}
        value={prompt}
        onChange={(e) => onPromptChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
        }}
        rows={size === "hero" ? 5 : 6}
        placeholder="Describe the building you want: size, floors, rooms, style, garage, balcony…"
        disabled={pending}
        className={
          "w-full resize-y rounded-lg border border-neutral-300 bg-white px-3 py-2.5 leading-relaxed shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 disabled:opacity-60 dark:border-neutral-700 dark:bg-neutral-900 " +
          (size === "hero" ? "text-base" : "text-sm")
        }
      />
      <div className="flex items-center justify-between text-xs text-neutral-500">
        <span>Ctrl + Enter to generate</span>
        <span className={tooLong ? "text-red-600" : "tabular-nums"}>
          {prompt.length} / {MAX_PROMPT_CHARS}
        </span>
      </div>

      <div>
        <p className="mb-1.5 text-xs font-medium text-neutral-500">Try an example</p>
        <ul className="flex flex-wrap gap-1.5">
          {EXAMPLE_PROMPTS.map((example) => (
            <li key={example}>
              <button
                type="button"
                onClick={() => onPromptChange(example)}
                disabled={pending}
                title={example}
                className="max-w-[18rem] truncate rounded-full border border-neutral-200 bg-neutral-50 px-3 py-1 text-left text-xs text-neutral-700 hover:border-blue-300 hover:bg-blue-50 disabled:opacity-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-lg border border-neutral-200 dark:border-neutral-800">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-neutral-700 dark:text-neutral-300"
        >
          <span>
            Optional details{" "}
            <span className="text-xs text-neutral-500">— area, floors, style, budget, region</span>
          </span>
          <span aria-hidden className="text-neutral-400">
            {open ? "−" : "+"}
          </span>
        </button>
        {open && (
          <div className="grid grid-cols-2 gap-3 border-t border-neutral-200 p-3 text-sm dark:border-neutral-800">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-neutral-500">Approx. area (m²)</span>
              <input
                type="number"
                min={20}
                max={2000}
                inputMode="numeric"
                value={details.area}
                onChange={(e) => set({ area: e.target.value })}
                className={input}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-neutral-500">Floors</span>
              <select
                value={details.storeys}
                onChange={(e) => set({ storeys: e.target.value })}
                className={input}
              >
                <option value="">Any</option>
                <option value="1">1</option>
                <option value="2">2</option>
                <option value="3">3</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-neutral-500">Style</span>
              <select
                value={details.style}
                onChange={(e) => set({ style: e.target.value })}
                className={input}
              >
                <option value="">From the description</option>
                {STYLES.map((s) => (
                  <option key={s} value={s}>
                    {s[0]!.toUpperCase() + s.slice(1)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-neutral-500">Region code</span>
              <input
                value={details.region}
                onChange={(e) => set({ region: e.target.value.toUpperCase() })}
                placeholder="e.g. KZ-ALA"
                maxLength={16}
                className={input}
              />
            </label>
            <label className="col-span-2 flex flex-col gap-1">
              <span className="text-xs text-neutral-500">
                Budget (a constraint only — no costs are estimated yet)
              </span>
              <div className="flex gap-2">
                <input
                  type="number"
                  min={1}
                  inputMode="numeric"
                  value={details.budget}
                  onChange={(e) => set({ budget: e.target.value })}
                  aria-label="Budget amount"
                  className={input}
                />
                <select
                  value={details.currency}
                  onChange={(e) => set({ currency: e.target.value })}
                  aria-label="Budget currency"
                  className={input + " w-24"}
                >
                  {["KZT", "USD", "EUR"].map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </div>
            </label>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={pending || trimmed.length < 3 || tooLong}
        className={
          "rounded-lg bg-blue-600 font-semibold uppercase tracking-wide text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 " +
          (size === "hero" ? "px-6 py-3 text-sm" : "px-4 py-2.5 text-sm")
        }
      >
        {pending ? "Starting…" : "Generate 3D building"}
      </button>
    </form>
  );
}

function toOptions(d: Details): Partial<GenerationOptions> {
  const options: Partial<GenerationOptions> = {};
  const area = Number(d.area);
  if (d.area && Number.isFinite(area)) options.gross_floor_area_m2 = area;
  if (d.storeys) options.storeys = Number(d.storeys);
  if (d.style) options.architectural_style = d.style as ArchitecturalStyle;
  if (d.region.trim()) options.region_code = d.region.trim();
  // Budget amounts travel as decimal strings (never JS float math for money).
  if (d.budget && /^\d+(\.\d{1,2})?$/.test(d.budget)) {
    options.budget = { amount: d.budget, currency: d.currency };
  }
  return options;
}
