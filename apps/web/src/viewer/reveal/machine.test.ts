import { describe, expect, it } from "vitest";

import {
  type FlowStep,
  flowStep,
  INITIAL_REVEAL,
  reduceReveal,
  type RevealEvent,
  type RevealOptions,
  type RevealState,
} from "./machine";

const OPTIONS: RevealOptions = {
  reducedMotion: false,
  duration: { build: 8, changes: 2.4 },
  collapse: 0.7,
};
const LEAD = 1.1;

function run(events: RevealEvent[], options = OPTIONS, from = INITIAL_REVEAL): RevealState {
  return events.reduce((state, event) => reduceReveal(state, event, options), from);
}

describe("continuous flow: waiting -> facts -> blueprint -> construction -> saved", () => {
  it("follows the backend through one unbroken sequence", () => {
    const seen: FlowStep[] = [];
    let state = INITIAL_REVEAL;
    const send = (event: RevealEvent) => {
      state = reduceReveal(state, event, OPTIONS);
      const step = flowStep(state, LEAD);
      if (seen[seen.length - 1] !== step) seen.push(step);
    };
    expect(flowStep(state, LEAD)).toBe("idle");
    send({ type: "wait", stageIndex: 0 }); // interpreting
    send({ type: "facts", count: 2 }); // the AI's answer is being written
    send({ type: "facts", count: 6 });
    send({ type: "wait", stageIndex: 1 }); // validating
    send({ type: "wait", stageIndex: 3 }); // layout
    expect(state).toMatchObject({ phase: "gathering", bursts: 2, facts: 6, saved: false });
    send({ type: "model", saved: false }); // the laid-out preview arrives during "checking"
    expect(state).toMatchObject({ phase: "assembling", elapsed: 0, saved: false });
    send({ type: "tick", dt: 0.5 });
    send({ type: "tick", dt: 1 }); // the plan is drawn: construction
    send({ type: "saved" }); // the backend saved it while the house is being built
    expect(state).toMatchObject({ phase: "assembling", elapsed: 1.5, saved: true }); // no restart
    send({ type: "tick", dt: 10 });
    expect(seen).toEqual(["waiting", "facts", "blueprint", "construction", "saved"]);
    expect(state).toMatchObject({ phase: "done", elapsed: 8 });
  });

  it("stays 'built' (not saved) when the construction ends before the backend has saved", () => {
    const state = run([
      { type: "wait", stageIndex: 3 },
      { type: "model", saved: false },
      { type: "tick", dt: 9 },
    ]);
    expect(flowStep(state, LEAD)).toBe("built");
    expect(flowStep(reduceReveal(state, { type: "saved" }, OPTIONS), LEAD)).toBe("saved");
  });

  it("counts a real stage change as one pulse and ignores repeats; facts only while waiting", () => {
    const state = run([
      { type: "wait", stageIndex: 0 },
      { type: "wait", stageIndex: 0 },
      { type: "wait", stageIndex: 1 },
    ]);
    expect(state).toMatchObject({ phase: "gathering", stageIndex: 1, bursts: 1 });
    const same = reduceReveal(state, { type: "facts", count: 0 }, OPTIONS);
    expect(same).toBe(state);
    const building = run([{ type: "model" }, { type: "facts", count: 4 }], OPTIONS, state);
    expect(building.facts).toBe(0);
    // A new creation starts from nothing.
    const again = run([{ type: "reset" }, { type: "wait", stageIndex: 0 }], OPTIONS, building);
    expect(again).toMatchObject({ bursts: 0, facts: 0, saved: false });
  });
});

describe("skip", () => {
  it("ends the animation at once and touches nothing the backend reported", () => {
    const building = run([
      { type: "wait", stageIndex: 4 },
      { type: "model", saved: false },
      { type: "tick", dt: 2 },
    ]);
    const skipped = reduceReveal(building, { type: "skip" }, OPTIONS);
    expect(skipped).toMatchObject({ phase: "done", elapsed: 8, saved: false, stageIndex: 4 });
    expect(flowStep(skipped, LEAD)).toBe("built"); // never marked saved early
    // The real save still arrives afterwards.
    expect(reduceReveal(skipped, { type: "saved" }, OPTIONS).saved).toBe(true);
  });

  it("cannot skip waiting for the backend, and does nothing when nothing runs", () => {
    const waiting = run([{ type: "wait", stageIndex: 2 }]);
    expect(reduceReveal(waiting, { type: "skip" }, OPTIONS)).toBe(waiting);
    expect(reduceReveal(INITIAL_REVEAL, { type: "skip" }, OPTIONS)).toBe(INITIAL_REVEAL);
  });
});

describe("failure", () => {
  it("while waiting: back to idle (the real error is shown by the panel)", () => {
    const state = run([{ type: "wait", stageIndex: 1 }, { type: "fail" }]);
    expect(state).toEqual(INITIAL_REVEAL);
  });

  it("after the house was shown: the construction stops, it fades out, then idle", () => {
    const building = run([
      { type: "wait", stageIndex: 3 },
      { type: "model", saved: false },
      { type: "tick", dt: 3 },
    ]);
    const failed = reduceReveal(building, { type: "fail" }, OPTIONS);
    expect(failed).toMatchObject({ phase: "collapsing", elapsed: 0 });
    expect(flowStep(failed, LEAD)).toBe("failed");
    // The construction no longer advances, and cannot be skipped into "done".
    expect(reduceReveal(failed, { type: "skip" }, OPTIONS)).toBe(failed);
    expect(reduceReveal(failed, { type: "wait", stageIndex: 4 }, OPTIONS)).toBe(failed);
    const fading = reduceReveal(failed, { type: "tick", dt: 0.3 }, OPTIONS);
    expect(fading).toMatchObject({ phase: "collapsing", elapsed: 0.3 });
    expect(reduceReveal(fading, { type: "tick", dt: 0.5 }, OPTIONS)).toEqual(INITIAL_REVEAL);
  });

  it("also after a skipped or finished construction that was not saved yet", () => {
    const built = run([{ type: "model", saved: false }, { type: "skip" }]);
    expect(reduceReveal(built, { type: "fail" }, OPTIONS).phase).toBe("collapsing");
  });

  it("never takes away a stored version", () => {
    const saved = run([
      { type: "model", saved: false },
      { type: "saved" },
      { type: "tick", dt: 1 },
    ]);
    expect(reduceReveal(saved, { type: "fail" }, OPTIONS)).toBe(saved);
    const replay = run([{ type: "model" }]);
    expect(reduceReveal(replay, { type: "fail" }, OPTIONS)).toBe(replay);
  });
});

describe("replay, changes, seek", () => {
  it("replays the build of the shown (saved) model from the start", () => {
    const done = run([{ type: "model" }, { type: "tick", dt: 9 }]);
    expect(done.phase).toBe("done");
    const replay = reduceReveal(done, { type: "model" }, OPTIONS);
    expect(replay).toMatchObject({ phase: "assembling", mode: "build", elapsed: 0, saved: true });
  });

  it("grows changed elements in the short mode, without a blueprint step", () => {
    const state = run([{ type: "model", mode: "changes" }]);
    expect(flowStep(state, 0)).toBe("construction");
    expect(run([{ type: "tick", dt: 2.4 }], OPTIONS, state).phase).toBe("done");
  });

  it("takes the length of the build from the options (it depends on the model)", () => {
    const short = { ...OPTIONS, duration: { build: 6.2, changes: 2.4 } };
    expect(run([{ type: "model" }, { type: "tick", dt: 6.1 }], short).phase).toBe("assembling");
    expect(run([{ type: "model" }, { type: "tick", dt: 6.3 }], short).phase).toBe("done");
  });

  it("seeks inside the assembly only, clamped", () => {
    const state = run([{ type: "model" }, { type: "seek", elapsed: 3 }]);
    expect(state.elapsed).toBe(3);
    expect(run([{ type: "seek", elapsed: 99 }], OPTIONS, state).elapsed).toBe(8);
    expect(reduceReveal(INITIAL_REVEAL, { type: "seek", elapsed: 2 }, OPTIONS)).toBe(
      INITIAL_REVEAL,
    );
    expect(reduceReveal(state, { type: "tick", dt: 0 }, OPTIONS)).toBe(state);
  });
});

describe("reduced motion", () => {
  const reduced = { ...OPTIONS, reducedMotion: true };

  it("never animates: no waiting state, the finished model is shown directly", () => {
    const waiting = run([{ type: "wait", stageIndex: 0 }], reduced);
    expect(waiting).toBe(INITIAL_REVEAL);
    const shown = run([{ type: "model", saved: false }], reduced);
    expect(shown).toMatchObject({ phase: "done", saved: false });
    expect(flowStep(shown, LEAD)).toBe("built");
    expect(flowStep(reduceReveal(shown, { type: "saved" }, reduced), LEAD)).toBe("saved");
  });

  it("a failure removes the unsaved house without a fade", () => {
    const shown = run([{ type: "model", saved: false }], reduced);
    expect(reduceReveal(shown, { type: "fail" }, reduced)).toEqual(INITIAL_REVEAL);
  });
});
