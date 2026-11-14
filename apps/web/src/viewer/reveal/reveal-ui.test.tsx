import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  BackSide,
  Group,
  type Material,
  Mesh,
  MeshStandardMaterial,
  Raycaster,
  Vector3,
} from "three";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { prefersReducedMotion, useRevealStore } from "@/stores/reveal-store";

import { materialCache } from "@/engine/materials/material-cache";
import { buildScene } from "@/engine/scene/build-scene";
import { demoIndex } from "@/engine/test-fixtures";

import { REVEAL } from "../render-settings";
import { createGrowth, createObjectGrowth, materialHex } from "./growth";
import { RevealSurface } from "./RevealSurface";
import { plotFor, waitingBounds, waitingPose } from "./waiting";

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

describe("RevealSurface: any interaction ends the construction, the camera is the user's", () => {
  function surface(onInner: Record<string, () => void> = {}) {
    render(
      <RevealSurface>
        <div
          data-testid="canvas"
          onPointerDown={onInner.pointerDown}
          onWheel={onInner.wheel}
          onClick={onInner.click}
        />
      </RevealSurface>,
    );
    return screen.getByTestId("canvas");
  }
  const start = (saved = true) => {
    stubReducedMotion(false);
    useRevealStore.getState().play("build", undefined, saved);
    expect(useRevealStore.getState().phase).toBe("assembling");
  };

  it("a pointer-down (the start of a drag) skips and still reaches the orbit controls", () => {
    const pointerDown = vi.fn();
    const canvas = surface({ pointerDown });
    act(() => start());
    expect(screen.getByRole("note")).toHaveTextContent(/skip the build animation/i);
    fireEvent.pointerDown(canvas);
    expect(useRevealStore.getState().phase).toBe("done");
    expect(pointerDown).toHaveBeenCalledTimes(1); // the same gesture orbits: controls are live
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("the wheel skips and still zooms", () => {
    const wheel = vi.fn();
    const canvas = surface({ wheel });
    act(() => start());
    fireEvent.wheel(canvas);
    expect(useRevealStore.getState().phase).toBe("done");
    expect(wheel).toHaveBeenCalledTimes(1);
  });

  it("a click skips without also selecting what is under the pointer; later clicks select", () => {
    const click = vi.fn();
    const canvas = surface({ click });
    act(() => start());
    fireEvent.pointerDown(canvas);
    fireEvent.click(canvas); // the click of the gesture that skipped
    expect(useRevealStore.getState().phase).toBe("done");
    expect(click).not.toHaveBeenCalled();
    fireEvent.pointerDown(canvas);
    fireEvent.click(canvas);
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("Esc skips; outside a construction nothing is intercepted", () => {
    const click = vi.fn();
    const canvas = surface({ click });
    act(() => start());
    fireEvent.keyDown(window, { key: "Escape" });
    expect(useRevealStore.getState().phase).toBe("done");
    fireEvent.click(canvas);
    expect(click).toHaveBeenCalledTimes(1);
    // Waiting for the backend cannot be skipped.
    act(() => {
      useRevealStore.getState().dispatch({ type: "reset" });
      useRevealStore.getState().dispatch({ type: "wait", stageIndex: 0 });
    });
    fireEvent.pointerDown(canvas);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(useRevealStore.getState().phase).toBe("gathering");
  });

  it("skipping never marks anything the backend has not reported", () => {
    const canvas = surface();
    act(() => {
      stubReducedMotion(false);
      useRevealStore.getState().dispatch({ type: "wait", stageIndex: 3 });
      useRevealStore.getState().play("build", undefined, false); // the laid-out preview
    });
    fireEvent.pointerDown(canvas);
    expect(useRevealStore.getState()).toMatchObject({ phase: "done", saved: false, stageIndex: 3 });
  });

  it("fades the canvas out when a stage fails after the house was shown, then is idle", () => {
    vi.useFakeTimers();
    const canvas = surface();
    act(() => start(false));
    const veil = canvas.parentElement!;
    expect(veil.style.opacity).toBe("1");
    act(() => useRevealStore.getState().dispatch({ type: "fail" }));
    expect(useRevealStore.getState().phase).toBe("collapsing");
    expect(veil.style.opacity).toBe("0");
    act(() => vi.advanceTimersByTime(REVEAL.fail.fade * 1000 + 20));
    expect(useRevealStore.getState().phase).toBe("idle");
    expect(veil.style.opacity).toBe("1");
    vi.useRealTimers();
  });
});

describe("waiting view", () => {
  it("sizes the plot from the stated floor area and storeys; nothing before it is known", () => {
    const cfg = REVEAL.waiting;
    expect(plotFor(null, 2, cfg)).toBeNull();
    const one = plotFor(140, null, cfg)!;
    const two = plotFor(280, 2, cfg)!;
    expect(two).toEqual(one); // 280 m² over two floors = the footprint of 140 m²
    const width = (one.halfWidth - cfg.plotMargin) * 2;
    const depth = (one.halfDepth - cfg.plotMargin) * 2;
    expect(width * depth).toBeCloseTo(140);
    expect(width / depth).toBeCloseTo(cfg.plotAspect);
    expect(plotFor(600, 1, cfg)!.halfWidth).toBeGreaterThan(one.halfWidth);
  });

  it("frames the empty site from above the ground, looking at it", () => {
    const bounds = waitingBounds(REVEAL.waiting.bounds);
    const pose = waitingPose(bounds);
    expect(pose.position.z).toBeGreaterThan(5);
    expect(pose.target.x).toBeCloseTo(REVEAL.waiting.bounds.width / 2);
    expect(pose.target.z).toBeLessThan(1);
  });

  it("keeps the plot in the store only as a display hint", () => {
    const store = useRevealStore.getState();
    store.setPlot({ halfWidth: 9, halfDepth: 7 });
    const first = useRevealStore.getState().plot;
    store.setPlot({ halfWidth: 9, halfDepth: 7 });
    expect(useRevealStore.getState().plot).toBe(first); // unchanged: no re-render
    store.setPlot(null);
    expect(useRevealStore.getState().plot).toBeNull();
  });
});

describe("growing stand-ins (growth.ts)", () => {
  const scene = buildScene(demoIndex());
  const wall = scene.index.model.elements.find((e) => e.type === "wall")!;
  const parts = scene.byElement.get(wall.id)!;

  it("clips copies of the real materials at a rising horizontal plane, shadow included", () => {
    const growth = createGrowth(parts);
    expect(growth.space).toBe("model");
    const meshes = growth.object.children as Mesh[];
    const body = meshes[0]!;
    const materials = (
      Array.isArray(body.material) ? body.material : [body.material]
    ) as Material[];
    materials.forEach((m, i) => {
      const real = materialCache.get(parts[0]!.materials[i]!);
      expect(m).not.toBe(real); // the cached material is never touched
      expect(real.clippingPlanes ?? null).toBeNull();
      expect((m as MeshStandardMaterial).roughness).toBe(real.roughness); // same PBR look
      expect((m as MeshStandardMaterial).color.equals(real.color)).toBe(true);
      expect(m.clipShadows).toBe(true); // the shadow grows with the element
      const plane = m.clippingPlanes![0]!;
      expect(plane.normal.toArray()).toEqual([0, -1, 0]); // world up = model z: bottom to top
    });
    expect(body.geometry).toBe(parts[0]!.geometry); // the element's real mesh
    growth.setFront(1.25, 0.1);
    expect(materials[0]!.clippingPlanes![0]!.constant).toBe(1.25);
    growth.setFront(2.5, 0);
    expect(materials[0]!.clippingPlanes![0]!.constant).toBe(2.5);
    growth.dispose();
  });

  it("closes the cut: a back-face section in the material's colour, never pickable", () => {
    const growth = createGrowth(parts);
    const meshes = growth.object.children as Mesh[];
    expect(meshes.length).toBe(parts.length * 2);
    const cap = meshes[1]!;
    const capMaterial = (Array.isArray(cap.material) ? cap.material[0] : cap.material) as
      MeshStandardMaterial | undefined;
    expect(capMaterial!.side).toBe(BackSide);
    expect(`#${capMaterial!.color.getHexString()}`).toBe(
      materialHex(parts[0]!.materials[0]!).toLowerCase(),
    );
    expect(cap.castShadow).toBe(false);
    for (const mesh of meshes) {
      expect(mesh.userData).toEqual({}); // no elementId: the real mesh keeps the mapping
      const hits: unknown[] = [];
      mesh.raycast(new Raycaster(new Vector3(0, 0, 50), new Vector3(0, 0, -1)), hits as never);
      expect(hits).toEqual([]);
    }
    growth.dispose();
    expect(growth.object.parent).toBeNull();
  });

  it("grows glTF models, the site and plants from a copy of the object the viewer draws", () => {
    const source = new Group();
    source.userData = { revealKey: "chair-1" };
    const material = new MeshStandardMaterial({ color: "#885533" });
    const leg = new Mesh(parts[0]!.geometry, material);
    source.add(leg);
    source.position.set(3, 0, 4);
    source.layers.set(31); // waiting on the hidden layer
    const growth = createObjectGrowth(source);
    expect(growth.space).toBe("world");
    const copy = growth.object.children[0]!;
    expect(copy.userData).toEqual({}); // the gate must not hide the stand-in
    expect(copy.layers.mask).toBe(1);
    expect(copy.matrix.elements[12]).toBe(3);
    const grown = (copy.children[0] as Mesh).material as MeshStandardMaterial;
    expect(grown).not.toBe(material);
    expect(grown.clippingPlanes).toHaveLength(1);
    expect(leg.material).toBe(material); // the source is untouched
    growth.dispose();
    material.dispose();
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

  it("grows only the changed elements again and for a shorter time", () => {
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
