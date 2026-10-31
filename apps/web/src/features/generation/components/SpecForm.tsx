"use client";

import {
  type BuildingSpecification,
  buildingSpecificationSchema,
  type RoomRequirement,
} from "@buildai/schema";
import { useState } from "react";
import type { z } from "zod";

import type { Issue } from "@/lib/api/schemas";

import type { DesignOptions } from "../api";
import { nextRoomKey, ROOM_TYPE_LABELS, SPEC_PRESETS } from "../spec-presets";
import { DesignSection } from "./DesignSection";

const STYLES = [
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
const ROOFS = ["flat", "gable", "hip"];
const WINDOWS = ["standard", "large", "panoramic"];
const FACADES = ["render", "brick", "concrete", "timber"];
const FINISHES = ["economy", "standard", "premium"];

const input =
  "w-full rounded-md border border-neutral-300 bg-white px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900";
const label = "text-[11px] font-medium uppercase tracking-wide text-neutral-500";

const title = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");

/** Numbers from inputs: "" -> undefined, otherwise a finite number. */
function num(value: string): number | undefined {
  if (value.trim() === "") return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

export interface SpecFormProps {
  spec: BuildingSpecification;
  onChange: (spec: BuildingSpecification) => void;
  seed: number;
  onSeedChange: (seed: number) => void;
  issues: Issue[];
  disabled?: boolean;
  /** Design systems and palette from GET /design-options (K3); undefined while loading. */
  designOptions?: DesignOptions;
}

/**
 * Manual building specification entry (Phase 2). Edits a typed BuildingSpecification (the
 * generated contract); fields the form doesn't show (adjacency, open plan, assumptions) are
 * kept from presets unchanged.
 */
export function SpecForm({
  spec,
  onChange,
  seed,
  onSeedChange,
  issues,
  disabled,
  designOptions,
}: SpecFormProps) {
  const [presetId, setPresetId] = useState("");
  const set = (patch: Partial<BuildingSpecification>) => onChange({ ...spec, ...patch });
  const targets = spec.targets;
  const style = spec.style ?? {};
  const features = spec.features ?? {};
  const balcony = features.balconies?.[0];

  const setRoom = (i: number, patch: Partial<RoomRequirement>) =>
    set({ rooms: spec.rooms.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const removeRoom = (i: number) => {
    const removed = spec.rooms[i].key;
    set({
      rooms: spec.rooms
        .filter((_, j) => j !== i)
        .map((r) => ({
          ...r,
          adjacent_to: r.adjacent_to?.filter((k) => k !== removed),
          open_to: r.open_to?.filter((k) => k !== removed),
        })),
    });
  };
  const issueAt = (path: string) =>
    issues.filter((x) => x.path === path || x.path.startsWith(path + "/"));

  return (
    <fieldset disabled={disabled} className="flex flex-col gap-5 text-sm">
      <div className="flex flex-col gap-1">
        <label htmlFor="spec-preset" className={label}>
          Start from a reference specification
        </label>
        <select
          id="spec-preset"
          className={input}
          value={presetId}
          onChange={(e) => {
            setPresetId(e.target.value);
            const preset = SPEC_PRESETS.find((p) => p.id === e.target.value);
            if (preset) onChange(structuredClone(preset.spec));
          }}
        >
          <option value="">Choose a preset…</option>
          {SPEC_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      </div>

      <section className="flex flex-col gap-3" aria-labelledby="spec-basics">
        <h3
          id="spec-basics"
          className="text-xs font-semibold uppercase tracking-wider text-neutral-500"
        >
          Building
        </h3>
        <div className="flex flex-col gap-1">
          <label htmlFor="spec-name" className={label}>
            Name
          </label>
          <input
            id="spec-name"
            className={input}
            value={spec.name}
            maxLength={200}
            onChange={(e) => set({ name: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="flex flex-col gap-1">
            <span className={label} id="spec-storeys-label">
              Floors
            </span>
            <div className="flex gap-1" role="group" aria-labelledby="spec-storeys-label">
              {[1, 2, 3].map((n) => (
                <button
                  key={n}
                  type="button"
                  aria-pressed={targets.storeys === n}
                  onClick={() =>
                    set({
                      targets: { ...targets, storeys: n },
                      rooms: spec.rooms.map((r) =>
                        r.level != null && r.level >= n ? { ...r, level: null } : r,
                      ),
                    })
                  }
                  className={
                    "flex-1 rounded-md py-1 text-sm font-medium " +
                    (targets.storeys === n
                      ? "bg-blue-600 text-white"
                      : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-200")
                  }
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="spec-gfa" className={label}>
              Floor area m²
            </label>
            <input
              id="spec-gfa"
              type="number"
              min={20}
              max={2000}
              step={5}
              placeholder="auto"
              className={input}
              value={targets.gross_floor_area_m2 ?? ""}
              onChange={(e) =>
                set({ targets: { ...targets, gross_floor_area_m2: num(e.target.value) ?? null } })
              }
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="spec-f2f" className={label}>
              Floor height m
            </label>
            <input
              id="spec-f2f"
              type="number"
              min={2.4}
              max={4}
              step={0.05}
              className={input}
              value={targets.floor_to_floor_height_m ?? 3}
              onChange={(e) =>
                set({ targets: { ...targets, floor_to_floor_height_m: num(e.target.value) ?? 3 } })
              }
            />
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-2" aria-labelledby="spec-style">
        <h3
          id="spec-style"
          className="text-xs font-semibold uppercase tracking-wider text-neutral-500"
        >
          Style
        </h3>
        <div className="grid grid-cols-2 gap-2">
          <Select
            id="spec-arch"
            text="Architecture"
            value={style.architectural_style ?? "modern"}
            options={STYLES}
            onChange={(v) =>
              set({
                style: { ...style, architectural_style: v as typeof style.architectural_style },
              })
            }
          />
          <Select
            id="spec-roof"
            text="Roof"
            value={style.roof?.type ?? "hip"}
            options={ROOFS}
            onChange={(v) =>
              set({
                style: {
                  ...style,
                  roof: { ...style.roof, type: v as "flat" | "gable" | "hip" },
                },
              })
            }
          />
          <Select
            id="spec-windows"
            text="Windows"
            value={style.window_style ?? "standard"}
            options={WINDOWS}
            onChange={(v) =>
              set({ style: { ...style, window_style: v as typeof style.window_style } })
            }
          />
          <Select
            id="spec-facade"
            text="Facade"
            value={style.facade_material ?? "render"}
            options={FACADES}
            onChange={(v) =>
              set({ style: { ...style, facade_material: v as typeof style.facade_material } })
            }
          />
          <Select
            id="spec-finish"
            text="Interior finish"
            value={style.interior_finish_level ?? "standard"}
            options={FINISHES}
            onChange={(v) =>
              set({
                style: { ...style, interior_finish_level: v as typeof style.interior_finish_level },
              })
            }
          />
        </div>
      </section>

      <DesignSection spec={spec} onChange={onChange} options={designOptions} issues={issues} />

      <section className="flex flex-col gap-2" aria-labelledby="spec-rooms">
        <div className="flex items-center justify-between">
          <h3
            id="spec-rooms"
            className="text-xs font-semibold uppercase tracking-wider text-neutral-500"
          >
            Rooms
          </h3>
          <span className="text-[11px] text-neutral-400">area per room · blank = automatic</span>
        </div>
        <ul className="flex flex-col gap-1.5">
          {spec.rooms.map((room, i) => (
            <li
              key={room.key}
              className="rounded-md border border-neutral-200 p-2 dark:border-neutral-800"
            >
              <div className="grid grid-cols-[1fr_3.5rem_4.5rem_4.5rem_1.5rem] items-center gap-1.5">
                <select
                  aria-label={`Room ${i + 1} type`}
                  className={input}
                  value={room.type}
                  onChange={(e) =>
                    setRoom(i, {
                      type: e.target.value as RoomRequirement["type"],
                      features: e.target.value === "bedroom" ? room.features : [],
                    })
                  }
                >
                  {Object.entries(ROOM_TYPE_LABELS).map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </select>
                <input
                  aria-label={`Room ${i + 1} count`}
                  type="number"
                  min={1}
                  max={12}
                  className={input}
                  value={room.count ?? 1}
                  onChange={(e) => setRoom(i, { count: Math.max(1, num(e.target.value) ?? 1) })}
                />
                <input
                  aria-label={`Room ${i + 1} area (m²)`}
                  type="number"
                  min={1}
                  max={200}
                  placeholder="auto"
                  className={input}
                  value={room.target_area_m2 ?? ""}
                  onChange={(e) => setRoom(i, { target_area_m2: num(e.target.value) ?? null })}
                />
                <select
                  aria-label={`Room ${i + 1} floor`}
                  className={input}
                  value={room.level ?? ""}
                  onChange={(e) =>
                    setRoom(i, { level: e.target.value === "" ? null : Number(e.target.value) })
                  }
                >
                  <option value="">Any</option>
                  {Array.from({ length: targets.storeys }, (_, lv) => (
                    <option key={lv} value={lv}>
                      Floor {lv + 1}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  aria-label={`Remove room ${i + 1}`}
                  onClick={() => removeRoom(i)}
                  disabled={spec.rooms.length <= 1}
                  className="text-neutral-400 hover:text-red-600 disabled:opacity-30"
                >
                  ×
                </button>
              </div>
              {
                <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-neutral-500">
                  {room.name && (
                    <span className="font-medium text-neutral-700 dark:text-neutral-300">
                      {room.name}
                    </span>
                  )}
                  <label className="flex items-center gap-1">
                    Faces
                    <select
                      aria-label={`Room ${i + 1} faces`}
                      className="rounded border border-neutral-300 bg-white px-1 py-0 text-xs dark:border-neutral-700 dark:bg-neutral-900"
                      value={room.faces ?? ""}
                      onChange={(e) =>
                        setRoom(i, {
                          faces: (e.target.value || null) as RoomRequirement["faces"],
                        })
                      }
                    >
                      <option value="">any side</option>
                      <option value="rear">garden (rear)</option>
                      <option value="front">street (front)</option>
                    </select>
                  </label>
                  {room.type === "bedroom" &&
                    (["en_suite", "walk_in_closet"] as const).map((f) => (
                      <label key={f} className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          className="h-3 w-3 accent-blue-600"
                          checked={room.features?.includes(f) ?? false}
                          onChange={(e) =>
                            setRoom(i, {
                              features: e.target.checked
                                ? [...(room.features ?? []), f]
                                : (room.features ?? []).filter((x) => x !== f),
                            })
                          }
                        />
                        {f === "en_suite" ? "En-suite" : "Walk-in closet"}
                      </label>
                    ))}
                  {(room.open_to?.length ?? 0) > 0 && (
                    <span>open to {room.open_to?.join(", ")}</span>
                  )}
                </div>
              }
              {issueAt(`/rooms/${i}`).map((x) => (
                <p key={x.code + x.path} className="mt-1 text-xs text-red-600">
                  {x.message}
                </p>
              ))}
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() =>
            set({
              rooms: [
                ...spec.rooms,
                { key: nextRoomKey(spec, "bedroom"), type: "bedroom", count: 1 },
              ],
            })
          }
          disabled={spec.rooms.length >= 40}
          className="self-start rounded-md px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 dark:text-blue-400 dark:hover:bg-blue-950"
        >
          + Add room
        </button>
      </section>

      <section className="flex flex-col gap-2" aria-labelledby="spec-features">
        <h3
          id="spec-features"
          className="text-xs font-semibold uppercase tracking-wider text-neutral-500"
        >
          Garage & outdoor
        </h3>
        <div className="grid grid-cols-2 gap-2">
          <Select
            id="spec-garage"
            text="Garage"
            value={String(features.garage?.cars ?? 0)}
            options={["0", "1", "2", "3"]}
            format={(v) => (v === "0" ? "None" : `${v} car${v === "1" ? "" : "s"}`)}
            onChange={(v) =>
              set({ features: { ...features, garage: v === "0" ? null : { cars: Number(v) } } })
            }
          />
          <div className="flex flex-col justify-end gap-1">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-blue-600"
                checked={features.terrace != null}
                onChange={(e) =>
                  set({
                    features: { ...features, terrace: e.target.checked ? { depth_m: 3 } : null },
                  })
                }
              />
              Garden terrace
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-blue-600"
                disabled={targets.storeys < 2}
                checked={balcony != null}
                onChange={(e) =>
                  set({
                    features: {
                      ...features,
                      balconies: e.target.checked ? [{ level: targets.storeys - 1 }] : [],
                    },
                  })
                }
              />
              Balcony{targets.storeys < 2 ? " (needs 2 floors)" : ""}
            </label>
          </div>
        </div>
      </section>

      <details className="rounded-md border border-neutral-200 p-2 dark:border-neutral-800">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-neutral-500">
          Advanced
        </summary>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <div className="flex flex-col gap-1">
            <label htmlFor="spec-seed" className={label}>
              Layout seed
            </label>
            <input
              id="spec-seed"
              type="number"
              min={0}
              step={1}
              className={input}
              value={seed}
              onChange={(e) => onSeedChange(Math.max(0, Math.floor(num(e.target.value) ?? 0)))}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="spec-plot-w" className={label}>
              Plot width m
            </label>
            <input
              id="spec-plot-w"
              type="number"
              min={1}
              placeholder="—"
              className={input}
              value={spec.site?.plot_width_m ?? ""}
              onChange={(e) =>
                set({ site: { ...spec.site, plot_width_m: num(e.target.value) ?? null } })
              }
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="spec-plot-d" className={label}>
              Plot depth m
            </label>
            <input
              id="spec-plot-d"
              type="number"
              min={1}
              placeholder="—"
              className={input}
              value={spec.site?.plot_depth_m ?? ""}
              onChange={(e) =>
                set({ site: { ...spec.site, plot_depth_m: num(e.target.value) ?? null } })
              }
            />
          </div>
        </div>
        <p className="mt-2 text-[11px] text-neutral-400">
          The same specification and seed always produce the same house; change the seed to explore
          alternatives.
        </p>
      </details>
    </fieldset>
  );
}

function Select({
  id,
  text,
  value,
  options,
  onChange,
  format = title,
}: {
  id: string;
  text: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  format?: (value: string) => string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className={label}>
        {text}
      </label>
      <select id={id} className={input} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o} value={o}>
            {format(o)}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Client-side tier-1 check with the generated validator (the API repeats it, plus rules). */
export function checkSpecShape(spec: BuildingSpecification): Issue[] {
  const parsed = buildingSpecificationSchema.safeParse(spec);
  if (parsed.success) return [];
  return parsed.error.issues.map((issue: z.core.$ZodIssue) => ({
    severity: "error" as const,
    code: "SPEC_SCHEMA",
    path: "/" + issue.path.map(String).join("/"),
    message: issue.message,
  }));
}
