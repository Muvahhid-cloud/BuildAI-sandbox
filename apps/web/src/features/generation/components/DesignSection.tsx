"use client";

import type { BuildingSpecification } from "@buildai/schema";

import type { Issue } from "@/lib/api/schemas";

import type { DesignOptions, DesignSystemOption } from "../api";

type Style = NonNullable<BuildingSpecification["style"]>;
type WindowIntent = NonNullable<NonNullable<BuildingSpecification["design"]>["windows"]>;
type Facade = WindowIntent["preferred_facades"][number];

const FACADES: { id: Facade; text: string }[] = [
  { id: "front", text: "Front (street)" },
  { id: "rear", text: "Rear (garden)" },
  { id: "left", text: "Left" },
  { id: "right", text: "Right" },
];
const HEX = /^#[0-9a-f]{6}$/;

const input =
  "w-full rounded-md border border-neutral-300 bg-white px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900";
const label = "text-[11px] font-medium uppercase tracking-wide text-neutral-500";

/** Where a design choice comes from — shown next to every value (K3 precedence). */
export type ChoiceSource = "explicit" | "design_system" | "inherited";
const SOURCE_TEXT: Record<ChoiceSource, string> = {
  explicit: "Your requirement",
  design_system: "Design-system default",
  inherited: "Inherited default",
};

export function SourceBadge({ source }: { source: ChoiceSource }) {
  const tone =
    source === "explicit"
      ? "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
      : source === "design_system"
        ? "bg-violet-50 text-violet-700 dark:bg-violet-950 dark:text-violet-300"
        : "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${tone}`}>
      {SOURCE_TEXT[source]}
    </span>
  );
}

/** The facade color a spec will get and where it comes from (mirrors building/design.py). */
export function effectiveFacadeColor(
  spec: BuildingSpecification,
  system: DesignSystemOption | undefined,
  options: DesignOptions | undefined,
): { name: string | null; hex: string | null; source: ChoiceSource } {
  const hexOf = (name: string) => options?.palette.find((c) => c.name === name)?.hex ?? null;
  const explicit = spec.design?.facade_color;
  if (explicit) {
    return HEX.test(explicit)
      ? { name: null, hex: explicit, source: "explicit" }
      : { name: explicit, hex: hexOf(explicit), source: "explicit" };
  }
  const fallback = system?.facade.default_color;
  if (fallback) return { name: fallback, hex: hexOf(fallback), source: "design_system" };
  return { name: null, hex: null, source: "inherited" };
}

export interface DesignSectionProps {
  spec: BuildingSpecification;
  onChange: (spec: BuildingSpecification) => void;
  options: DesignOptions | undefined;
  issues: Issue[];
}

/**
 * Design system + explicit design intent (Phase 3.5 K3). Explicit values always win; a design
 * system only fills what is left open, and values outside its allow-lists are reported as
 * conflicts by the API (never changed silently).
 */
export function DesignSection({ spec, onChange, options, issues }: DesignSectionProps) {
  const style: Style = spec.style ?? {};
  const design = spec.design ?? {};
  const windows = design.windows ?? null;
  const system = options?.available.find((d) => d.id === style.design_system);
  const color = effectiveFacadeColor(spec, system, options);
  const palette =
    system && !system.facade.custom_colors
      ? (options?.palette ?? []).filter((c) => system.facade.colors.includes(c.name))
      : (options?.palette ?? []);

  const setStyle = (patch: Partial<Style>) => onChange({ ...spec, style: { ...style, ...patch } });
  const setDesign = (patch: Partial<typeof design>) =>
    onChange({ ...spec, design: { ...design, ...patch } });
  const setWindows = (patch: Partial<WindowIntent> | null) =>
    setDesign({
      windows:
        patch === null
          ? null
          : ({
              emphasis: "panoramic",
              preferred_facades: [],
              excluded_facades: [],
              ...windows,
              ...patch,
            } as WindowIntent),
    });
  const toggle = (list: Facade[], side: Facade, on: boolean) =>
    on ? [...list.filter((s) => s !== side), side] : list.filter((s) => s !== side);
  const designIssues = issues.filter(
    (x) =>
      x.path.startsWith("/design") ||
      x.path === "/style/design_system" ||
      x.code.startsWith("DESIGN_"),
  );

  return (
    <section className="flex flex-col gap-2" aria-labelledby="spec-design">
      <h3
        id="spec-design"
        className="text-xs font-semibold uppercase tracking-wider text-neutral-500"
      >
        Design
      </h3>

      <div className="flex flex-col gap-1">
        <label htmlFor="spec-design-system" className={label}>
          Design system
        </label>
        <select
          id="spec-design-system"
          className={input}
          value={style.design_system ?? ""}
          onChange={(e) => setStyle({ design_system: e.target.value || null })}
        >
          <option value="">None (generic components)</option>
          {options?.available.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
          {options?.unavailable.map((d) => (
            <option key={d.id} value={d.id} disabled>
              {d.name} — not available ({d.reason.split(";")[0]})
            </option>
          ))}
        </select>
        {system && (
          <button
            type="button"
            className="self-start text-xs font-medium text-violet-700 hover:underline dark:text-violet-300"
            onClick={() =>
              setStyle({
                roof: {
                  ...style.roof,
                  type: system.roof.default as NonNullable<Style["roof"]>["type"],
                  pitch_deg: system.roof.default_pitch_deg,
                },
                window_style: system.windows.default as Style["window_style"],
                facade_material: system.facade.default_material as Style["facade_material"],
              })
            }
          >
            Use {system.name} defaults for roof, windows and facade
          </button>
        )}
        {options && options.available.length === 0 && (
          <p className="text-[11px] text-neutral-400">
            Design systems are awaiting review; until one is approved the generic components are
            used. Colors and window placement below work without a design system.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <span className={label} id="spec-facade-color-label">
            Facade color
          </span>
          <SourceBadge source={color.source} />
        </div>
        <div
          role="radiogroup"
          aria-labelledby="spec-facade-color-label"
          className="flex flex-wrap gap-1"
        >
          <button
            type="button"
            role="radio"
            aria-checked={!design.facade_color}
            onClick={() => setDesign({ facade_color: null })}
            className="rounded border border-neutral-300 px-1.5 text-[11px] dark:border-neutral-700"
          >
            {system?.facade.default_color ? `System (${system.facade.default_color})` : "Material"}
          </button>
          {palette.map((c) => (
            <button
              key={c.name}
              type="button"
              role="radio"
              aria-checked={design.facade_color === c.name}
              aria-label={c.name.replace(/_/g, " ")}
              title={c.name.replace(/_/g, " ")}
              onClick={() => setDesign({ facade_color: c.name })}
              className={
                "h-6 w-6 rounded border " +
                (design.facade_color === c.name
                  ? "border-blue-600 ring-2 ring-blue-600"
                  : "border-neutral-300 dark:border-neutral-600")
              }
              style={{ backgroundColor: c.hex }}
            />
          ))}
        </div>
        <p className="text-[11px] text-neutral-500">
          {color.hex ? (
            <>
              Exterior walls drawn in{" "}
              <span
                className="inline-block h-2.5 w-2.5 rounded-sm align-middle"
                style={{ backgroundColor: color.hex }}
              />{" "}
              {color.name?.replace(/_/g, " ") ?? color.hex} — display color only; the facade
              material stays {style.facade_material ?? "render"}.
            </>
          ) : (
            <>Walls show the color of the facade material.</>
          )}
        </p>
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <label htmlFor="spec-window-emphasis" className={label}>
            Emphasised windows
          </label>
          <SourceBadge source={windows ? "explicit" : "inherited"} />
        </div>
        <select
          id="spec-window-emphasis"
          className={input}
          value={windows?.emphasis ?? ""}
          onChange={(e) =>
            e.target.value === ""
              ? setWindows(null)
              : setWindows({
                  emphasis: e.target.value as WindowIntent["emphasis"],
                  preferred_facades: windows?.preferred_facades.length
                    ? windows.preferred_facades
                    : ["rear"],
                })
          }
        >
          <option value="">Same size on every facade (building window style)</option>
          <option value="large">Large windows on chosen facades</option>
          <option value="panoramic">Panoramic windows on chosen facades</option>
        </select>
        {windows && (
          <div className="grid grid-cols-2 gap-x-3 text-xs">
            <fieldset className="flex flex-col gap-0.5">
              <legend className={label}>Place on</legend>
              {FACADES.map((f) => (
                <label key={f.id} className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    className="h-3 w-3 accent-blue-600"
                    aria-label={`Prefer ${f.text}`}
                    checked={windows.preferred_facades.includes(f.id)}
                    onChange={(e) =>
                      setWindows({
                        preferred_facades: toggle(
                          windows.preferred_facades,
                          f.id,
                          e.target.checked,
                        ),
                        excluded_facades: (windows.excluded_facades ?? []).filter(
                          (s) => s !== f.id,
                        ),
                      })
                    }
                  />
                  {f.text}
                </label>
              ))}
            </fieldset>
            <fieldset className="flex flex-col gap-0.5">
              <legend className={label}>Never on</legend>
              {FACADES.map((f) => (
                <label key={f.id} className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    className="h-3 w-3 accent-blue-600"
                    aria-label={`Exclude ${f.text}`}
                    checked={(windows.excluded_facades ?? []).includes(f.id)}
                    onChange={(e) =>
                      setWindows({
                        excluded_facades: toggle(
                          windows.excluded_facades ?? [],
                          f.id,
                          e.target.checked,
                        ),
                        preferred_facades: windows.preferred_facades.filter((s) => s !== f.id),
                      })
                    }
                  />
                  {f.text}
                </label>
              ))}
            </fieldset>
          </div>
        )}
      </div>

      {designIssues.length > 0 && (
        <ul aria-label="Design conflicts" className="flex flex-col gap-1">
          {designIssues.map((x) => (
            <li
              key={x.code + x.path + x.message}
              className={
                "rounded px-2 py-1 text-xs " +
                (x.severity === "error"
                  ? "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300"
                  : "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300")
              }
            >
              {x.message}
              {x.suggestion ? <span className="block opacity-80">{x.suggestion}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
