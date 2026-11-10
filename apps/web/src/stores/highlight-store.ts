import { create } from "zustand";

/**
 * Elements to highlight as changed (Phase 5): the elements an AI modification preview touches, or
 * the elements a version comparison found changed. View state only — derived from the models.
 */
interface HighlightState {
  ids: ReadonlySet<string>;
  setIds: (ids: Iterable<string> | null) => void;
}

const EMPTY: ReadonlySet<string> = new Set();

export const useHighlightStore = create<HighlightState>()((set) => ({
  ids: EMPTY,
  setIds: (ids) => set({ ids: ids ? new Set(ids) : EMPTY }),
}));
