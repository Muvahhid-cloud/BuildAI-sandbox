// The build reveal as a pure state machine (no React, no three, no clock):
//
//   idle --wait--> gathering --model--> assembling --tick... / skip--> done
//
// "gathering" is the calm blueprint state while the backend works (each real stage change counts
// as one pulse), "assembling" the construction of the model from pieces. With reduced motion the
// machine never leaves idle for the waiting state and goes straight to done when the model
// arrives. How long an assembly takes depends on the model: the viewer reports it (options).

export type RevealPhase = "idle" | "gathering" | "assembling" | "done";
/** "build": the whole model assembles. "changes": only the changed elements re-assemble. */
export type RevealMode = "build" | "changes";

export interface RevealState {
  phase: RevealPhase;
  mode: RevealMode;
  /** Index of the backend's current stage while gathering (-1: none reported yet). */
  stageIndex: number;
  /** Number of real stage changes seen (the grid pulses once per change). */
  bursts: number;
  /** Seconds since the assembly started. */
  elapsed: number;
}

export type RevealEvent =
  /** The backend reports its stage (same index again = no burst). */
  | { type: "wait"; stageIndex: number }
  /** The model arrived (or a replay was asked for). */
  | { type: "model"; mode?: RevealMode }
  | { type: "tick"; dt: number }
  /** Jump to a time of the assembly (screenshots, tests). */
  | { type: "seek"; elapsed: number }
  | { type: "skip" }
  | { type: "reset" };

export interface RevealOptions {
  reducedMotion: boolean;
  /** Length of the assembly per mode (seconds). */
  duration: Record<RevealMode, number>;
}

export const INITIAL_REVEAL: RevealState = {
  phase: "idle",
  mode: "build",
  stageIndex: -1,
  bursts: 0,
  elapsed: 0,
};

export function reduceReveal(
  state: RevealState,
  event: RevealEvent,
  options: RevealOptions,
): RevealState {
  switch (event.type) {
    case "wait": {
      if (options.reducedMotion) return state;
      if (state.phase === "assembling") return state; // a running assembly is not interrupted
      if (state.phase === "gathering" && event.stageIndex === state.stageIndex) return state;
      const changed = state.phase === "gathering";
      return {
        ...state,
        phase: "gathering",
        mode: "build",
        stageIndex: event.stageIndex,
        bursts: changed ? state.bursts + 1 : state.phase === "gathering" ? state.bursts : 0,
        elapsed: 0,
      };
    }
    case "model": {
      const mode = event.mode ?? "build";
      if (options.reducedMotion) return { ...INITIAL_REVEAL, phase: "done", mode };
      return { ...state, phase: "assembling", mode, elapsed: 0 };
    }
    case "tick": {
      if (state.phase !== "assembling" || !(event.dt > 0)) return state;
      const elapsed = state.elapsed + event.dt;
      return elapsed >= options.duration[state.mode]
        ? { ...state, phase: "done", elapsed: options.duration[state.mode] }
        : { ...state, elapsed };
    }
    case "seek": {
      if (state.phase !== "assembling") return state;
      const elapsed = Math.min(Math.max(event.elapsed, 0), options.duration[state.mode]);
      return { ...state, elapsed };
    }
    case "skip":
      // Only the animation can be skipped; waiting for the backend cannot.
      return state.phase === "assembling"
        ? { ...state, phase: "done", elapsed: options.duration[state.mode] }
        : state;
    case "reset":
      return INITIAL_REVEAL;
  }
}
