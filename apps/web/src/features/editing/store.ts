// The plan-editing session (docs/3d-engine.md §20): the operations made on one base version,
// with a cursor for undo/redo. Every state the user sees is a model the server built and
// validated from `ops.slice(0, cursor)`; the client never edits a model itself.
import { create } from "zustand";

import type { NewOpening } from "@/engine/drawing/opening-edit";
import { relocateSide, type RoomSide, roomSides } from "@/engine/drawing/room-edit";
import type { NewWall } from "@/engine/drawing/wall-add";
import type { ModelIndex } from "@/engine/model/model-index";
import { ApiError } from "@/lib/api/errors";
import type { EditOperation, EditPreview, EditRejection, Issue, Version } from "@/lib/api/schemas";
import { useBuildingStore } from "@/stores/building-store";

import { previewEdits, saveEdits } from "./api";

export interface EditMessage {
  tone: "error" | "warning" | "info";
  text: string;
  issues?: Issue[];
}

/** A prepared operation and the server's answer for it on top of the applied operations. */
export interface EditDraft {
  key: string;
  op: EditOperation;
  preview: EditPreview;
}

interface EditState {
  projectId: string | null;
  versionId: string | null;
  /** The base version's model (shown when no edit is applied). */
  baseModel: unknown;
  ops: EditOperation[];
  /** Number of operations applied; ops beyond it can be redone. */
  cursor: number;
  busy: boolean;
  message: EditMessage | null;
  /** Elements that differ from the base version (for highlighting). */
  changedIds: string[];
  /** The room side chosen for resizing (index into the room's boundary). */
  side: { roomId: string; edge: number } | null;
  /** A door or window being added: the next click on a wall in the plan places it. */
  placing: NewOpening | null;
  /** A wall being added: the next click inside a room on the plan places it. */
  placingWall: NewWall | null;
  /**
   * The server's answer for a change being prepared in a form (an opening's size, a wall to
   * remove, a room's type): the plan shows its model until it is applied or abandoned.
   */
  draft: EditDraft | null;

  begin: (projectId: string, version: Pick<Version, "id" | "model">) => void;
  end: () => void;
  /** Validate `op` on top of the applied operations; apply it if the server accepts it. */
  apply: (op: EditOperation, preview?: EditPreview) => Promise<boolean>;
  /** Check `op` on top of the applied operations without applying it (live preview). */
  check: (op: EditOperation, signal?: AbortSignal) => Promise<EditPreview>;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  discard: () => void;
  save: (label?: string) => Promise<Version | null>;
  dismissMessage: () => void;
  chooseSide: (side: { roomId: string; edge: number } | null) => void;
  setPlacing: (placing: NewOpening | null) => void;
  setPlacingWall: (placingWall: NewWall | null) => void;
  setDraft: (draft: EditDraft | null) => void;
}

function rejectionMessage(r: EditRejection | null): EditMessage {
  return {
    tone: "error",
    text: r?.message ?? "This change is not possible.",
    issues: r?.issues,
  };
}

function errorMessage(err: unknown): EditMessage {
  return {
    tone: "error",
    text:
      err instanceof ApiError
        ? err.message
        : "The change could not be checked. Is the server running?",
  };
}

function sideOf(index: ModelIndex, roomId: string, edge: number): RoomSide | null {
  const room = index.elementsById.get(roomId);
  return room?.type === "room" ? (roomSides(index, room)[edge] ?? null) : null;
}

const EMPTY = {
  projectId: null,
  versionId: null,
  baseModel: null,
  ops: [] as EditOperation[],
  cursor: 0,
  busy: false,
  message: null,
  changedIds: [] as string[],
  side: null as { roomId: string; edge: number } | null,
  placing: null as NewOpening | null,
  placingWall: null as NewWall | null,
  draft: null as EditDraft | null,
};

export const useEditStore = create<EditState>()((set, get) => {
  /** Show the model of `ops.slice(0, cursor)` (re-validated by the server). */
  async function show(cursor: number): Promise<void> {
    const { projectId, versionId, ops, baseModel } = get();
    if (!projectId || !versionId) return;
    // Side numbers belong to one outline; after undo/redo the side is chosen again.
    if (cursor === 0) {
      useBuildingStore.getState().load(baseModel);
      set({ cursor, changedIds: [], message: null, side: null, draft: null });
      return;
    }
    set({ busy: true });
    try {
      const preview = await previewEdits(projectId, versionId, ops.slice(0, cursor));
      if (!preview.valid || preview.model === null) {
        set({ busy: false, message: rejectionMessage(preview.rejection) });
        return;
      }
      useBuildingStore.getState().load(preview.model);
      set({
        cursor,
        busy: false,
        changedIds: preview.changed_ids,
        message: null,
        side: null,
        draft: null,
      });
    } catch (err) {
      set({ busy: false, message: errorMessage(err) });
    }
  }

  return {
    ...EMPTY,

    begin: (projectId, version) => {
      const s = get();
      if (s.projectId === projectId && s.versionId === version.id) return;
      set({ ...EMPTY, projectId, versionId: version.id, baseModel: version.model });
    },

    end: () => set({ ...EMPTY }),

    check: (op, signal) => {
      const { projectId, versionId, ops, cursor } = get();
      if (!projectId || !versionId) return Promise.reject(new Error("No editing session"));
      return previewEdits(projectId, versionId, [...ops.slice(0, cursor), op], signal);
    },

    apply: async (op, known) => {
      const { projectId, versionId, ops, cursor } = get();
      if (!projectId || !versionId) return false;
      set({ busy: true, message: null });
      try {
        const preview = known ?? (await get().check(op));
        if (!preview.valid || preview.model === null) {
          set({ busy: false, message: rejectionMessage(preview.rejection) });
          return false;
        }
        // A resized side keeps its place in the session after its outline changed.
        const before = useBuildingStore.getState().index;
        const movedSide =
          op.op === "resize_room" && before ? sideOf(before, op.room_id, op.edge) : null;
        useBuildingStore.getState().load(preview.model);
        const after = useBuildingStore.getState().index;
        const side =
          op.op === "resize_room" && movedSide && after
            ? relocateSide(after, op.room_id, movedSide, op.delta_m)
            : null;
        const warnings = preview.warnings;
        set({
          ops: [...ops.slice(0, cursor), op],
          cursor: cursor + 1,
          busy: false,
          changedIds: preview.changed_ids,
          draft: null,
          ...(op.op === "resize_room"
            ? { side: side === null ? null : { roomId: op.room_id, edge: side } }
            : {}),
          message:
            warnings.length > 0
              ? { tone: "warning", text: "Applied, with notes to review.", issues: warnings }
              : null,
        });
        return true;
      } catch (err) {
        set({ busy: false, message: errorMessage(err) });
        return false;
      }
    },

    undo: async () => {
      const { cursor, busy } = get();
      if (cursor > 0 && !busy) await show(cursor - 1);
    },

    redo: async () => {
      const { cursor, ops, busy } = get();
      if (cursor < ops.length && !busy) await show(cursor + 1);
    },

    discard: () => {
      const { baseModel } = get();
      useBuildingStore.getState().load(baseModel);
      set({ ops: [], cursor: 0, changedIds: [], message: null, side: null, draft: null });
    },

    save: async (label) => {
      const { projectId, versionId, ops, cursor } = get();
      if (!projectId || !versionId || cursor === 0) return null;
      set({ busy: true, message: null });
      try {
        const version = await saveEdits(projectId, versionId, ops.slice(0, cursor), label);
        set({ ...EMPTY });
        return version;
      } catch (err) {
        set({ busy: false, message: errorMessage(err) });
        return null;
      }
    },

    dismissMessage: () => set({ message: null }),

    chooseSide: (side) => set({ side }),

    // Adding a door/window and adding a wall exclude each other.
    setPlacing: (placing) => set(placing ? { placing, placingWall: null } : { placing }),

    setPlacingWall: (placingWall) =>
      set(placingWall ? { placingWall, placing: null } : { placingWall }),

    setDraft: (draft) => set({ draft }),
  };
});

/** Whether the session has applied edits that are not saved yet. */
export function hasUnsavedEdits(s: Pick<EditState, "cursor">): boolean {
  return s.cursor > 0;
}
