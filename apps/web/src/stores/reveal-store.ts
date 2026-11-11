// View state of the build reveal (viewer/reveal). Wraps the pure state machine; never stored
// with the model.
import { create } from "zustand";

import {
  INITIAL_REVEAL,
  reduceReveal,
  type RevealEvent,
  type RevealMode,
  type RevealState,
} from "@/viewer/reveal/machine";
import { REVEAL } from "@/viewer/render-settings";

/** The user asked the system for less motion (no matchMedia, e.g. in tests: not reduced). */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Until the viewer reports the length for the shown model (it depends on its size). */
const DEFAULT_DURATION: Record<RevealMode, number> = {
  build: REVEAL.schedule.maxDuration,
  changes: REVEAL.changes.duration,
};

interface RevealStore extends RevealState {
  /** PRNG key of the shown model (its model hash): the same model, the same pieces. */
  seed: string;
  /** Elements that re-assemble (mode "changes"). */
  changedIds: ReadonlySet<string>;
  /** Increments on every play, so a replay rebuilds the effect. */
  nonce: number;
  /** Paused at a fixed time (dev screenshots only). */
  frozen: boolean;
  /** Length of the assembly per mode (seconds), reported by the viewer for the shown model. */
  duration: Record<RevealMode, number>;
  dispatch: (event: RevealEvent) => void;
  setSeed: (seed: string) => void;
  setDuration: (mode: RevealMode, seconds: number) => void;
  /** Start the assembly of the shown model, or the re-assembly of `changedIds`. */
  play: (mode?: RevealMode, changedIds?: Iterable<string>) => void;
  freeze: (elapsed: number) => void;
}

const NONE: ReadonlySet<string> = new Set();

export const useRevealStore = create<RevealStore>()((set, get) => ({
  ...INITIAL_REVEAL,
  seed: "",
  changedIds: NONE,
  nonce: 0,
  frozen: false,
  duration: DEFAULT_DURATION,
  dispatch: (event) => {
    const s = get();
    const next = reduceReveal(s, event, {
      reducedMotion: prefersReducedMotion(),
      duration: s.duration,
    });
    if (next !== s) set(next);
  },
  setSeed: (seed) => set({ seed }),
  setDuration: (mode, seconds) => {
    if (seconds > 0 && get().duration[mode] !== seconds) {
      set((s) => ({ duration: { ...s.duration, [mode]: seconds } }));
    }
  },
  play: (mode = "build", changedIds) => {
    set({ changedIds: changedIds ? new Set(changedIds) : NONE, frozen: false });
    get().dispatch({ type: "model", mode });
    set((s) => ({ nonce: s.nonce + 1 }));
  },
  freeze: (elapsed) => {
    set({ frozen: true });
    get().dispatch({ type: "seek", elapsed });
  },
}));
