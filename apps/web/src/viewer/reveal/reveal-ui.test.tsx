import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { prefersReducedMotion, useRevealStore } from "@/stores/reveal-store";

import { REVEAL } from "../render-settings";
import { WaitingBlueprint } from "./WaitingBlueprint";

function stubReducedMotion(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reduce && query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })),
  );
}

beforeEach(() => {
  useRevealStore.getState().dispatch({ type: "reset" });
  useRevealStore.getState().setDuration("build", REVEAL.schedule.maxDuration);
});
afterEach(() => vi.unstubAllGlobals());

describe("WaitingBlueprint", () => {
  it("shows the real stage label as a status, also without WebGL (no canvas)", () => {
    const { container, rerender } = render(
      <WaitingBlueprint label="Understanding your requirements" stageIndex={0} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Understanding your requirements…");
    expect(container.querySelector("canvas")).toBeNull(); // jsdom has no WebGL: text only
    rerender(<WaitingBlueprint label="Generating the layout" stageIndex={3} />);
    expect(screen.getByRole("status")).toHaveTextContent("Generating the layout…");
    expect(screen.queryByText(/%/)).toBeNull(); // never a percentage
  });
});

describe("reveal store", () => {
  it("plays, ticks to the end and can be replayed; the seed is the model hash", () => {
    stubReducedMotion(false);
    const store = useRevealStore.getState();
    store.setSeed("model-hash-abc");
    store.dispatch({ type: "wait", stageIndex: 0 });
    store.dispatch({ type: "wait", stageIndex: 2 });
    expect(useRevealStore.getState()).toMatchObject({ phase: "gathering", bursts: 1 });
    store.play();
    const nonce = useRevealStore.getState().nonce;
    expect(useRevealStore.getState()).toMatchObject({ phase: "assembling", mode: "build" });
    // The viewer reports how long this model's build takes; until then the longest is assumed.
    store.dispatch({ type: "tick", dt: REVEAL.schedule.minDuration });
    expect(useRevealStore.getState().phase).toBe("assembling");
    store.setDuration("build", 7);
    store.dispatch({ type: "tick", dt: 1.1 });
    expect(useRevealStore.getState().phase).toBe("done");
    store.play();
    expect(useRevealStore.getState().nonce).toBe(nonce + 1); // a replay rebuilds the effect
    expect(useRevealStore.getState()).toMatchObject({
      phase: "assembling",
      seed: "model-hash-abc",
    });
    store.dispatch({ type: "skip" });
    expect(useRevealStore.getState().phase).toBe("done");
  });

  it("re-assembles only the changed elements and for a shorter time", () => {
    stubReducedMotion(false);
    const store = useRevealStore.getState();
    store.play("changes", ["wall-1", "window-2"]);
    expect([...useRevealStore.getState().changedIds]).toEqual(["wall-1", "window-2"]);
    expect(REVEAL.changes.duration).toBeLessThan(REVEAL.schedule.minDuration / 2);
    store.dispatch({ type: "tick", dt: REVEAL.changes.duration });
    expect(useRevealStore.getState().phase).toBe("done");
  });

  it("is off with prefers-reduced-motion: no waiting animation, the model is shown at once", () => {
    stubReducedMotion(true);
    expect(prefersReducedMotion()).toBe(true);
    const store = useRevealStore.getState();
    store.dispatch({ type: "wait", stageIndex: 1 });
    expect(useRevealStore.getState().phase).toBe("idle");
    store.play();
    expect(useRevealStore.getState().phase).toBe("done");
  });

  it("freezes at a time for screenshots", () => {
    stubReducedMotion(false);
    const store = useRevealStore.getState();
    store.play();
    store.freeze(1.5);
    expect(useRevealStore.getState()).toMatchObject({ frozen: true, elapsed: 1.5 });
    store.play();
    expect(useRevealStore.getState().frozen).toBe(false);
  });
});
