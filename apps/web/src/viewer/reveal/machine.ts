// The live creation of a design as a pure state machine (no React, no three, no clock):
//
//   idle --wait--> gathering --model--> assembling --tick... / skip--> done
//                      |                     |                          |
//                      +--------- fail ------+---------- fail ----------+--> collapsing --> idle
//
// "gathering": the canvas shows the ground and the drafting sheet while the backend works
// (each real stage change is one pulse; `facts` counts what the AI has stated so far).
// "assembling": the model is there — its plan draws itself, then it is built. A model can
// arrive before it is saved (`saved: false`: the laid-out preview); `saved` only records what
// the backend reported — skipping the animation never changes it. "collapsing": a later stage
// failed after the house was shown; it fades out. With reduced motion nothing animates: the
// machine goes straight to done when the model arrives.

export type RevealPhase = "idle" | "gathering" | "assembling" | "collapsing" | "done";
/** "build": the whole model is built. "changes": only the changed elements grow again. */
export type RevealMode = "build" | "changes";

export interface RevealState {
  phase: RevealPhase;
  mode: RevealMode;
  /** Index of the backend's current stage while gathering (-1: none reported yet). */
  stageIndex: number;
  /** Number of real stage changes seen (the sheet pulses once per change). */
  bursts: number;
  /** Number of facts the AI has stated so far (interim; display only). */
  facts: number;
  /** Seconds since the assembly (or the collapse) started. */
  elapsed: number;
  /** The shown model is a stored version (false: the laid-out preview, not saved yet). */
  saved: boolean;
}

export type RevealEvent =
  /** The backend reports its stage (same index again = no burst). */
  | { type: "wait"; stageIndex: number }
  /** The AI's answer states this many facts so far. */
  | { type: "facts"; count: number }
  /** The model arrived (or a replay was asked for). `saved: false` = the preview. */
  | { type: "model"; mode?: RevealMode; saved?: boolean }
  /** The backend saved the shown model as a version. */
  | { type: "saved" }
  /** The backend failed (any stage). */
  | { type: "fail" }
  | { type: "tick"; dt: number }
  /** Jump to a time of the assembly (screenshots, tests). */
  | { type: "seek"; elapsed: number }
  | { type: "skip" }
  | { type: "reset" };

export interface RevealOptions {
  reducedMotion: boolean;
  /** Length of the assembly per mode (seconds). */
  duration: Record<RevealMode, number>;
  /** Length of the fade after a failure (seconds). */
  collapse: number;
}

export const INITIAL_REVEAL: RevealState = {
  phase: "idle",
  mode: "build",
  stageIndex: -1,
  bursts: 0,
  facts: 0,
  elapsed: 0,
  saved: true,
};

export function reduceReveal(
  state: RevealState,
  event: RevealEvent,
  options: RevealOptions,
): RevealState {
  switch (event.type) {
    case "wait": {
      if (options.reducedMotion) return state;
      // A running assembly (or collapse) is not interrupted.
      if (state.phase === "assembling" || state.phase === "collapsing") return state;
      if (state.phase === "gathering" && event.stageIndex === state.stageIndex) return state;
      const changed = state.phase === "gathering";
      return {
        ...state,
        phase: "gathering",
        mode: "build",
        stageIndex: event.stageIndex,
        bursts: changed ? state.bursts + 1 : 0,
        facts: changed ? state.facts : 0,
        elapsed: 0,
        saved: false,
      };
    }
    case "facts":
      return state.phase === "gathering" && event.count !== state.facts
        ? { ...state, facts: event.count }
        : state;
    case "model": {
      const mode = event.mode ?? "build";
      const saved = event.saved ?? true;
      if (options.reducedMotion) return { ...INITIAL_REVEAL, phase: "done", mode, saved };
      return { ...state, phase: "assembling", mode, elapsed: 0, saved };
    }
    case "saved":
      return state.saved ? state : { ...state, saved: true };
    case "fail": {
      // Only a house that is shown but not saved fades out; a stored version stays.
      const shown = state.phase === "assembling" || state.phase === "done";
      if (shown && !state.saved && !options.reducedMotion) {
        return { ...state, phase: "collapsing", elapsed: 0 };
      }
      return shown && state.saved ? state : INITIAL_REVEAL;
    }
    case "tick": {
      if (!(event.dt > 0)) return state;
      if (state.phase === "collapsing") {
        const elapsed = state.elapsed + event.dt;
        return elapsed >= options.collapse ? INITIAL_REVEAL : { ...state, elapsed };
      }
      if (state.phase !== "assembling") return state;
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
      // Only the animation can be skipped: waiting for the backend cannot, and what the
      // backend has reported (`saved`, the stage) is left exactly as it is.
      return state.phase === "assembling"
        ? { ...state, phase: "done", elapsed: options.duration[state.mode] }
        : state;
    case "reset":
      return INITIAL_REVEAL;
  }
}

/** Where the continuous flow is, for the UI and tests. */
export type FlowStep =
  | "idle"
  /** The backend works; nothing is known yet. */
  | "waiting"
  /** The backend works; the AI has stated facts. */
  | "facts"
  /** The model is there: its ground-floor plan draws itself. */
  | "blueprint"
  | "construction"
  /** Built (or skipped), the backend has not saved it yet. */
  | "built"
  /** Built and stored as a version. */
  | "saved"
  /** A stage failed after the house was shown: it fades out. */
  | "failed";

/** `lead`: seconds of the assembly that belong to the blueprint (0 for "changes"). */
export function flowStep(state: RevealState, lead: number): FlowStep {
  switch (state.phase) {
    case "idle":
      return "idle";
    case "gathering":
      return state.facts > 0 ? "facts" : "waiting";
    case "assembling":
      return state.mode === "build" && state.elapsed < lead ? "blueprint" : "construction";
    case "collapsing":
      return "failed";
    case "done":
      return state.saved ? "saved" : "built";
  }
}
