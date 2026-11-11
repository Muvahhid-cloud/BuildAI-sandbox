import { describe, expect, it } from "vitest";

import {
  INITIAL_REVEAL,
  reduceReveal,
  type RevealEvent,
  type RevealOptions,
  type RevealState,
} from "./machine";

const MOTION: RevealOptions = { reducedMotion: false, duration: { build: 3.6, changes: 1.6 } };
const REDUCED: RevealOptions = { ...MOTION, reducedMotion: true };

const run = (events: RevealEvent[], options = MOTION, from: RevealState = INITIAL_REVEAL) =>
  events.reduce((s, e) => reduceReveal(s, e, options), from);

describe("reveal state machine", () => {
  it("goes idle -> gathering -> assembling -> done", () => {
    let s = run([{ type: "wait", stageIndex: 0 }]);
    expect(s.phase).toBe("gathering");
    s = run([{ type: "model" }], MOTION, s);
    expect(s).toMatchObject({ phase: "assembling", mode: "build", elapsed: 0 });
    s = run(
      [
        { type: "tick", dt: 1 },
        { type: "tick", dt: 1 },
      ],
      MOTION,
      s,
    );
    expect(s).toMatchObject({ phase: "assembling", elapsed: 2 });
    s = run([{ type: "tick", dt: 2 }], MOTION, s);
    expect(s).toMatchObject({ phase: "done", elapsed: 3.6 });
    expect(run([{ type: "tick", dt: 1 }], MOTION, s)).toBe(s); // done stays done
  });

  it("counts one pulse per real stage change, none for a repeated stage", () => {
    const s = run([
      { type: "wait", stageIndex: 0 },
      { type: "wait", stageIndex: 0 },
      { type: "wait", stageIndex: 1 },
      { type: "wait", stageIndex: 3 },
      { type: "wait", stageIndex: 3 },
    ]);
    expect(s).toMatchObject({ phase: "gathering", stageIndex: 3, bursts: 2 });
    // A new wait after a finished reveal starts counting again.
    const again = run(
      [{ type: "model" }, { type: "skip" }, { type: "wait", stageIndex: 0 }],
      MOTION,
      s,
    );
    expect(again).toMatchObject({ phase: "gathering", bursts: 0 });
  });

  it("skips only a running assembly", () => {
    const gathering = run([{ type: "wait", stageIndex: 1 }]);
    expect(run([{ type: "skip" }], MOTION, gathering)).toBe(gathering); // the backend cannot be skipped
    expect(run([{ type: "skip" }])).toBe(INITIAL_REVEAL);
    const skipped = run([{ type: "model" }, { type: "tick", dt: 0.5 }, { type: "skip" }]);
    expect(skipped).toMatchObject({ phase: "done", elapsed: 3.6 });
  });

  it("with reduced motion shows no waiting animation and finishes at once", () => {
    expect(run([{ type: "wait", stageIndex: 2 }], REDUCED)).toBe(INITIAL_REVEAL);
    expect(run([{ type: "model" }], REDUCED).phase).toBe("done");
    expect(run([{ type: "model", mode: "changes" }], REDUCED)).toMatchObject({
      phase: "done",
      mode: "changes",
    });
  });

  it("plays the shorter re-assembly of changed elements", () => {
    const s = run([
      { type: "model", mode: "changes" },
      { type: "tick", dt: 1 },
    ]);
    expect(s).toMatchObject({ phase: "assembling", mode: "changes" });
    expect(run([{ type: "tick", dt: 0.7 }], MOTION, s).phase).toBe("done");
  });

  it("replays from done, is not interrupted by a late wait, seeks within bounds and resets", () => {
    const done = run([{ type: "model" }, { type: "skip" }]);
    const replay = run([{ type: "model" }], MOTION, done);
    expect(replay).toMatchObject({ phase: "assembling", elapsed: 0 });
    expect(run([{ type: "wait", stageIndex: 4 }], MOTION, replay)).toBe(replay);
    expect(run([{ type: "seek", elapsed: 1.5 }], MOTION, replay).elapsed).toBe(1.5);
    expect(run([{ type: "seek", elapsed: 99 }], MOTION, replay).elapsed).toBe(3.6);
    expect(run([{ type: "seek", elapsed: 1 }], MOTION, done)).toBe(done);
    expect(run([{ type: "tick", dt: -1 }], MOTION, replay)).toBe(replay);
    expect(run([{ type: "reset" }], MOTION, replay)).toBe(INITIAL_REVEAL);
  });

  it("takes the length of the assembly from the options (it depends on the model)", () => {
    const long: RevealOptions = { reducedMotion: false, duration: { build: 8, changes: 2 } };
    const s = run([{ type: "model" }, { type: "tick", dt: 5 }], long);
    expect(s).toMatchObject({ phase: "assembling", elapsed: 5 });
    expect(run([{ type: "tick", dt: 3 }], long, s)).toMatchObject({ phase: "done", elapsed: 8 });
    expect(run([{ type: "skip" }], long, s)).toMatchObject({ phase: "done", elapsed: 8 });
  });
});
