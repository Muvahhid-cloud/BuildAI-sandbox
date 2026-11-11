import { describe, expect, it } from "vitest";

import { REVEAL } from "../render-settings";
import {
  INITIAL_REVEAL,
  reduceReveal,
  revealFrame,
  type RevealEvent,
  type RevealOptions,
  type RevealState,
} from "./machine";

const MOTION: RevealOptions = { reducedMotion: false, duration: { build: 3.6, sparkle: 1.6 } };
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

  it("counts one burst per real stage change, none for a repeated stage", () => {
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

  it("with reduced motion shows no cloud and finishes at once", () => {
    expect(run([{ type: "wait", stageIndex: 2 }], REDUCED)).toBe(INITIAL_REVEAL);
    expect(run([{ type: "model" }], REDUCED).phase).toBe("done");
    expect(run([{ type: "model", mode: "sparkle" }], REDUCED)).toMatchObject({
      phase: "done",
      mode: "sparkle",
    });
  });

  it("plays the shorter sparkle for changed elements", () => {
    const s = run([
      { type: "model", mode: "sparkle" },
      { type: "tick", dt: 1 },
    ]);
    expect(s).toMatchObject({ phase: "assembling", mode: "sparkle" });
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
});

describe("reveal timeline", () => {
  const t = {
    duration: REVEAL.duration,
    sweepStart: REVEAL.sweepStart,
    sweepEnd: REVEAL.sweepEnd,
    veilOpacity: REVEAL.veilOpacity,
  };

  it("keeps the model hidden and dark while the particles fly in", () => {
    const f = revealFrame(0.5, t, 0, 6);
    expect(f).toMatchObject({ sweep: 0, sweepZ: 0, veil: REVEAL.veilOpacity, particles: 1 });
  });

  it("sweeps bottom-up, lifting the veil, then fades the particles", () => {
    let last = -Infinity;
    for (let e = 0; e <= REVEAL.duration; e += 0.05) {
      const f = revealFrame(e, t, 0, 6);
      expect(f.sweepZ).toBeGreaterThanOrEqual(last); // never moves down
      last = f.sweepZ;
    }
    const mid = revealFrame((REVEAL.sweepStart + REVEAL.sweepEnd) / 2, t, 0, 6);
    expect(mid.sweepZ).toBeGreaterThan(1);
    expect(mid.sweepZ).toBeLessThan(6);
    expect(mid.veil).toBeLessThan(REVEAL.veilOpacity);
    const end = revealFrame(REVEAL.duration, t, 0, 6);
    expect(end.sweepZ).toBeGreaterThan(6); // above the top: nothing is clipped
    expect(end.veil).toBe(0);
    expect(end.particles).toBe(0);
  });

  it("stays within the time budget", () => {
    expect(REVEAL.duration).toBeGreaterThanOrEqual(3);
    expect(REVEAL.duration).toBeLessThanOrEqual(4);
    expect(REVEAL.sweepStart).toBeLessThan(REVEAL.sweepEnd);
    expect(REVEAL.sweepEnd).toBeLessThan(REVEAL.duration);
    // The top particles have landed before the sweep reaches them.
    expect(REVEAL.stagger + REVEAL.jitter + REVEAL.fly).toBeLessThanOrEqual(REVEAL.sweepEnd);
  });
});
