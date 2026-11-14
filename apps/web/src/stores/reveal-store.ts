// View state of the live creation and the construction (viewer/reveal). Wraps the pure state
// machine; never stored with the model.
import { create } from "zustand";

import {
  INITIAL_REVEAL,
  reduceReveal,
  type RevealEvent,
  type RevealMode,
  type RevealState,
} from "@/viewer/reveal/machine";
import type { Plot } from "@/viewer/reveal/waiting";
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
  /** Elements that grow again (mode "changes"). */
  changedIds: ReadonlySet<string>;
  /** Increments on every play, so a replay rebuilds the effect. */
  nonce: number;
  /** Paused at a fixed time (dev screenshots only). */
  frozen: boolean;
  /** While frozen: leave the camera where it is (dev close-ups of a frame). */
  cameraHeld: boolean;
  /** Length of the assembly per mode (seconds), reported by the viewer for the shown model. */
  duration: Record<RevealMode, number>;
  /** Plot outline shown while waiting, once the floor area is known (interim, display only). */
  plot: Plot | null;
  dispatch: (event: RevealEvent) => void;
  setSeed: (seed: string) => void;
  setDuration: (mode: RevealMode, seconds: number) => void;
  setPlot: (plot: Plot | null) => void;
  /**
   * Start the construction of the shown model, or the re-growth of `changedIds`.
   * `saved: false`: the model is the laid-out preview of a generation that still runs.
   */
  play: (mode?: RevealMode, changedIds?: Iterable<string>, saved?: boolean) => void;
  freeze: (elapsed: number, holdCamera?: boolean) => void;
}

const NONE: ReadonlySet<string> = new Set();

export const useRevealStore = create<RevealStore>()((set, get) => ({
  ...INITIAL_REVEAL,
  seed: "",
  changedIds: NONE,
  nonce: 0,
  frozen: false,
  cameraHeld: false,
  duration: DEFAULT_DURATION,
  plot: null,
  dispatch: (event) => {
    const s = get();
    const next = reduceReveal(s, event, {
      reducedMotion: prefersReducedMotion(),
      duration: s.duration,
      collapse: REVEAL.fail.fade,
    });
    if (next !== s) set(next);
  },
  setSeed: (seed) => set({ seed }),
  setDuration: (mode, seconds) => {
    if (seconds > 0 && get().duration[mode] !== seconds) {
      set((s) => ({ duration: { ...s.duration, [mode]: seconds } }));
    }
  },
  setPlot: (plot) => {
    const now = get().plot;
    if (now?.halfWidth !== plot?.halfWidth || now?.halfDepth !== plot?.halfDepth) set({ plot });
  },
  play: (mode = "build", changedIds, saved = true) => {
    set({ changedIds: changedIds ? new Set(changedIds) : NONE, frozen: false, cameraHeld: false });
    get().dispatch({ type: "model", mode, saved });
    set((s) => ({ nonce: s.nonce + 1 }));
  },
  freeze: (elapsed, holdCamera = false) => {
    set({ frozen: true, cameraHeld: holdCamera });
    get().dispatch({ type: "seek", elapsed });
  },
}));
