"use client";

import type { ArchitecturalStyle, GenerationOptions } from "@buildai/schema";
import { ChevronDown, SlidersHorizontal, Sparkles } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { Button, Input, Kbd, Select } from "@/components/ui";
import { cn } from "@/lib/cn";

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
  const hero = size === "hero";
  const label = "flex flex-col gap-1";
  const caption = "text-xs text-fg-subtle";

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" aria-label="Describe your building">
      <label htmlFor={`${id}-prompt`} className="sr-only">
        Building description
      </label>
      {/* The prompt box: text, counter and the primary action in one focusable surface. */}
      <div
        className={cn(
          "group rounded-2xl border border-line-strong bg-surface transition-[border-color,box-shadow] duration-200",
          "focus-within:border-accent focus-within:shadow-glow",
          hero ? "shadow-md" : "shadow-xs",
        )}
      >
        <textarea
          id={`${id}-prompt`}
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
          }}
          rows={hero ? 4 : 6}
          placeholder="Describe the building you want: size, floors, rooms, style, garage, balcony…"
          disabled={pending}
          className={cn(
            "block w-full resize-none rounded-t-2xl bg-transparent px-4 pt-3.5 leading-relaxed text-fg outline-none placeholder:text-fg-subtle disabled:opacity-60",
            hero ? "text-base sm:text-[17px]" : "text-sm",
          )}
        />
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 pb-3 pt-1">
          <span className="hidden items-center gap-1 text-xs text-fg-subtle sm:inline-flex">
            <Kbd>Ctrl</Kbd>
            <Kbd>Enter</Kbd>
            <span className="ml-0.5">to generate</span>
          </span>
          <span
            className={cn(
              "ml-auto text-xs tabular-nums",
              tooLong ? "font-medium text-red-600 dark:text-red-400" : "text-fg-subtle",
            )}
          >
            {prompt.length} / {MAX_PROMPT_CHARS}
          </span>
          <Button
            type="submit"
            variant="primary"
            size={hero ? "lg" : "md"}
            disabled={pending || trimmed.length < 3 || tooLong}
            loading={pending}
            icon={<Sparkles size={hero ? 16 : 14} />}
            className={hero ? "px-5" : undefined}
          >
            {pending ? "Starting…" : "Generate 3D building"}
          </Button>
        </div>
      </div>

      <div>
        <p className="mb-1.5 text-xs font-medium text-fg-subtle">Try an example</p>
        <ul className="flex flex-wrap gap-1.5">
          {EXAMPLE_PROMPTS.map((example) => (
            <li key={example} className="min-w-0 max-w-full">
              <button
                type="button"
                onClick={() => onPromptChange(example)}
                disabled={pending}
                title={example}
                className="block max-w-full truncate rounded-full border border-line bg-surface px-3 py-1 text-left text-xs text-fg-muted shadow-xs transition-colors duration-150 hover:border-accent hover:bg-accent-soft hover:text-accent-text disabled:opacity-50 sm:max-w-[19rem]"
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-xl border border-line bg-surface">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-left text-sm text-fg-muted transition-colors hover:text-fg"
        >
          <span className="flex items-center gap-2">
            <SlidersHorizontal size={14} aria-hidden className="text-fg-subtle" />
            <span>
              Optional details{" "}
              <span className="text-xs text-fg-subtle">— area, floors, style, budget, region</span>
            </span>
          </span>
          <ChevronDown
            size={15}
            aria-hidden
            className={cn("text-fg-subtle transition-transform duration-200", open && "rotate-180")}
          />
        </button>
        {open && (
          <div className="grid animate-fade-in grid-cols-2 gap-3 border-t border-line p-3 text-sm">
            <label className={label}>
              <span className={caption}>Approx. area (m²)</span>
              <Input
                type="number"
                min={20}
                max={2000}
                inputMode="numeric"
                value={details.area}
                onChange={(e) => set({ area: e.target.value })}
              />
            </label>
            <label className={label}>
              <span className={caption}>Floors</span>
              <Select value={details.storeys} onChange={(e) => set({ storeys: e.target.value })}>
                <option value="">Any</option>
                <option value="1">1</option>
                <option value="2">2</option>
                <option value="3">3</option>
              </Select>
            </label>
            <label className={label}>
              <span className={caption}>Style</span>
              <Select value={details.style} onChange={(e) => set({ style: e.target.value })}>
                <option value="">From the description</option>
                {STYLES.map((s) => (
                  <option key={s} value={s}>
                    {s[0]!.toUpperCase() + s.slice(1)}
                  </option>
                ))}
              </Select>
            </label>
            <label className={label}>
              <span className={caption}>Region code</span>
              <Input
                value={details.region}
                onChange={(e) => set({ region: e.target.value.toUpperCase() })}
                placeholder="e.g. KZ-ALA"
                maxLength={16}
              />
            </label>
            <label className={cn(label, "col-span-2")}>
              <span className={caption}>
                Budget (a constraint only — no costs are estimated yet)
              </span>
              <div className="flex gap-2">
                <Input
                  type="number"
                  min={1}
                  inputMode="numeric"
                  value={details.budget}
                  onChange={(e) => set({ budget: e.target.value })}
                  aria-label="Budget amount"
                />
                <Select
                  value={details.currency}
                  onChange={(e) => set({ currency: e.target.value })}
                  aria-label="Budget currency"
                  className="w-24"
                >
                  {["KZT", "USD", "EUR"].map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </Select>
              </div>
            </label>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
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
