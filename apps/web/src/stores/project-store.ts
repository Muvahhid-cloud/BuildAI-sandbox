import { create } from "zustand";

export interface EditorProject {
  /** null for the public demo (not a persisted project). */
  id: string | null;
  name: string;
  source: "demo" | "project";
  description: string;
}

interface ProjectState {
  project: EditorProject | null;
  setProject: (project: EditorProject | null) => void;
}

/** Which project the editor shows (metadata only; the model lives in the building store). */
export const useProjectStore = create<ProjectState>()((set) => ({
  project: null,
  setProject: (project) => set({ project }),
}));
