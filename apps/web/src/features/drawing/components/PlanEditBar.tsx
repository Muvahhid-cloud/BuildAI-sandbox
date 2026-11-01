"use client";

import { useEffect, useState } from "react";

import {
  type DoorKind,
  isOpening,
  newOpening,
  OPENING_SNAP_M,
  slideDirections,
  slideTowards,
  type WindowKind,
} from "@/engine/drawing/opening-edit";
import { roomSides, sideRefusal } from "@/engine/drawing/room-edit";
import { newWall } from "@/engine/drawing/wall-add";
import {
  type Compass,
  isFacade,
  isMovableWall,
  moveDirections,
  offsetTowards,
  WALL_SNAP_M,
} from "@/engine/drawing/wall-edit";
import type { ModelIndex } from "@/engine/model/model-index";
import { ROOM_TYPE_LABELS } from "@/features/editing/components/ElementEditSection";
import { useEditStore } from "@/features/editing/store";
import type { Version } from "@/lib/api/schemas";
import { useSelectionStore } from "@/stores/selection-store";

const ARROWS: Record<string, Compass> = {
  ArrowUp: "north",
  ArrowDown: "south",
  ArrowLeft: "west",
  ArrowRight: "east",
};

const ARROW_LABEL: Record<Compass, string> = {
  north: "↑ North",
  south: "↓ South",
  west: "← West",
  east: "East →",
};

const OPPOSITE: Record<Compass, Compass> = {
  north: "south",
  south: "north",
  east: "west",
  west: "east",
};

const DOOR_KINDS: { value: DoorKind; label: string }[] = [
  { value: "interior", label: "Interior door" },
  { value: "entrance", label: "Entrance door" },
  { value: "sliding", label: "Sliding glass door" },
];
const WINDOW_KINDS: { value: WindowKind; label: string }[] = [
  { value: "casement", label: "Casement window" },
  { value: "fixed", label: "Fixed window" },
  { value: "sliding", label: "Sliding window" },
  { value: "panoramic", label: "Panoramic window" },
];

const round3 = (v: number) => Math.round(v * 1000) / 1000;

function typingInField(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

/**
 * Editing controls over the plan: undo / redo, the number of changes, discard, save as a new
 * version, the selected wall's move controls, the selected room's resize controls, the selected
 * door or window's position and Remove, adding a door or window, and the server's verdict on
 * the last change. Sizes of doors and windows, wall removal and room names and types are edited
 * in the properties panel (ElementEditSection) and join the same session. Keyboard: Ctrl+Z / Ctrl+Shift+Z (or Ctrl+Y); arrows nudge the selected wall,
 * the chosen side of the selected room, or the selected opening along its wall by 5 cm
 * (Shift: 25 cm); Delete removes the selected opening; Esc stops placing a new one.
 */
export function PlanEditBar({
  index,
  onSaved,
}: {
  index: ModelIndex;
  onSaved?: (version: Version) => void;
}) {
  const ops = useEditStore((s) => s.ops);
  const cursor = useEditStore((s) => s.cursor);
  const busy = useEditStore((s) => s.busy);
  const message = useEditStore((s) => s.message);
  const selectedId = useSelectionStore((s) => s.selectedId);
  const selected = selectedId ? index.elementsById.get(selectedId) : undefined;
  const wall = isMovableWall(selected) ? selected : null;
  const room = selected?.type === "room" ? selected : null;
  const chosen = useEditStore((s) => s.side);
  const side =
    room && chosen?.roomId === room.id ? (roomSides(index, room)[chosen.edge] ?? null) : null;
  const sideMovable = side?.resizable ?? false;
  const [distance, setDistance] = useState("0.10");
  const opening = isOpening(selected) ? selected : null;
  const host = opening ? (index.hostOf.get(opening.id) ?? null) : null;
  const placing = useEditStore((s) => s.placing);
  const placingWall = useEditStore((s) => s.placingWall);
  const [position, setPosition] = useState<{ id: string; value: string } | null>(null);
  const positionValue =
    opening && position?.id === opening.id
      ? position.value
      : (opening?.position.x.toFixed(2) ?? "");

  /** Put the selected opening's start edge at `offset` along its wall. */
  const place = (offset: number) => {
    if (!opening || !Number.isFinite(offset)) return;
    const at = Math.max(0, round3(offset));
    if (at === opening.position.x) return;
    setPosition(null);
    void useEditStore
      .getState()
      .apply({ op: "move_opening", opening_id: opening.id, offset_m: at });
  };

  const slide = (direction: Compass, meters: number) => {
    if (!opening || !host) return;
    const delta = slideTowards(host, direction, meters);
    if (delta !== 0) place(opening.position.x + delta);
  };

  const remove = () => {
    if (!opening) return;
    void useEditStore
      .getState()
      .apply({ op: "remove_element", element_id: opening.id })
      .then((ok) => {
        if (ok) useSelectionStore.getState().select(null);
      });
  };

  const startAdding = (kind: "door" | "window") => {
    useSelectionStore.getState().select(null);
    useEditStore.getState().setPlacing(newOpening(index, kind));
  };

  /** Move the chosen side towards `direction`: outwards grows the room, inwards shrinks it. */
  const resize = (direction: Compass, meters: number) => {
    if (!room || !side || !sideMovable || !(meters > 0)) return;
    const sign = direction === side.compass ? 1 : direction === OPPOSITE[side.compass] ? -1 : 0;
    if (sign === 0) return;
    void useEditStore.getState().apply({
      op: "resize_room",
      room_id: room.id,
      edge: side.index,
      delta_m: Math.round(sign * meters * 1000) / 1000,
    });
  };

  const move = (direction: Compass, meters: number) => {
    if (!wall || !(meters > 0)) return;
    const offset = Math.round(offsetTowards(wall, direction, meters) * 1000) / 1000;
    if (offset === 0) return;
    void useEditStore.getState().apply({ op: "move_wall", wall_id: wall.id, offset_m: offset });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const store = useEditStore.getState();
      if (e.key === "Escape" && (store.placing || store.placingWall)) {
        store.setPlacing(null); // also from the size fields of the add panels
        store.setPlacingWall(null);
        return;
      }
      if (typingInField(e.target)) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        void (e.shiftKey ? store.redo() : store.undo());
      } else if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        void store.redo();
      } else if (opening && (e.key === "Delete" || e.key === "Backspace") && !store.busy) {
        e.preventDefault();
        remove();
      } else if (opening && host && ARROWS[e.key] && !store.busy) {
        const direction = ARROWS[e.key];
        if (slideTowards(host, direction, 1) === 0) return; // across the wall: not a slide
        e.preventDefault();
        slide(direction, e.shiftKey ? OPENING_SNAP_M * 5 : OPENING_SNAP_M);
      } else if (wall && ARROWS[e.key] && !store.busy) {
        const direction = ARROWS[e.key];
        if (offsetTowards(wall, direction, 1) === 0) return; // along the wall: not a move
        e.preventDefault();
        move(direction, e.shiftKey ? WALL_SNAP_M * 5 : WALL_SNAP_M);
      } else if (side && sideMovable && ARROWS[e.key] && !store.busy) {
        const direction = ARROWS[e.key];
        if (direction !== side.compass && direction !== OPPOSITE[side.compass]) return;
        e.preventDefault();
        resize(direction, e.shiftKey ? WALL_SNAP_M * 5 : WALL_SNAP_M);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // A refusal's headline already quotes its first finding; warnings list all of theirs.
  const listed = message?.issues?.slice(message.tone === "error" ? 1 : 0) ?? [];
  const store = useEditStore.getState();
  const save = async () => {
    const version = await store.save();
    if (version) onSaved?.(version);
  };

  return (
    <div className="absolute right-3 top-3 flex w-[min(92%,340px)] flex-col gap-2">
      <div
        role="toolbar"
        aria-label="Plan editing"
        className="flex flex-wrap items-center gap-1 rounded-md bg-white/95 p-1.5 text-xs shadow ring-1 ring-neutral-200"
      >
        <BarButton
          onClick={() => void store.undo()}
          disabled={busy || cursor === 0}
          title="Undo (Ctrl+Z)"
        >
          Undo
        </BarButton>
        <BarButton
          onClick={() => void store.redo()}
          disabled={busy || cursor >= ops.length}
          title="Redo (Ctrl+Shift+Z)"
        >
          Redo
        </BarButton>
        <span className="px-1 tabular-nums text-neutral-600" aria-live="polite">
          {busy
            ? "Checking…"
            : cursor === 0
              ? "No changes"
              : `${cursor} change${cursor > 1 ? "s" : ""}`}
        </span>
        <span className="ml-auto flex gap-1">
          <BarButton
            onClick={() => store.discard()}
            disabled={busy || cursor === 0}
            title="Back to the saved version"
          >
            Discard
          </BarButton>
          <BarButton
            onClick={() => void save()}
            disabled={busy || cursor === 0}
            primary
            title="Save the edited plan as a new version"
          >
            Save version
          </BarButton>
        </span>
      </div>

      {placing ? (
        <PlacingPanel index={index} />
      ) : placingWall ? (
        <WallPlacingPanel />
      ) : (
        <div className="flex items-center gap-1 rounded-md bg-white/95 p-1.5 text-xs shadow ring-1 ring-neutral-200">
          <span className="px-1 text-neutral-600">Add</span>
          <BarButton onClick={() => startAdding("door")} disabled={busy} title="Add a door">
            + Door
          </BarButton>
          <BarButton onClick={() => startAdding("window")} disabled={busy} title="Add a window">
            + Window
          </BarButton>
          <BarButton
            onClick={() => {
              useSelectionStore.getState().select(null);
              useEditStore.getState().setPlacingWall(newWall(index));
            }}
            disabled={busy}
            title="Divide a room with a new wall"
          >
            + Wall
          </BarButton>
        </div>
      )}

      {placing || placingWall ? null : opening && host ? (
        <div className="rounded-md bg-white/95 p-2 text-xs shadow ring-1 ring-neutral-200">
          <p className="mb-1.5 text-neutral-700">
            <span className="font-semibold">{opening.name}</span> ·{" "}
            {opening.dimensions.width.toFixed(2)} × {opening.dimensions.height.toFixed(2)} m in{" "}
            {host.name} · drag it along the wall or onto another one; drag its end grips (or use the
            Properties panel) to resize it; or
          </p>
          <div className="flex flex-wrap items-center gap-1">
            <label htmlFor="opening-position" className="text-neutral-600">
              Position
            </label>
            <input
              id="opening-position"
              type="number"
              min={0}
              max={host.dimensions.length}
              step={OPENING_SNAP_M}
              value={positionValue}
              aria-describedby="opening-position-help"
              onChange={(e) => setPosition({ id: opening.id, value: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") place(Number(positionValue));
              }}
              className="w-16 rounded border border-neutral-300 px-1.5 py-0.5 tabular-nums"
            />
            <span id="opening-position-help" className="text-neutral-500">
              m from the wall start
            </span>
            <BarButton onClick={() => place(Number(positionValue))} disabled={busy}>
              Move
            </BarButton>
            {slideDirections(host).map((d) => (
              <BarButton
                key={d}
                onClick={() => slide(d, OPENING_SNAP_M)}
                disabled={busy}
                title={`Slide 5 cm ${d}`}
              >
                {ARROW_LABEL[d]}
              </BarButton>
            ))}
            <BarButton onClick={remove} disabled={busy} title="Remove (Delete)" danger>
              Remove
            </BarButton>
          </div>
        </div>
      ) : wall ? (
        <div className="rounded-md bg-white/95 p-2 text-xs shadow ring-1 ring-neutral-200">
          <p className="mb-1.5 text-neutral-700">
            <span className="font-semibold">{wall.name}</span> ·{" "}
            {isFacade(wall)
              ? "drag the facade on the plan (it moves on every storey with slabs and roof), or move by"
              : "drag it on the plan (remove it in the Properties panel), or move by"}
          </p>
          <div className="flex items-center gap-1">
            <label className="sr-only" htmlFor="wall-move-distance">
              Distance in meters
            </label>
            <input
              id="wall-move-distance"
              type="number"
              min={0.01}
              max={20}
              step={0.05}
              value={distance}
              onChange={(e) => setDistance(e.target.value)}
              className="w-16 rounded border border-neutral-300 px-1.5 py-0.5 tabular-nums"
            />
            <span className="text-neutral-500">m</span>
            {moveDirections(wall).map((d) => (
              <BarButton key={d} onClick={() => move(d, Number(distance))} disabled={busy}>
                {ARROW_LABEL[d]}
              </BarButton>
            ))}
          </div>
        </div>
      ) : room && side && sideMovable ? (
        <div className="rounded-md bg-white/95 p-2 text-xs shadow ring-1 ring-neutral-200">
          <p className="mb-1.5 text-neutral-700">
            <span className="font-semibold">{room.name}</span> · {side.compass} side (
            {side.walls.map((w) => w.name).join(", ")}) · drag its handle, or
          </p>
          <div className="flex items-center gap-1">
            <label className="sr-only" htmlFor="wall-move-distance">
              Distance in meters
            </label>
            <input
              id="wall-move-distance"
              type="number"
              min={0.01}
              max={20}
              step={0.05}
              value={distance}
              onChange={(e) => setDistance(e.target.value)}
              className="w-16 rounded border border-neutral-300 px-1.5 py-0.5 tabular-nums"
            />
            <span className="text-neutral-500">m</span>
            <BarButton
              onClick={() => resize(OPPOSITE[side.compass], Number(distance))}
              disabled={busy}
            >
              Shrink
            </BarButton>
            <BarButton onClick={() => resize(side.compass, Number(distance))} disabled={busy}>
              Enlarge
            </BarButton>
          </div>
        </div>
      ) : (
        <p className="rounded-md bg-white/90 px-2 py-1 text-xs text-neutral-600 shadow-sm ring-1 ring-neutral-200">
          {room && side
            ? sideRefusal(room, side)
            : room
              ? `Click a side handle of ${room.name} to resize it; rename it or change its type in the Properties panel.`
              : selected?.type === "wall"
                ? `${selected.name} is a partition; it cannot be moved on the plan.`
                : "Select a wall, a room, a door or a window, then drag it or use the arrow keys."}
        </p>
      )}

      {message && (
        <div
          role={message.tone === "error" ? "alert" : "status"}
          className={
            "rounded-md p-2 text-xs shadow ring-1 " +
            (message.tone === "error"
              ? "bg-red-50 text-red-800 ring-red-200"
              : message.tone === "warning"
                ? "bg-amber-50 text-amber-900 ring-amber-200"
                : "bg-white text-neutral-700 ring-neutral-200")
          }
        >
          <div className="flex items-start gap-2">
            <p className="flex-1 font-medium">{message.text}</p>
            <button
              type="button"
              aria-label="Dismiss"
              onClick={() => store.dismissMessage()}
              className="leading-none opacity-70 hover:opacity-100"
            >
              ×
            </button>
          </div>
          {listed.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {listed.slice(0, 3).map((i, k) => (
                <li key={k}>{i.message}</li>
              ))}
              {listed.length > 3 && <li>… {listed.length - 3} more</li>}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Choosing the door or window to add (kind and size, sized like the model's own openings of
 * that kind); the plan then places it where a wall is clicked.
 */
function PlacingPanel({ index }: { index: ModelIndex }) {
  const placing = useEditStore((s) => s.placing);
  if (!placing) return null;
  const set = useEditStore.getState().setPlacing;
  const kinds = placing.kind === "door" ? DOOR_KINDS : WINDOW_KINDS;
  const kindValue = placing.kind === "door" ? placing.doorKind : placing.windowKind;
  const number = (key: "width" | "height" | "sill", label: string) => (
    <label className="flex items-center gap-1 text-neutral-600">
      {label}
      <input
        type="number"
        min={key === "sill" ? 0 : 0.1}
        max={6}
        step={0.05}
        value={placing[key]}
        onChange={(e) => {
          const v = Number(e.target.value);
          if (Number.isFinite(v) && v >= 0) set({ ...placing, [key]: round3(v) });
        }}
        className="w-14 rounded border border-neutral-300 px-1 py-0.5 tabular-nums"
      />
    </label>
  );
  return (
    <div
      role="group"
      aria-label={`Add a ${placing.kind}`}
      className="rounded-md bg-white/95 p-2 text-xs shadow ring-1 ring-blue-300"
    >
      <div className="mb-1.5 flex items-center gap-1">
        <label className="sr-only" htmlFor="new-opening-kind">
          Kind
        </label>
        <select
          id="new-opening-kind"
          value={kindValue}
          onChange={(e) => {
            const next =
              placing.kind === "door"
                ? newOpening(index, "door", e.target.value as DoorKind)
                : newOpening(index, "window", "interior", e.target.value as WindowKind);
            set(next);
          }}
          className="rounded border border-neutral-300 px-1 py-0.5"
        >
          {kinds.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
        <span className="ml-auto">
          <BarButton onClick={() => set(null)} title="Stop adding (Esc)">
            Cancel
          </BarButton>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {number("width", "Width")}
        {number("height", "Height")}
        {placing.kind === "window" && number("sill", "Sill")}
        <span className="text-neutral-500">m</span>
      </div>
      <p className="mt-1.5 text-neutral-600">
        Click a wall on the plan to place the {placing.kind}
        {placing.kind === "window" || placing.doorKind !== "interior"
          ? " (exterior walls only)"
          : ""}
        .
      </p>
    </div>
  );
}

/**
 * Choosing the wall to add: its direction, a door in it, and the type of the new room; the plan
 * then shows the wall across the room under the pointer, and a click places it.
 */
function WallPlacingPanel() {
  const spec = useEditStore((s) => s.placingWall);
  if (!spec) return null;
  const set = useEditStore.getState().setPlacingWall;
  return (
    <div
      role="group"
      aria-label="Add a wall"
      className="rounded-md bg-white/95 p-2 text-xs shadow ring-1 ring-blue-300"
    >
      <div className="mb-1.5 flex flex-wrap items-center gap-1">
        <span className="text-neutral-600">Direction</span>
        {(
          [
            ["north_south", "↕ North–south"],
            ["east_west", "↔ East–west"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={spec.direction === value}
            onClick={() => set({ ...spec, direction: value })}
            className={
              "rounded px-2 py-1 font-medium " +
              (spec.direction === value
                ? "bg-blue-600 text-white"
                : "bg-neutral-100 text-neutral-800 hover:bg-neutral-200")
            }
          >
            {label}
          </button>
        ))}
        <span className="ml-auto">
          <BarButton onClick={() => set(null)} title="Stop adding (Esc)">
            Cancel
          </BarButton>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1 text-neutral-600">
          <input
            type="checkbox"
            checked={spec.door}
            onChange={(e) => set({ ...spec, door: e.target.checked })}
          />
          Door
        </label>
        {spec.door && (
          <label className="flex items-center gap-1 text-neutral-600">
            Width
            <input
              type="number"
              aria-label="Door width in meters"
              min={0.5}
              max={3}
              step={0.05}
              value={spec.doorWidth}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (Number.isFinite(v) && v > 0) set({ ...spec, doorWidth: round3(v) });
              }}
              className="w-14 rounded border border-neutral-300 px-1 py-0.5 tabular-nums"
            />
          </label>
        )}
        <label className="flex items-center gap-1 text-neutral-600">
          New room
          <select
            aria-label="New room type"
            value={spec.newRoomType ?? ""}
            onChange={(e) =>
              set({
                ...spec,
                newRoomType: (e.target.value || null) as typeof spec.newRoomType,
              })
            }
            className="rounded border border-neutral-300 px-1 py-0.5"
          >
            <option value="">Same as the room</option>
            {Object.entries(ROOM_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="mt-1.5 text-neutral-600">
        Click inside a room to divide it: the wall runs across the room through that point and must
        meet a wall at both ends. The smaller part becomes the new room.
      </p>
    </div>
  );
}

function BarButton({
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
        "rounded px-2 py-1 font-medium disabled:opacity-40 " +
        (primary
          ? "bg-blue-600 text-white hover:bg-blue-700"
          : danger
            ? "bg-red-50 text-red-700 hover:bg-red-100"
            : "bg-neutral-100 text-neutral-800 hover:bg-neutral-200")
      }
    >
      {children}
    </button>
  );
}
