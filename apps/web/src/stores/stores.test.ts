import { beforeEach, describe, expect, it } from "vitest";

import { demoModelJson } from "@/engine/test-fixtures";

import { useBuildingStore } from "./building-store";
import { useLayerStore } from "./layer-store";
import { useSelectionStore } from "./selection-store";
import { useViewerStore } from "./viewer-store";

beforeEach(() => {
  useViewerStore.getState().reset();
  useLayerStore.getState().showAll();
  useSelectionStore.getState().select(null);
  useBuildingStore.getState().clear();
});

describe("viewer store (floor navigation)", () => {
  it("isolating a floor sets the filter and requests a camera move to it", () => {
    useViewerStore.getState().selectFloor("level-2");
    const s = useViewerStore.getState();
    expect(s.levelFilter).toBe("level-2");
    expect(s.cameraRequest?.preset).toBe("level:level-2");
  });

  it("'All' shows every floor without moving the camera", () => {
    const { selectFloor } = useViewerStore.getState();
    selectFloor("level-2");
    const before = useViewerStore.getState().cameraRequest;
    selectFloor("all");
    expect(useViewerStore.getState().levelFilter).toBe("all");
    expect(useViewerStore.getState().cameraRequest).toBe(before);
  });

  it("re-requesting the same preset produces a new request", () => {
    const { requestCamera } = useViewerStore.getState();
    requestCamera("top");
    const a = useViewerStore.getState().cameraRequest!;
    requestCamera("top");
    expect(useViewerStore.getState().cameraRequest!.nonce).toBeGreaterThan(a.nonce);
  });
});

describe("layer store", () => {
  it("toggles layers independently", () => {
    useLayerStore.getState().toggle("furniture");
    const v = useLayerStore.getState().visible;
    expect(v.furniture).toBe(false);
    expect(v.architecture).toBe(true);
    expect(v.structure).toBe(true);
    useLayerStore.getState().toggle("furniture");
    expect(useLayerStore.getState().visible.furniture).toBe(true);
  });
});

describe("building store", () => {
  it("loads, validates and builds the demo model", () => {
    useBuildingStore.getState().load(demoModelJson());
    const s = useBuildingStore.getState();
    expect(s.status).toBe("ready");
    expect(s.scene!.descriptors.length).toBeGreaterThan(100);
    expect(s.buildMs).not.toBeNull();
  });

  it("reports invalid models instead of rendering them", () => {
    useBuildingStore.getState().load({ schema_version: "1.0.0", elements: "nope" });
    const s = useBuildingStore.getState();
    expect(s.status).toBe("error");
    expect(s.error).toMatch(/schema/);
  });
});

describe("selection store", () => {
  it("stores and clears the selected element id", () => {
    useSelectionStore.getState().select("abc");
    expect(useSelectionStore.getState().selectedId).toBe("abc");
    useSelectionStore.getState().select(null);
    expect(useSelectionStore.getState().selectedId).toBeNull();
  });
});
