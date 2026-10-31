import { create } from "zustand";

interface SelectionState {
  /** Id of the selected BuildingModel element (null = nothing selected). */
  selectedId: string | null;
  select: (id: string | null) => void;
}

export const useSelectionStore = create<SelectionState>()((set) => ({
  selectedId: null,
  select: (selectedId) => set({ selectedId }),
}));
