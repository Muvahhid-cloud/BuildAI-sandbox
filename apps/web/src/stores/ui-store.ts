// Editor chrome state (which side panels are open). Kept per browser in localStorage.
import { create } from "zustand";

const KEY = "buildai-editor-panels";

interface Panels {
  left: boolean;
  right: boolean;
}

function load(): Panels {
  try {
    const raw = window.localStorage.getItem(KEY);
    const value = raw ? (JSON.parse(raw) as Partial<Panels>) : {};
    return { left: value.left !== false, right: value.right !== false };
  } catch {
    return { left: true, right: true };
  }
}

function save(panels: Panels) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(panels));
  } catch {
    // Not persisted (private mode): the panels still toggle for this page view.
  }
}

interface UIState extends Panels {
  toggle: (side: keyof Panels) => void;
}

export const useUIStore = create<UIState>((set, get) => ({
  ...(typeof window === "undefined" ? { left: true, right: true } : load()),
  toggle: (side) => {
    const next = { left: get().left, right: get().right, [side]: !get()[side] };
    save(next);
    set(next);
  },
}));
