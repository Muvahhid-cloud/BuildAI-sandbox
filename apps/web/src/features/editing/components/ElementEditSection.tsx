"use client";

import { useState } from "react";

import type { ModelIndex } from "@/engine/model/model-index";
import { parseBuildingModel } from "@/engine/model/parse";
import type { BuildingElement, Opening, Room, RoomType, Wall } from "@/engine/model/types";
import type { EditOperation, EditPreview, Issue } from "@/lib/api/schemas";
import { useSelectionStore } from "@/stores/selection-store";

import { useEditStore } from "../store";
import { type DraftCheck, useDraftCheck } from "../use-draft-check";

/** Room types a room can be changed to and from (docs/building-model.md §5.4). */
type EditableRoomType = Exclude<RoomType, "staircase" | "garage" | "balcony" | "terrace">;
export const ROOM_TYPE_LABELS: Record<EditableRoomType, string> = {
  bedroom: "Bedroom",
  study: "Study / office",
  living: "Living room",
  dining: "Dining room",
  kitchen: "Kitchen",
  open_kitchen_living: "Kitchen & living",
  bathroom: "Bathroom",
  en_suite: "En-suite",
  wc: "WC",
  laundry: "Laundry",
  utility: "Utility room",
  storage: "Storage",
  walk_in_closet: "Walk-in closet",
  plant_room: "Plant room",
  entrance: "Entrance",
  hall: "Hall",
  corridor: "Corridor",
};

export function isEditableRoomType(t: RoomType): t is EditableRoomType {
  return t in ROOM_TYPE_LABELS;
}

const round3 = (v: number) => Math.round(v * 1000) / 1000;

/**
 * Editing controls for the selected element, shown in the properties panel while a version is
 * open for editing: a door or window's size, an interior wall's removal, a room's name and type.
 * Every change is a typed operation checked live by the server and applied to the editing
 * session (undo, redo, discard and save in the plan's edit bar).
 */
export function ElementEditSection({
  element,
  index,
}: {
  element: BuildingElement;
  index: ModelIndex;
}) {
  const editing = useEditStore((s) => s.versionId !== null);
  if (!editing) return null;
  let body: React.ReactNode = null;
  if (element.type === "door" || element.type === "window") {
    const host = index.hostOf.get(element.id);
    if (host) body = <OpeningSizeForm key={element.id} opening={element} host={host} />;
  } else if (element.type === "wall" && element.properties.wall_kind !== "exterior") {
    body = <WallRemoval key={element.id} wall={element} index={index} />;
  } else if (element.type === "room") {
    body = <RoomEdit key={element.id} room={element} />;
  }
  if (!body) return null;
  return (
    <section
      aria-label="Edit"
      className="border-b border-neutral-100 bg-blue-50/40 px-4 py-2.5 dark:border-neutral-800 dark:bg-blue-950/20"
    >
      <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-blue-700 dark:text-blue-400">
        Edit
      </h3>
      {body}
      <p className="mt-1.5 text-[11px] text-neutral-500">
        Changes join the plan&apos;s editing session: undo, discard or save them as a new version in
        the 2D plan.
      </p>
    </section>
  );
}

// --- door / window size --------------------------------------------------------------------

function OpeningSizeForm({ opening, host }: { opening: Opening; host: Wall }) {
  const busy = useEditStore((s) => s.busy);
  const isWindow = opening.type === "window";
  const current = {
    width: opening.dimensions.width.toFixed(2),
    height: opening.dimensions.height.toFixed(2),
    sill: opening.position.z.toFixed(2),
  };
  // Typed values belong to the opening's current size; a change elsewhere resets them.
  const sizeKey = `${current.width}:${current.height}:${current.sill}`;
  const [typed, setTyped] = useState<{ key: string; values: typeof current } | null>(null);
  const values = typed?.key === sizeKey ? typed.values : current;
  const set = (field: keyof typeof current, value: string) =>
    setTyped({ key: sizeKey, values: { ...values, [field]: value } });

  const width = Number(values.width);
  const height = Number(values.height);
  const sill = Number(values.sill);
  const numbers = [width, height, ...(isWindow ? [sill] : [])];
  const wellFormed = numbers.every((v) => Number.isFinite(v)) && width > 0 && height > 0;
  const sillChanged = isWindow && round3(sill) !== round3(opening.position.z);
  const changed =
    round3(width) !== round3(opening.dimensions.width) ||
    round3(height) !== round3(opening.dimensions.height) ||
    sillChanged;
  const op: EditOperation | null =
    wellFormed && changed && (!isWindow || sill >= 0)
      ? {
          op: "resize_opening",
          opening_id: opening.id,
          width_m: round3(width),
          height_m: round3(height),
          ...(sillChanged ? { sill_m: round3(sill) } : {}),
        }
      : null;
  const check = useDraftCheck(op);

  const apply = () => {
    if (!op || !check.preview?.valid) return;
    void useEditStore
      .getState()
      .apply(op, check.preview)
      .then((ok) => {
        if (ok) setTyped(null);
      });
  };

  const field = (name: keyof typeof current, label: string, hint?: string) => (
    <label className="flex flex-col gap-0.5 text-[11px] text-neutral-600 dark:text-neutral-400">
      {label}
      <input
        type="number"
        aria-label={`${label} in meters`}
        min={name === "sill" ? 0 : 0.1}
        max={10}
        step={0.05}
        value={values[name]}
        onChange={(e) => set(name, e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") apply();
        }}
        className="w-full rounded border border-neutral-300 bg-white px-1.5 py-0.5 text-xs tabular-nums dark:border-neutral-700 dark:bg-neutral-900"
      />
      {hint && <span className="text-[10px] text-neutral-400">{hint}</span>}
    </label>
  );

  return (
    <div>
      <p className="mb-1 text-xs text-neutral-700 dark:text-neutral-300">
        Size in {host.name} ({host.dimensions.length.toFixed(2)} m long,{" "}
        {host.dimensions.height.toFixed(2)} m high)
      </p>
      <div className={`grid gap-1.5 ${isWindow ? "grid-cols-3" : "grid-cols-2"}`}>
        {field("width", "Width")}
        {field("height", "Height")}
        {isWindow && field("sill", "Sill", "above floor")}
      </div>
      <Verdict
        check={check}
        idle={changed ? null : "Type a new size, or drag the opening's end grips on the plan."}
        valid={
          op && check.preview?.valid
            ? `${round3(width).toFixed(2)} × ${round3(height).toFixed(2)} m fits`
            : null
        }
      />
      <div className="mt-1.5 flex gap-1">
        <EditButton
          onClick={apply}
          disabled={busy || !op || !check.preview?.valid}
          primary
          title="Apply the new size (Enter)"
        >
          Apply size
        </EditButton>
        {changed && (
          <EditButton onClick={() => setTyped(null)} disabled={busy}>
            Reset
          </EditButton>
        )}
      </div>
    </div>
  );
}

// --- interior wall removal -----------------------------------------------------------------

function WallRemoval({ wall, index }: { wall: Wall; index: ModelIndex }) {
  const busy = useEditStore((s) => s.busy);
  const [merge, setMerge] = useState<boolean | null>(null);
  const op: EditOperation | null =
    merge === null ? null : { op: "remove_wall", wall_id: wall.id, merge_rooms: merge };
  const check = useDraftCheck(op);
  const rooms = wall.relationships
    .filter((r) => r.kind === "bounds")
    .map((r) => index.elementsById.get(r.target_id))
    .filter((e): e is Room => e?.type === "room");
  const doors = index.model.elements.filter(
    (e) => (e.type === "door" || e.type === "window") && index.hostOf.get(e.id)?.id === wall.id,
  );

  const confirm = () => {
    if (!op || !check.preview?.valid) return;
    const survivor = merge ? mergedRoom(check.preview, rooms) : null;
    void useEditStore
      .getState()
      .apply(op, check.preview)
      .then((ok) => {
        if (ok) useSelectionStore.getState().select(survivor?.id ?? null);
      });
  };

  if (merge === null) {
    return (
      <div>
        <p className="mb-1.5 text-xs text-neutral-700 dark:text-neutral-300">
          Remove {wall.name}
          {rooms.length > 0 && <> between {rooms.map((r) => r.name).join(" and ")}</>}:
        </p>
        <div className="flex flex-wrap gap-1">
          <EditButton
            onClick={() => setMerge(false)}
            disabled={busy}
            danger
            title="Remove the wall; the rooms open into each other"
          >
            Remove wall…
          </EditButton>
          <EditButton
            onClick={() => setMerge(true)}
            disabled={busy || rooms.length !== 2}
            danger
            title="Remove the wall and make the two rooms one room"
          >
            Remove & merge rooms…
          </EditButton>
        </div>
      </div>
    );
  }

  const survivor = merge && check.preview?.valid ? mergedRoom(check.preview, rooms) : null;
  const what = merge
    ? survivor
      ? `${rooms.map((r) => r.name).join(" and ")} become one room, ${survivor.name}, ` +
        `${survivor.dimensions.area.toFixed(1)} m².`
      : null
    : `${rooms.map((r) => r.name).join(" and ")} open into each other.`;
  return (
    <div role="group" aria-label={`Remove ${wall.name}`}>
      <p className="mb-1 text-xs font-medium text-neutral-800 dark:text-neutral-200">
        {merge ? `Remove ${wall.name} and merge the rooms?` : `Remove ${wall.name}?`}
      </p>
      {check.preview?.valid && (
        <p className="mb-1 text-xs text-neutral-700 dark:text-neutral-300">
          {what}
          {doors.length > 0 && (
            <> {doors.map((d) => d.name).join(", ")} in the wall will be removed with it.</>
          )}
        </p>
      )}
      <Verdict check={check} idle={null} valid={null} />
      <div className="mt-1.5 flex gap-1">
        <EditButton
          onClick={confirm}
          disabled={busy || !check.preview?.valid}
          danger
          title="Remove the wall (undo with Ctrl+Z in the plan)"
        >
          Confirm removal
        </EditButton>
        <EditButton onClick={() => setMerge(null)} disabled={busy}>
          Cancel
        </EditButton>
      </div>
    </div>
  );
}

/** The room of `rooms` that is still in the previewed model (the merged room). */
function mergedRoom(preview: EditPreview, rooms: Room[]): Room | null {
  if (!preview.model) return null;
  try {
    const after = parseBuildingModel(preview.model);
    for (const r of rooms) {
      const found = after.elementsById.get(r.id);
      if (found?.type === "room") return found;
    }
  } catch {
    return null;
  }
  return null;
}

// --- room name and type --------------------------------------------------------------------

function RoomEdit({ room }: { room: Room }) {
  const busy = useEditStore((s) => s.busy);
  const [name, setName] = useState<{ base: string; value: string } | null>(null);
  const nameValue = name?.base === room.name ? name.value : room.name;
  const [type, setType] = useState<{ base: RoomType; value: RoomType } | null>(null);
  const typeValue =
    type?.base === room.properties.room_type ? type.value : room.properties.room_type;
  const current = room.properties.room_type;
  const editableType = isEditableRoomType(current);

  const trimmed = nameValue.trim().replace(/\s+/g, " ");
  const renameOp: EditOperation | null =
    trimmed && trimmed !== room.name && trimmed.length <= 120
      ? { op: "rename_room", room_id: room.id, name: trimmed }
      : null;
  const typeOp: EditOperation | null =
    typeValue !== current ? { op: "set_room_type", room_id: room.id, room_type: typeValue } : null;
  // One check at a time: the field being edited.
  const pending = typeOp ?? renameOp;
  const check = useDraftCheck(pending);

  const apply = () => {
    if (!pending || !check.preview?.valid) return;
    void useEditStore
      .getState()
      .apply(pending, check.preview)
      .then((ok) => {
        if (!ok) return;
        if (pending === typeOp) setType(null);
        else setName(null);
      });
  };

  return (
    <div className="space-y-2">
      <label className="flex flex-col gap-0.5 text-[11px] text-neutral-600 dark:text-neutral-400">
        Name
        <input
          type="text"
          aria-label="Room name"
          maxLength={120}
          value={nameValue}
          disabled={typeOp !== null}
          onChange={(e) => setName({ base: room.name, value: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === "Enter") apply();
            if (e.key === "Escape") setName(null);
          }}
          className="rounded border border-neutral-300 bg-white px-1.5 py-0.5 text-xs dark:border-neutral-700 dark:bg-neutral-900"
        />
      </label>
      <label className="flex flex-col gap-0.5 text-[11px] text-neutral-600 dark:text-neutral-400">
        Room type
        {editableType ? (
          <select
            aria-label="Room type"
            value={typeValue}
            disabled={renameOp !== null}
            onChange={(e) => setType({ base: current, value: e.target.value as RoomType })}
            className="rounded border border-neutral-300 bg-white px-1 py-0.5 text-xs dark:border-neutral-700 dark:bg-neutral-900"
          >
            {Object.entries(ROOM_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        ) : (
          <span className="text-xs text-neutral-500">
            {current.replace(/_/g, " ")} — this type is tied to the building (stair, garage door or
            outdoors) and cannot be changed.
          </span>
        )}
      </label>
      <Verdict
        check={check}
        idle={null}
        valid={
          pending?.op === "set_room_type"
            ? `${room.name} can become a ${ROOM_TYPE_LABELS[typeValue as EditableRoomType] ?? typeValue}`
            : pending
              ? `"${trimmed}" is available`
              : null
        }
      />
      {pending && (
        <div className="flex gap-1">
          <EditButton
            onClick={apply}
            disabled={busy || !check.preview?.valid}
            primary
            title="Apply (Enter)"
          >
            {pending.op === "set_room_type" ? "Change type" : "Rename"}
          </EditButton>
          <EditButton
            onClick={() => {
              setName(null);
              setType(null);
            }}
            disabled={busy}
          >
            Cancel
          </EditButton>
        </div>
      )}
    </div>
  );
}

// --- shared --------------------------------------------------------------------------------

/** The server's verdict on a prepared change: checking, valid (with notes), or why not. */
function Verdict({
  check,
  idle,
  valid,
}: {
  check: DraftCheck;
  idle: string | null;
  valid: string | null;
}) {
  const { preview, checking, error } = check;
  if (error) return <p className="mt-1 text-[11px] text-red-700">{error}</p>;
  if (checking) {
    return (
      <p className="mt-1 text-[11px] text-neutral-500" aria-live="polite">
        Checking…
      </p>
    );
  }
  if (!preview) return idle ? <p className="mt-1 text-[11px] text-neutral-500">{idle}</p> : null;
  if (!preview.valid) {
    const rest: Issue[] = preview.rejection?.issues.slice(1) ?? [];
    return (
      <div role="alert" className="mt-1 rounded bg-red-50 p-1.5 text-[11px] text-red-800">
        <p className="font-medium">{preview.rejection?.message ?? "Not possible."}</p>
        {rest.length > 0 && (
          <ul className="mt-0.5 list-disc pl-4">
            {rest.slice(0, 3).map((i, k) => (
              <li key={k}>{i.message}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  return (
    <div role="status" className="mt-1 rounded bg-green-50 p-1.5 text-[11px] text-green-800">
      <p>{valid ? `${valid} — valid.` : "Valid."}</p>
      {preview.warnings.length > 0 && (
        <ul className="mt-0.5 list-disc pl-4 text-amber-800">
          {preview.warnings.slice(0, 3).map((i, k) => (
            <li key={k}>{i.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EditButton({
  onClick,
  disabled,
  title,
  primary,
  danger,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  primary?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={
        "rounded px-2 py-1 text-xs font-medium disabled:opacity-40 " +
        (primary
          ? "bg-blue-600 text-white hover:bg-blue-700"
          : danger
            ? "bg-red-50 text-red-700 ring-1 ring-red-200 hover:bg-red-100"
            : "bg-neutral-100 text-neutral-800 hover:bg-neutral-200")
      }
    >
      {children}
    </button>
  );
}
