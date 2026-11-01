"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { P2 } from "@/engine/math/polygon";
import {
  isOpening,
  type NewOpening,
  offsetFor,
  OPENING_SNAP_M,
  openingCenter,
  openingOutline,
  resizedOpening,
  wallAt,
  wallLocal,
  wallMargins,
  wallPoint,
} from "@/engine/drawing/opening-edit";
import { buildPlanDrawing } from "@/engine/drawing/plan";
import {
  deltaFromDrag,
  movedSideOutline,
  roomExtent,
  type RoomSide,
  roomSides,
} from "@/engine/drawing/room-edit";
import { fmt, paperBox, paperPoint, renderPlanContent } from "@/engine/drawing/svg";
import {
  interiorThickness,
  type NewWall,
  roomAt,
  snapPoint,
  wallAcross,
  wallBody,
} from "@/engine/drawing/wall-add";
import {
  isFacade,
  isMovableWall,
  movedWallOutline,
  offsetFromDrag,
  roofOutlines,
  snapOffset,
} from "@/engine/drawing/wall-edit";
import type { ModelIndex } from "@/engine/model/model-index";
import { parseBuildingModel } from "@/engine/model/parse";
import type { Opening, Room, Wall } from "@/engine/model/types";
import { useEditStore } from "@/features/editing/store";
import type { EditOperation, EditPreview, Version } from "@/lib/api/schemas";
import { useBuildingStore } from "@/stores/building-store";
import { useLayerStore } from "@/stores/layer-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";

import { PlanEditBar } from "./PlanEditBar";

const currentModelIndex = () => useBuildingStore.getState().index;

interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * What is being placed: an interior wall or one side of a room (moved sideways), a door or
 * window (dragged along / onto a wall; `start` = its centre when the drag began), one end of a
 * door or window (resizing it along its wall), or a new opening following the pointer.
 */
type DragTarget =
  | { kind: "wall"; wall: Wall }
  | { kind: "side"; room: Room; side: RoomSide }
  | { kind: "opening"; opening: Opening; host: Wall; start: P2 }
  | { kind: "size"; opening: Opening; host: Wall; end: "start" | "end" }
  | { kind: "new"; spec: NewOpening }
  | { kind: "newWall"; spec: NewWall };

/** A drag in progress: the snapped position and the server's answer for it, once known. */
interface Drag {
  target: DragTarget;
  /** Walls and sides: the signed move. Openings: the start edge's offset along `wall`. */
  offset: number;
  /** Resizing an opening: its new width. */
  width?: number;
  /** A new wall: the snapped point it goes through, the room it divides, its line. */
  point?: P2;
  room?: Room | null;
  line?: [P2, P2] | null;
  /** Openings: the wall the opening is placed in (null: the pointer is on no wall). */
  wall: Wall | null;
  preview: EditPreview | null;
  /** Position (`positionKey`) the preview was computed for. */
  previewFor: string | null;
}

const MARGIN_MM = 8;
const CLICK_SLOP_PX = 4;
const ZOOM_STEP = 1.25;
const PREVIEW_DEBOUNCE_MS = 60;
/** Side handles, in paper mm: pointer target width and grip radius. */
const SIDE_HIT_MM = 2.4;
const SIDE_GRIP_MM = 1.3;
/** Narrowest opening a grip drag proposes (m): input sanity; the rules profile judges sizes. */
const MIN_GRIP_WIDTH_M = 0.1;

function targetKey(t: DragTarget): string {
  if (t.kind === "wall") return t.wall.id;
  if (t.kind === "side") return `${t.room.id}:${t.side.index}`;
  if (t.kind === "opening") return t.opening.id;
  if (t.kind === "size") return `size:${t.opening.id}:${t.end}`;
  if (t.kind === "newWall") {
    const w = t.spec;
    return `newWall:${w.direction}:${w.door}:${w.doorWidth}:${w.doorHeight}:${w.newRoomType}`;
  }
  const n = t.spec;
  return `new:${n.kind}:${n.doorKind}:${n.windowKind}:${n.width}:${n.height}:${n.sill}`;
}

function positionKey(d: Pick<Drag, "wall" | "offset" | "width" | "point" | "room">): string {
  return `${d.wall?.id ?? ""}@${d.offset}:${d.width ?? ""}:${d.point?.join(",") ?? ""}:${d.room?.id ?? ""}`;
}

/** Whether the drag would change the model (otherwise nothing is checked or applied). */
function isChange(
  d: Pick<Drag, "target" | "wall" | "offset" | "width" | "room" | "line">,
): boolean {
  const t = d.target;
  if (t.kind === "newWall") return Boolean(d.room && d.line);
  if (t.kind === "wall" || t.kind === "side") return d.offset !== 0;
  if (t.kind === "size") {
    return d.offset !== t.opening.position.x || d.width !== t.opening.dimensions.width;
  }
  if (!d.wall) return false;
  return t.kind === "new" || d.wall.id !== t.host.id || d.offset !== t.opening.position.x;
}

function operationFor(
  d: Pick<Drag, "target" | "wall" | "offset" | "width" | "point" | "room">,
): EditOperation {
  const t = d.target;
  if (t.kind === "newWall") {
    const w = t.spec;
    const [x, y] = d.point ?? [0, 0];
    return {
      op: "add_wall",
      room_id: d.room?.id ?? "",
      direction: w.direction,
      x_m: x,
      y_m: y,
      ...(w.newRoomType ? { new_room_type: w.newRoomType } : {}),
      ...(w.door ? { door_width_m: w.doorWidth, door_height_m: w.doorHeight } : {}),
    };
  }
  if (t.kind === "wall") return { op: "move_wall", wall_id: t.wall.id, offset_m: d.offset };
  if (t.kind === "side") {
    return { op: "resize_room", room_id: t.room.id, edge: t.side.index, delta_m: d.offset };
  }
  if (t.kind === "size") {
    return {
      op: "resize_opening",
      opening_id: t.opening.id,
      width_m: d.width ?? t.opening.dimensions.width,
      height_m: t.opening.dimensions.height,
      offset_m: d.offset,
    };
  }
  const wallId = d.wall?.id ?? "";
  if (t.kind === "opening") {
    return {
      op: "move_opening",
      opening_id: t.opening.id,
      offset_m: d.offset,
      ...(wallId !== t.host.id ? { host_wall_id: wallId } : {}),
    };
  }
  const n = t.spec;
  return {
    op: "add_opening",
    kind: n.kind,
    host_wall_id: wallId,
    offset_m: d.offset,
    width_m: n.width,
    height_m: n.height,
    ...(n.kind === "door"
      ? { door_kind: n.doorKind }
      : { sill_m: n.sill, window_kind: n.windowKind }),
  };
}

function widthOf(d: Pick<Drag, "target" | "width">): number {
  const t = d.target;
  if (t.kind === "size") return d.width ?? t.opening.dimensions.width;
  return t.kind === "opening" ? t.opening.dimensions.width : t.kind === "new" ? t.spec.width : 0;
}

/** The start offset and width of an opening with one end dragged to `u` along its wall. */
function gripResize(opening: Opening, end: "start" | "end", u: number): [number, number] {
  const snapped = Math.round(u / OPENING_SNAP_M) * OPENING_SNAP_M;
  const x0 = opening.position.x;
  const x1 = x0 + opening.dimensions.width;
  const r = (v: number) => Math.round(v * 1000) / 1000 || 0;
  if (end === "end") return [x0, r(Math.max(snapped - x0, MIN_GRIP_WIDTH_M))];
  const start = r(Math.max(0, Math.min(snapped, x1 - MIN_GRIP_WIDTH_M)));
  return [start, r(x1 - start)];
}

/** CSS for the selected element; ids are UUIDs, safe inside an attribute selector. */
function highlightCss(selectedId: string | null, editable: boolean): string {
  const base =
    "[data-element-id]{cursor:pointer}" +
    '[data-element-id]:hover [data-fill="hit"]{fill:#2563eb;fill-opacity:.06}';
  if (!selectedId || !/^[0-9a-f-]+$/i.test(selectedId)) return base;
  const s = `[data-element-id="${selectedId}"]`;
  return (
    base +
    `${s} [data-fill="solid"]{fill:#2563eb}` +
    `${s} polygon,${s} polyline,${s} circle{stroke:#2563eb}` +
    `${s} [data-fill="hit"]{fill:#2563eb;fill-opacity:.12}` +
    `${s} text{fill:#1d4ed8}` +
    (editable ? `[data-role="wall"]${s},[data-role="opening"]${s}{cursor:grab}` : "")
  );
}

/**
 * The floor plan of one level, drawn from the BuildingModel by the same engine as the
 * downloadable sheets. Scroll to zoom, drag to pan, click an element to select it (shared
 * selection with the 3D view and the properties panel).
 *
 * In a project (an editing session is open) the plan is also editable: drag a selected
 * interior wall to move it, select a room and drag one of its side handles to resize it, drag a
 * selected door or window along its wall or onto another wall, or place a new one (chosen in
 * the edit bar) by clicking a wall.
 * While dragging, every snapped position is checked by the server and the plan shows the
 * resulting model, or why the change is not possible; on release a valid change becomes an
 * operation of the session (undo/redo, save as a new version).
 */
export function PlanView({
  index,
  onEditsSaved,
}: {
  index: ModelIndex;
  onEditsSaved?: (version: Version) => void;
}) {
  const planLevelId = useViewerStore((s) => s.planLevelId);
  const furniture = useLayerStore((s) => s.visible.furniture);
  const selectedId = useSelectionStore((s) => s.selectedId);
  const select = useSelectionStore((s) => s.select);
  const editable = useEditStore((s) => s.versionId !== null);
  const chosenSide = useEditStore((s) => s.side);
  const placing = useEditStore((s) => (s.versionId !== null ? s.placing : null));
  const placingWall = useEditStore((s) => (s.versionId !== null ? s.placingWall : null));
  // A change being prepared in the properties panel (size, wall removal, room type).
  const draft = useEditStore((s) => (s.versionId !== null ? s.draft : null));
  const level = index.levels.find((l) => l.id === planLevelId) ?? index.levels[0];
  const selected = selectedId ? index.elementsById.get(selectedId) : undefined;
  const selectedRoom =
    editable && selected?.type === "room" && selected.level_id === level?.id ? selected : null;
  const selectedOpening =
    editable && isOpening(selected) && selected.level_id === level?.id ? selected : null;
  const selectedHost = selectedOpening ? (index.hostOf.get(selectedOpening.id) ?? null) : null;
  const sides = useMemo(
    () => (selectedRoom ? roomSides(index, selectedRoom) : []),
    [index, selectedRoom],
  );

  const [dragState, setDrag] = useState<Drag | null>(null);
  // The outline of a new opening lasts only while it is being placed.
  const drag =
    (dragState?.target.kind === "new" && !placing) ||
    (dragState?.target.kind === "newWall" && !placingWall)
      ? null
      : dragState;

  // While a valid preview is on screen, the plan shows the model the server returned for it:
  // the dragged position, or else a change prepared in the properties panel.
  const dragPreview = drag ? drag.preview : (draft?.preview ?? null);
  const previewIndex = useMemo(() => {
    if (!dragPreview?.valid || dragPreview.model === null) return null;
    try {
      return parseBuildingModel(dragPreview.model);
    } catch {
      return null;
    }
  }, [dragPreview]);
  const shownIndex = previewIndex ?? index;
  // A facade being moved or re-sized: the roof outline (eaves) is drawn dashed over the plan.
  const chosen =
    selectedRoom && chosenSide?.roomId === selectedRoom.id ? sides[chosenSide.edge] : null;
  const facadeEdit =
    editable &&
    ((selected?.type === "wall" && isFacade(selected)) ||
      (drag?.target.kind === "side" && drag.target.side.kind === "exterior") ||
      chosen?.kind === "exterior");

  const drawing = useMemo(
    () => (level ? buildPlanDrawing(shownIndex, level.id, { furniture }) : null),
    [shownIndex, level, furniture],
  );
  const content = useMemo(
    () => (drawing ? renderPlanContent(drawing, { interactive: true }) : ""),
    [drawing],
  );
  const fitBox = useMemo<ViewBox | null>(() => {
    if (!drawing) return null;
    const b = paperBox(drawing.bounds, drawing.scale, MARGIN_MM);
    return { x: b.x, y: b.y, w: b.width, h: b.height };
  }, [drawing]);

  const svgRef = useRef<SVGSVGElement>(null);
  const [view, setView] = useState<ViewBox | null>(fitBox);
  // Frame the drawing when another model or level is shown; edits keep the current view.
  const fitKey = `${index.model.id}:${level?.id ?? ""}`;
  const [fittedFor, setFittedFor] = useState<string | null>(view ? fitKey : null);
  if (fitBox && fittedFor !== fitKey) {
    setFittedFor(fitKey);
    setView(fitBox);
  }

  const fit = useCallback(() => setView(fitBox), [fitBox]);

  /** Paper mm per client pixel for the current view ("meet" scaling). */
  const mmPerPixel = useCallback((v: ViewBox) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return 1;
    return Math.max(v.w / rect.width, v.h / rect.height);
  }, []);

  /** Zoom by `factor` (> 1 = in) around a point given in client pixels. */
  const zoomAt = useCallback((factor: number, clientX?: number, clientY?: number) => {
    const svg = svgRef.current;
    setView((v) => {
      if (!v || !svg) return v;
      const rect = svg.getBoundingClientRect();
      const scale = Math.max(v.w / rect.width, v.h / rect.height);
      const ox = v.x + v.w / 2 - (rect.width * scale) / 2;
      const oy = v.y + v.h / 2 - (rect.height * scale) / 2;
      const px = clientX === undefined ? v.x + v.w / 2 : ox + (clientX - rect.left) * scale;
      const py = clientY === undefined ? v.y + v.h / 2 : oy + (clientY - rect.top) * scale;
      const w = Math.min(Math.max(v.w / factor, 5), 5000);
      const k = w / v.w;
      return { x: px - (px - v.x) * k, y: py - (py - v.y) * k, w, h: v.h * k };
    });
  }, []);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY);
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  // Live check of the dragged position: debounced, latest wins, stale answers are dropped.
  const dragKey = drag ? targetKey(drag.target) : null;
  const dragPos = drag ? positionKey(drag) : null;
  useEffect(() => {
    if (!drag || !isChange(drag)) return;
    const at = drag;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      useEditStore
        .getState()
        .check(operationFor(at), controller.signal)
        .then((preview) =>
          setDrag((d) =>
            d && targetKey(d.target) === dragKey && positionKey(d) === dragPos
              ? { ...d, preview, previewFor: dragPos }
              : d,
          ),
        )
        .catch(() => undefined); // aborted, or reported again on release
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // The target object is stable for a key; re-check only when the key or position changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragKey, dragPos]);

  /** Model plan coordinates of a client pixel ("meet" scaling, centred, as in zoomAt). */
  const clientToModel = (clientX: number, clientY: number): P2 | null => {
    const svg = svgRef.current;
    if (!svg || !view || !drawing) return null;
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    const k = Math.max(view.w / rect.width, view.h / rect.height);
    const px = view.x + view.w / 2 - (rect.width * k) / 2 + (clientX - rect.left) * k;
    const py = view.y + view.h / 2 - (rect.height * k) / 2 + (clientY - rect.top) * k;
    const m = drawing.scale / 1000;
    return [px * m, -py * m];
  };

  /** Where a new opening would go for the pointer at a client pixel (also returned). */
  const hoverPlacement = (spec: NewOpening, clientX: number, clientY: number): Drag => {
    const point = level ? clientToModel(clientX, clientY) : null;
    const on = point && level ? wallAt(index, level.id, point) : null;
    const target: DragTarget = { kind: "new", spec };
    const next = { wall: on?.wall ?? null, offset: on ? offsetFor(on.u, spec.width) : 0 };
    // The same position as now: keep it, with its live check.
    if (drag && targetKey(drag.target) === targetKey(target)) {
      if (positionKey(drag) === positionKey(next)) return drag;
    }
    const result: Drag = { target, ...next, preview: null, previewFor: null };
    setDrag(result);
    return result;
  };

  /** Where a new wall would go for the pointer at a client pixel (also returned). */
  const hoverWall = (spec: NewWall, clientX: number, clientY: number): Drag => {
    const raw = level ? clientToModel(clientX, clientY) : null;
    const point = raw ? snapPoint(raw) : undefined;
    const room = point && level ? roomAt(index, level.id, point) : null;
    const line = room && point ? wallAcross(room, point, spec.direction) : null;
    const target: DragTarget = { kind: "newWall", spec };
    const next = { wall: null, offset: 0, point, room, line };
    if (drag && targetKey(drag.target) === targetKey(target)) {
      if (positionKey(drag) === positionKey(next)) return drag;
    }
    const result: Drag = { target, ...next, preview: null, previewFor: null };
    setDrag(result);
    return result;
  };

  const pointer = useRef<{
    x: number;
    y: number;
    moved: boolean;
    view: ViewBox;
    target: DragTarget | null;
    onSide: boolean;
  } | null>(null);

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!view || e.button !== 0) return;
    let target: DragTarget | null = null;
    const handle = (e.target as Element).closest<SVGElement>("[data-side]");
    const grip = (e.target as Element).closest<SVGElement>("[data-grip]");
    if (placing || placingWall) {
      // Placing a new opening or wall: a click places it, a drag pans.
    } else if (grip && selectedOpening && selectedHost) {
      // An end grip of the selected door or window: drag it to resize along the wall.
      target = {
        kind: "size",
        opening: selectedOpening,
        host: selectedHost,
        end: grip.dataset.grip === "start" ? "start" : "end",
      };
    } else if (handle && selectedRoom) {
      // A side handle of the selected room: choose that side; drag it if it can move.
      const side = sides[Number(handle.dataset.side)];
      if (side) {
        useEditStore.getState().chooseSide({ roomId: selectedRoom.id, edge: side.index });
        if (side.resizable) target = { kind: "side", room: selectedRoom, side };
      }
    } else {
      const hit = (e.target as Element).closest<SVGElement>("[data-element-id]");
      const el = hit ? index.elementsById.get(hit.dataset.elementId ?? "") : undefined;
      // Dragging the selected interior wall or opening moves it; anything else pans.
      if (editable && el?.id === selectedId && isMovableWall(el)) {
        target = { kind: "wall", wall: el };
      } else if (editable && el?.id === selectedId && isOpening(el)) {
        const host = index.hostOf.get(el.id);
        const start = openingCenter(index, el);
        if (host && start) target = { kind: "opening", opening: el, host, start };
      }
    }
    pointer.current = {
      x: e.clientX,
      y: e.clientY,
      moved: false,
      view,
      target,
      onSide: handle !== null || grip !== null,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const p = pointer.current;
    if (!p) {
      if (placing) hoverPlacement(placing, e.clientX, e.clientY);
      else if (placingWall) hoverWall(placingWall, e.clientX, e.clientY);
      return;
    }
    const dx = e.clientX - p.x;
    const dy = e.clientY - p.y;
    if (!p.moved && Math.hypot(dx, dy) < CLICK_SLOP_PX) return;
    p.moved = true;
    const k = mmPerPixel(p.view);
    if (p.target && drawing) {
      // Client pixels -> paper mm -> model meters (+y north = up the screen).
      const m = (k * drawing.scale) / 1000;
      const target = p.target;
      const moved: P2 = [dx * m, -dy * m];
      let next: Pick<Drag, "wall" | "offset" | "width">;
      if (target.kind === "size") {
        const point = clientToModel(e.clientX, e.clientY);
        if (!point) return;
        const [offset, width] = gripResize(
          target.opening,
          target.end,
          wallLocal(target.host, point)[0],
        );
        next = { wall: target.host, offset, width };
      } else if (target.kind === "opening") {
        // Along its wall, or onto the wall the pointer is over (same level).
        const point: P2 = [target.start[0] + moved[0], target.start[1] + moved[1]];
        const on = level ? wallAt(index, level.id, point, target.host) : null;
        const u = on ? on.u : wallLocal(target.host, point)[0];
        next = { wall: on?.wall ?? target.host, offset: offsetFor(u, widthOf({ target })) };
      } else {
        const offset =
          target.kind === "wall"
            ? offsetFromDrag(target.wall, moved)
            : target.kind === "side"
              ? deltaFromDrag(target.side, moved)
              : 0;
        next = { wall: null, offset: snapOffset(offset) };
      }
      const key = targetKey(target);
      const pos = positionKey(next);
      setDrag((d) => {
        if (d && positionKey(d) === pos && targetKey(d.target) === key) return d;
        const same = d !== null && targetKey(d.target) === key && d.previewFor === pos;
        return {
          target,
          ...next,
          preview: same ? d.preview : null,
          previewFor: same ? d.previewFor : null,
        };
      });
      return;
    }
    if (p.onSide) return; // a side that cannot move: no pan either
    setView({ ...p.view, x: p.view.x - dx * k, y: p.view.y - dy * k });
  };

  const onPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    const p = pointer.current;
    pointer.current = null;
    if (!p) return;
    if (p.target && p.moved) {
      const d = drag;
      setDrag(null);
      if (d && isChange(d)) {
        // Reuse the live check when it matches the final position; otherwise check now.
        const known = d.previewFor === positionKey(d) && d.preview ? d.preview : undefined;
        void useEditStore.getState().apply(operationFor(d), known);
      }
      return;
    }
    if (p.moved || p.onSide) return; // a pan, or a side was chosen
    if (placingWall) {
      const d = hoverWall(placingWall, e.clientX, e.clientY);
      if (!isChange(d)) return; // not in a room: keep placing
      const before = index;
      const known = d.previewFor === positionKey(d) && d.preview ? d.preview : undefined;
      void useEditStore
        .getState()
        .apply(operationFor(d), known)
        .then((ok) => {
          if (!ok) return;
          const store = useEditStore.getState();
          store.setPlacingWall(null);
          // Select the new room, so it can be named and typed right away.
          const after = currentModelIndex();
          const added = store.changedIds.find(
            (id) => !before.elementsById.has(id) && after?.elementsById.get(id)?.type === "room",
          );
          if (added) select(added);
        });
      return;
    }
    if (placing) {
      const d = hoverPlacement(placing, e.clientX, e.clientY);
      if (!isChange(d)) return; // not on a wall: keep placing
      const before = index;
      const known = d.previewFor === positionKey(d) && d.preview ? d.preview : undefined;
      void useEditStore
        .getState()
        .apply(operationFor(d), known)
        .then((ok) => {
          if (!ok) return;
          const store = useEditStore.getState();
          store.setPlacing(null);
          // Select the new opening, so it can be adjusted right away.
          const added = store.changedIds.find((id) => !before.elementsById.has(id));
          if (added) select(added);
        });
      return;
    }
    // A click: the element under the pointer (pointer capture retargets the event).
    const hit = document
      .elementFromPoint(e.clientX, e.clientY)
      ?.closest<SVGElement>("[data-element-id]");
    select(hit?.dataset.elementId ?? null);
  };

  if (!drawing || !view) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-neutral-500">
        This model has no levels to draw.
      </div>
    );
  }

  const ghost =
    drag && (isChange(drag) || drag.target.kind === "new" || drag.target.kind === "newWall")
      ? drag
      : null;
  const ghostValid =
    ghost && isChange(ghost) && ghost.previewFor === positionKey(ghost)
      ? ghost.preview?.valid
      : undefined;

  return (
    <div className="relative h-full w-full bg-neutral-200 dark:bg-neutral-800">
      <svg
        ref={svgRef}
        role="img"
        aria-label={`${drawing.levelName} floor plan`}
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        className={
          "h-full w-full touch-none select-none bg-white" +
          (placing || placingWall ? " cursor-crosshair" : "")
        }
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => {
          pointer.current = null;
          setDrag(null);
        }}
        onPointerLeave={() => {
          if ((placing || placingWall) && !pointer.current) setDrag(null);
        }}
      >
        <style>{highlightCss(selectedId, editable)}</style>
        <g dangerouslySetInnerHTML={{ __html: content }} />
        {ghost && (
          <DragGhost
            drag={ghost}
            scale={drawing.scale}
            valid={ghostValid}
            thickness={level ? interiorThickness(index, level.id) : 0.12}
          />
        )}
        {!ghost && draft && !draft.preview.valid && draft.op.op === "resize_opening" && (
          <DraftGhost index={index} op={draft.op} scale={drawing.scale} />
        )}
        {facadeEdit && <RoofOutlines index={shownIndex} scale={drawing.scale} />}
        {selectedOpening && selectedHost && !ghost && !placing && !placingWall && (
          <OpeningGrips opening={selectedOpening} host={selectedHost} scale={drawing.scale} />
        )}
        {selectedRoom && !ghost && (
          <SideHandles
            sides={sides}
            chosen={chosenSide?.roomId === selectedRoom.id ? chosenSide.edge : null}
            scale={drawing.scale}
          />
        )}
      </svg>
      <div className="pointer-events-none absolute left-3 top-3 rounded-md bg-white/90 px-2 py-1 text-xs text-neutral-700 shadow-sm ring-1 ring-neutral-200">
        <span className="font-semibold">{drawing.levelName} plan</span> · drawn at 1:
        {drawing.scale} · dimensions in mm
      </div>
      {ghost && <DragStatus drag={ghost} valid={ghostValid} />}
      {editable && <PlanEditBar index={index} onSaved={onEditsSaved} />}
      <div className="absolute bottom-3 right-3 flex flex-col overflow-hidden rounded-md bg-white shadow ring-1 ring-neutral-200">
        <ZoomButton label="Zoom in" onClick={() => zoomAt(ZOOM_STEP)}>
          +
        </ZoomButton>
        <ZoomButton label="Zoom out" onClick={() => zoomAt(1 / ZOOM_STEP)}>
          −
        </ZoomButton>
        <ZoomButton label="Fit drawing" onClick={fit}>
          ⤢
        </ZoomButton>
      </div>
    </div>
  );
}

function svgPoints(pts: P2[], scale: number): string {
  return pts
    .map((p) => paperPoint(p, scale))
    .map(([x, y]) => `${fmt(x)},${fmt(y)}`)
    .join(" ");
}

/** Outline at the dragged position: blue while checking, green valid, red refused. */
function DragGhost({
  drag,
  scale,
  valid,
  thickness,
}: {
  drag: Drag;
  scale: number;
  valid: boolean | undefined;
  thickness: number;
}) {
  const color = valid === undefined ? "#2563eb" : valid ? "#16a34a" : "#dc2626";
  const t = drag.target;
  if (t.kind === "newWall") {
    if (!drag.line) return null;
    return (
      <polygon
        data-testid="wall-ghost"
        points={svgPoints(wallBody(drag.line, thickness), scale)}
        fill={color}
        fillOpacity={0.5}
        stroke={color}
        strokeWidth={0.35}
        pointerEvents="none"
      />
    );
  }
  if (t.kind === "opening" || t.kind === "new" || t.kind === "size") {
    if (!drag.wall) return null;
    return (
      <polygon
        data-testid="opening-ghost"
        points={svgPoints(openingOutline(drag.wall, drag.offset, widthOf(drag)), scale)}
        fill={color}
        fillOpacity={0.45}
        stroke={color}
        strokeWidth={0.35}
        pointerEvents="none"
      />
    );
  }
  if (t.kind === "wall") {
    return (
      <polygon
        points={svgPoints(movedWallOutline(t.wall, drag.offset), scale)}
        fill={color}
        fillOpacity={0.35}
        stroke={color}
        strokeWidth={0.35}
        strokeDasharray="1.5 1"
        pointerEvents="none"
      />
    );
  }
  const [ox, oy] = t.side.outward;
  const line: P2[] = [t.side.start, t.side.end].map((p): P2 => [
    p[0] + drag.offset * ox,
    p[1] + drag.offset * oy,
  ]);
  return (
    <g pointerEvents="none">
      <polygon
        points={svgPoints(movedSideOutline(t.room, t.side, drag.offset), scale)}
        fill={color}
        fillOpacity={0.08}
        stroke={color}
        strokeWidth={0.3}
        strokeDasharray="1.5 1"
      />
      <polyline points={svgPoints(line, scale)} fill="none" stroke={color} strokeWidth={0.8} />
    </g>
  );
}

/** Grips at both ends of the selected door or window: drag one to resize it along its wall. */
function OpeningGrips({ opening, host, scale }: { opening: Opening; host: Wall; scale: number }) {
  const x0 = opening.position.x;
  const x1 = x0 + opening.dimensions.width;
  const horizontal = Math.abs(Math.cos(host.rotation.z)) >= Math.abs(Math.sin(host.rotation.z));
  const ends: ["start" | "end", number][] = [
    ["start", x0],
    ["end", x1],
  ];
  return (
    <g aria-label={`Resize ${opening.name}`}>
      {ends.map(([end, u]) => {
        const [cx, cy] = paperPoint(wallPoint(host, u), scale);
        return (
          <g
            key={end}
            data-grip={end}
            data-testid={`opening-grip-${end}`}
            style={{ cursor: horizontal ? "ew-resize" : "ns-resize" }}
          >
            <circle cx={cx} cy={cy} r={SIDE_HIT_MM} fill="#000000" fillOpacity={0} />
            <rect
              x={cx - SIDE_GRIP_MM * 0.8}
              y={cy - SIDE_GRIP_MM * 0.8}
              width={SIDE_GRIP_MM * 1.6}
              height={SIDE_GRIP_MM * 1.6}
              fill="#ffffff"
              stroke="#2563eb"
              strokeWidth={0.35}
            />
          </g>
        );
      })}
    </g>
  );
}

/** Dashed eaves outline of the roofs, shown while a facade is edited (follows the preview). */
function RoofOutlines({ index, scale }: { index: ModelIndex; scale: number }) {
  return (
    <g data-testid="roof-outline" aria-label="Roof outline" pointerEvents="none">
      {roofOutlines(index).map((ring, i) => (
        <polygon
          key={i}
          points={svgPoints(ring, scale)}
          fill="none"
          stroke="#7c3aed"
          strokeWidth={0.35}
          strokeDasharray="3 1.5"
        />
      ))}
    </g>
  );
}

/** A size prepared in the properties panel that the server refused: its outline, in red. */
function DraftGhost({
  index,
  op,
  scale,
}: {
  index: ModelIndex;
  op: Extract<EditOperation, { op: "resize_opening" }>;
  scale: number;
}) {
  const opening = index.elementsById.get(op.opening_id);
  const host = opening ? index.hostOf.get(opening.id) : undefined;
  if (!isOpening(opening) || !host) return null;
  const [offset, width] = resizedOpening(opening, host, op.width_m, op.offset_m);
  return (
    <polygon
      data-testid="draft-ghost"
      points={svgPoints(openingOutline(host, offset, width), scale)}
      fill="#dc2626"
      fillOpacity={0.45}
      stroke="#dc2626"
      strokeWidth={0.35}
      pointerEvents="none"
    />
  );
}

/** Handles on the sides of the selected room; movable sides are blue, the chosen one filled. */
function SideHandles({
  sides,
  chosen,
  scale,
}: {
  sides: RoomSide[];
  chosen: number | null;
  scale: number;
}) {
  return (
    <g aria-label="Room sides">
      {sides.map((side) => {
        const [x0, y0] = paperPoint(side.start, scale);
        const [x1, y1] = paperPoint(side.end, scale);
        const movable = side.resizable;
        const color = movable ? "#2563eb" : "#a3a3a3";
        const horizontal = Math.abs(side.outward[1]) > Math.abs(side.outward[0]);
        return (
          <g
            key={side.index}
            data-side={side.index}
            style={{ cursor: movable ? (horizontal ? "ns-resize" : "ew-resize") : "not-allowed" }}
          >
            <line
              x1={x0}
              y1={y0}
              x2={x1}
              y2={y1}
              stroke="#000000"
              strokeOpacity={0}
              strokeWidth={SIDE_HIT_MM}
            />
            {side.index === chosen && (
              <line x1={x0} y1={y0} x2={x1} y2={y1} stroke={color} strokeWidth={0.6} />
            )}
            <circle
              cx={(x0 + x1) / 2}
              cy={(y0 + y1) / 2}
              r={SIDE_GRIP_MM}
              fill={side.index === chosen ? color : "#ffffff"}
              stroke={color}
              strokeWidth={0.35}
            />
          </g>
        );
      })}
    </g>
  );
}

function DragStatus({ drag, valid }: { drag: Drag; valid: boolean | undefined }) {
  const reason = valid === false ? drag.preview?.rejection?.message : null;
  const t = drag.target;
  if (t.kind === "newWall") {
    const length = drag.line
      ? Math.hypot(drag.line[1][0] - drag.line[0][0], drag.line[1][1] - drag.line[0][1])
      : 0;
    return (
      <div
        role="status"
        aria-live="polite"
        className={
          "pointer-events-none absolute bottom-3 left-1/2 max-w-[min(80%,560px)] -translate-x-1/2 rounded-md px-3 py-1.5 text-xs shadow ring-1 " +
          (valid === false
            ? "bg-red-50 text-red-800 ring-red-200"
            : valid
              ? "bg-green-50 text-green-800 ring-green-200"
              : "bg-white text-neutral-700 ring-neutral-200")
        }
      >
        <span className="font-semibold">New wall</span>
        {drag.room && drag.line
          ? ` across ${drag.room.name} · ${length.toFixed(2)} m`
          : " · point inside a room · Esc to stop"}
        {isChange(drag) && valid === undefined && " · checking…"}
        {valid && " · valid — click to place"}
        {reason && <> · {reason}</>}
      </div>
    );
  }
  if (t.kind === "opening" || t.kind === "new" || t.kind === "size") {
    return <OpeningStatus drag={drag} valid={valid} reason={reason ?? null} />;
  }
  const signed = `${drag.offset > 0 ? "+" : ""}${drag.offset.toFixed(2)} m`;
  let detail: string | null = null;
  if (t.kind === "side" && valid && drag.preview?.model) {
    // Area and extent of the room in the model the server returned for this position.
    try {
      const after = parseBuildingModel(drag.preview.model).elementsById.get(t.room.id);
      if (after?.type === "room") {
        const { width, depth } = roomExtent(after);
        detail =
          `${after.dimensions.area.toFixed(1)} m² (was ${t.room.dimensions.area.toFixed(1)})` +
          ` · ${width.toFixed(2)} × ${depth.toFixed(2)} m`;
      }
    } catch {
      detail = null;
    }
  }
  return (
    <div
      role="status"
      aria-live="polite"
      className={
        "pointer-events-none absolute bottom-3 left-1/2 max-w-[min(80%,560px)] -translate-x-1/2 rounded-md px-3 py-1.5 text-xs shadow ring-1 " +
        (valid === false
          ? "bg-red-50 text-red-800 ring-red-200"
          : valid
            ? "bg-green-50 text-green-800 ring-green-200"
            : "bg-white text-neutral-700 ring-neutral-200")
      }
    >
      <span className="font-semibold">
        {t.kind === "wall" ? t.wall.name : `${t.room.name} · ${t.side.compass} side`} {signed}
      </span>
      {valid === undefined && " · checking…"}
      {valid && (detail ? ` · ${detail} · release to apply` : " · valid — release to apply")}
      {reason && <> · {reason}</>}
    </div>
  );
}

/** Where the opening would go: its wall and the solid wall left on each side of it. */
function OpeningStatus({
  drag,
  valid,
  reason,
}: {
  drag: Drag;
  valid: boolean | undefined;
  reason: string | null;
}) {
  const t = drag.target;
  const width = widthOf(drag);
  const name =
    t.kind === "opening"
      ? t.opening.name
      : t.kind === "size"
        ? `${t.opening.name} ${width.toFixed(2)} × ${t.opening.dimensions.height.toFixed(2)} m` +
          ` (was ${t.opening.dimensions.width.toFixed(2)} m wide)`
        : `New ${t.kind === "new" ? t.spec.kind : "door"} ${width.toFixed(2)} m`;
  let where = "point at a wall to place it · Esc to stop";
  if (drag.wall) {
    const [before, after] = wallMargins(drag.wall, drag.offset, width);
    where =
      `${drag.wall.name} · ${before.toFixed(2)} m from its start · ` +
      `${after.toFixed(2)} m to its end`;
  }
  return (
    <div
      role="status"
      aria-live="polite"
      className={
        "pointer-events-none absolute bottom-3 left-1/2 max-w-[min(80%,560px)] -translate-x-1/2 rounded-md px-3 py-1.5 text-xs shadow ring-1 " +
        (valid === false
          ? "bg-red-50 text-red-800 ring-red-200"
          : valid
            ? "bg-green-50 text-green-800 ring-green-200"
            : "bg-white text-neutral-700 ring-neutral-200")
      }
    >
      <span className="font-semibold">{name}</span> · {where}
      {isChange(drag) && valid === undefined && " · checking…"}
      {valid && ` · valid — ${t.kind === "new" ? "click to place" : "release to apply"}`}
      {reason && <> · {reason}</>}
    </div>
  );
}

function ZoomButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="h-8 w-8 border-b border-neutral-200 text-base text-neutral-700 last:border-b-0 hover:bg-neutral-100"
    >
      {children}
    </button>
  );
}
