"use client";

import type { InterimFact } from "@buildai/schema";

/** A fact as a short label: "2 floors", "about 280 m²", "4 bedrooms", "Garage · 2 cars". */
export function factLabel(fact: InterimFact): string | null {
  const { key, value } = fact;
  const words = (text: string) => text.replace(/_/g, " ");
  const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
  const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
  if (key.startsWith("room:")) {
    if (typeof value !== "number") return null;
    const type = key.slice("room:".length);
    const name = ROOM_NAMES[type] ?? [words(type), `${words(type)}s`];
    return plural(value, name[0], name[1]);
  }
  switch (key) {
    case "storeys":
      return typeof value === "number" ? plural(value, "floor") : null;
    case "floor_area_m2":
      return typeof value === "number" ? `about ${Math.round(value)} m²` : null;
    case "style":
      return typeof value === "string" ? `${capital(words(value))} style` : null;
    case "roof":
      return typeof value === "string" ? `${capital(words(value))} roof` : null;
    case "footprint_shape":
      return typeof value === "string" ? `${capital(words(value))} plan` : null;
    case "garage_cars":
      return typeof value === "number" ? `Garage · ${plural(value, "car")}` : null;
    case "balconies":
      return typeof value === "number" ? plural(value, "balcony", "balconies") : null;
    case "terrace":
      return value === true ? "Terrace" : null;
    default:
      return null;
  }
}

const ROOM_NAMES: Record<string, [string, string]> = {
  wc: ["WC", "WCs"],
  living: ["living room", "living rooms"],
  dining: ["dining room", "dining rooms"],
  study: ["study", "studies"],
  laundry: ["laundry", "laundries"],
  utility: ["utility room", "utility rooms"],
  storage: ["storage room", "storage rooms"],
  open_kitchen_living: ["open kitchen-living room", "open kitchen-living rooms"],
};

/**
 * "Understood so far": what the AI's answer states while it is still being written, one chip
 * per fact, in the order they appeared. Interim — the validated specification decides.
 */
export function InterimFacts({ facts }: { facts: readonly InterimFact[] }) {
  const chips = facts.flatMap((fact) => {
    const label = factLabel(fact);
    return label ? [{ key: fact.key, label }] : [];
  });
  return (
    <section aria-label="Understood so far" className="flex min-h-[3.25rem] flex-col gap-2">
      <h3 className="text-2xs font-semibold uppercase tracking-[0.14em] text-fg-subtle">
        Understood so far
      </h3>
      {chips.length === 0 ? (
        <p className="text-xs text-fg-subtle">Reading your description…</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {chips.map((chip) => (
            <li
              key={chip.key}
              className="animate-rise-in rounded-full border border-line bg-surface px-2.5 py-1 text-xs font-medium text-fg-muted shadow-xs"
            >
              {chip.label}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
