import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { wallPoint } from "@/engine/drawing/opening-edit";
import type { Wall } from "@/engine/model/types";
import { bySemanticKey, demoIndex, demoModelJson } from "@/engine/test-fixtures";
import { useEditStore } from "@/features/editing/store";
import { useLayerStore } from "@/stores/layer-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";

import { drawingFileName } from "../export";
import { DrawingDownloads } from "./DrawingDownloads";
import { PlanView } from "./PlanView";

const index = demoIndex();

beforeEach(() => {
  useSelectionStore.getState().select(null);
  useLayerStore.getState().showAll();
  useViewerStore.getState().setPlanLevel(null);
});

describe("PlanView", () => {
  it("draws the first level by default and the chosen level on request", () => {
    const { container } = render(<PlanView index={index} />);
    expect(screen.getByRole("img", { name: "Floor 1 floor plan" })).toBeInTheDocument();
    expect(container.textContent).toContain("Kitchen");
    act(() => useViewerStore.getState().setPlanLevel(index.levels[1].id));
    expect(screen.getByRole("img", { name: "Floor 2 floor plan" })).toBeInTheDocument();
  });

  it("maps drawn groups to model elements and highlights the selection", () => {
    const kitchen = bySemanticKey(index.model, "room:kitchen");
    const { container } = render(<PlanView index={index} />);
    expect(container.querySelector(`[data-element-id="${kitchen.id}"]`)).not.toBeNull();
    act(() => useSelectionStore.getState().select(kitchen.id));
    expect(container.querySelector("style")?.textContent).toContain(kitchen.id);
  });

  it("follows the furniture layer", () => {
    const { container } = render(<PlanView index={index} />);
    const count = () => container.querySelectorAll('[data-role="furniture"]').length;
    expect(count()).toBeGreaterThan(0);
    act(() => useLayerStore.getState().setVisible("furniture", false));
    expect(count()).toBe(0);
  });
});

describe("DrawingDownloads", () => {
  it("offers PDF, SVG and PNG", async () => {
    render(<DrawingDownloads index={index} info={{ projectName: "Demo", versionLabel: "v1" }} />);
    for (const name of ["PDF", "SVG", "PNG"]) {
      expect(screen.getByRole("button", { name })).toBeEnabled();
    }
    await userEvent.hover(screen.getByRole("button", { name: "PDF" }));
    expect(screen.getByRole("button", { name: "PDF" })).toHaveAttribute(
      "title",
      expect.stringContaining("one page per floor"),
    );
  });

  it("names files after the project and the drawing", () => {
    expect(drawingFileName("Дом / House #1", "Floor 1 plan", "svg")).toBe(
      "дом-house-1-floor-1-plan.svg",
    );
    expect(drawingFileName("Villa Ála", "floor-plans", "pdf")).toBe("villa-ála-floor-plans.pdf");
    expect(drawingFileName("Дом Майя", "План", "png")).toBe("дом-майя-план.png");
    expect(drawingFileName("!!!", "", "svg")).toBe("drawing-drawing.svg");
    expect(drawingFileName("V1.2 L check - spec 11", "Floor 1 plan", "svg")).toBe(
      "v12-l-check-spec-11-floor-1-plan.svg",
    );
  });
});

describe("viewer store", () => {
  it("keeps the 3D / plan choice when a new model is loaded", () => {
    useViewerStore.getState().setViewMode("plan");
    useViewerStore.getState().setPlanLevel(index.levels[1].id);
    useViewerStore.getState().reset();
    expect(useViewerStore.getState().viewMode).toBe("plan");
    expect(useViewerStore.getState().planLevelId).toBeNull();
    useViewerStore.getState().setViewMode("3d");
  });
});

describe("PlanView: dragging a door or window", () => {
  it("slides a selected opening along its wall and onto another wall, checked live", async () => {
    const win = bySemanticKey(index.model, "window:storage"); // on G-S (runs east) at 5.7, 0.8 m
    const east = bySemanticKey(index.model, "wall:G-E");
    const check = vi.fn().mockResolvedValue({
      valid: true,
      model: demoModelJson(),
      summary: null,
      warnings: [],
      changed_ids: [win.id],
      rejection: null,
    });
    const apply = vi.fn().mockResolvedValue(true);
    useEditStore.getState().end();
    useEditStore.getState().begin("p1", { id: "v1", model: demoModelJson() });
    useEditStore.setState({ check, apply });
    useSelectionStore.getState().select(win.id);
    const { container } = render(<PlanView index={index} />);
    const svg = container.querySelector("svg")!;
    const [, , vw, vh] = svg.getAttribute("viewBox")!.split(" ").map(Number);
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: vw, height: vh }) as DOMRect;
    svg.setPointerCapture = () => undefined;
    const group = container.querySelector(`[data-element-id="${win.id}"]`)!;

    // 1 pixel = 1 paper mm = 0.1 m at 1:100. 1.0 m east along the wall.
    fireEvent.pointerDown(group, { clientX: 100, clientY: 100, button: 0 });
    fireEvent.pointerMove(svg, { clientX: 110, clientY: 100 });
    expect(await screen.findByTestId("opening-ghost")).toBeInTheDocument();
    await waitFor(() =>
      expect(check).toHaveBeenLastCalledWith(
        { op: "move_opening", opening_id: win.id, offset_m: 6.7 },
        expect.anything(),
      ),
    );
    expect(await screen.findByText(/valid — release to apply/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("6.70 m from its start");

    // Onto the east wall: the pointer over it picks it as the new host.
    const [cx, cy] = wallPoint(east as Wall, 4.0);
    const center = [5.7 + 0.4, 0]; // the window's centre when the drag began
    const to = { clientX: 100 + (cx - center[0]) * 10, clientY: 100 - (cy - center[1]) * 10 };
    fireEvent.pointerMove(svg, to);
    await waitFor(() =>
      expect(check).toHaveBeenLastCalledWith(
        { op: "move_opening", opening_id: win.id, offset_m: 3.6, host_wall_id: east.id },
        expect.anything(),
      ),
    );
    fireEvent.pointerUp(svg, to);
    await waitFor(() =>
      expect(apply).toHaveBeenCalledWith(
        { op: "move_opening", opening_id: win.id, offset_m: 3.6, host_wall_id: east.id },
        expect.anything(),
      ),
    );
    useEditStore.getState().end();
  });
});

describe("PlanView: resizing a door or window", () => {
  it("drags an end grip to a new width, checked live, and applies it on release", async () => {
    const win = bySemanticKey(index.model, "window:storage"); // G-S (from 0,0 east): 5.7-6.5 m
    const check = vi.fn().mockResolvedValue({
      valid: true,
      model: demoModelJson(),
      summary: null,
      warnings: [],
      changed_ids: [win.id],
      rejection: null,
    });
    const apply = vi.fn().mockResolvedValue(true);
    useEditStore.getState().end();
    useEditStore.getState().begin("p1", { id: "v1", model: demoModelJson() });
    useEditStore.setState({ check, apply });
    useSelectionStore.getState().select(win.id);
    const { container } = render(<PlanView index={index} />);
    const svg = container.querySelector("svg")!;
    const [vx, vy, vw, vh] = svg.getAttribute("viewBox")!.split(" ").map(Number);
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: vw, height: vh }) as DOMRect;
    svg.setPointerCapture = () => undefined;
    // Model (x, y) -> client pixels: 1 px = 1 paper mm = 0.1 m at 1:100, y up the screen.
    const at = (x: number, y: number) => ({ clientX: x * 10 - vx, clientY: -y * 10 - vy });

    const end = screen.getByTestId("opening-grip-end");
    expect(screen.getByTestId("opening-grip-start")).toBeInTheDocument();
    fireEvent.pointerDown(end, { ...at(6.5, 0), button: 0 });
    fireEvent.pointerMove(svg, at(7.31, 0));
    expect(await screen.findByTestId("opening-ghost")).toBeInTheDocument();
    const op = {
      op: "resize_opening",
      opening_id: win.id,
      width_m: 1.6,
      height_m: win.type === "window" ? win.dimensions.height : 0,
      offset_m: 5.7,
    };
    await waitFor(() => expect(check).toHaveBeenLastCalledWith(op, expect.anything()));
    expect(await screen.findByText(/1\.60 × 0\.60 m \(was 0\.80 m wide\)/)).toBeInTheDocument();
    fireEvent.pointerUp(svg, at(7.31, 0));
    await waitFor(() => expect(apply).toHaveBeenCalledWith(op, expect.anything()));
    useEditStore.getState().end();
  });

  it("drags the start grip: the far end stays where it is", async () => {
    const win = bySemanticKey(index.model, "window:storage");
    const check = vi.fn().mockReturnValue(new Promise(() => undefined));
    useEditStore.getState().end();
    useEditStore.getState().begin("p1", { id: "v1", model: demoModelJson() });
    useEditStore.setState({ check });
    useSelectionStore.getState().select(win.id);
    const { container } = render(<PlanView index={index} />);
    const svg = container.querySelector("svg")!;
    const [vx, vy, vw, vh] = svg.getAttribute("viewBox")!.split(" ").map(Number);
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: vw, height: vh }) as DOMRect;
    svg.setPointerCapture = () => undefined;
    const at = (x: number, y: number) => ({ clientX: x * 10 - vx, clientY: -y * 10 - vy });
    fireEvent.pointerDown(screen.getByTestId("opening-grip-start"), { ...at(5.7, 0), button: 0 });
    fireEvent.pointerMove(svg, at(5.2, 0));
    await waitFor(() =>
      expect(check).toHaveBeenLastCalledWith(
        expect.objectContaining({ op: "resize_opening", offset_m: 5.2, width_m: 1.3 }),
        expect.anything(),
      ),
    );
    useEditStore.getState().end();
  });

  it("shows the model of a change prepared in the properties panel", () => {
    const kitchen = bySemanticKey(index.model, "room:kitchen");
    const raw = demoModelJson() as { elements: { id: string; name: string }[] };
    const renamed = {
      ...raw,
      elements: raw.elements.map((e) =>
        e.id === kitchen.id ? { ...e, name: "Chef's kitchen" } : e,
      ),
    };
    useEditStore.getState().end();
    useEditStore.getState().begin("p1", { id: "v1", model: demoModelJson() });
    const { container } = render(<PlanView index={index} />);
    expect(container.textContent).not.toContain("Chef's kitchen");
    act(() =>
      useEditStore.getState().setDraft({
        key: "k",
        op: { op: "rename_room", room_id: kitchen.id, name: "Chef's kitchen" },
        preview: {
          valid: true,
          model: renamed,
          summary: null,
          warnings: [],
          changed_ids: [kitchen.id],
          rejection: null,
        },
      }),
    );
    expect(container.textContent).toContain("Chef's kitchen");
    act(() => useEditStore.getState().setDraft(null));
    expect(container.textContent).not.toContain("Chef's kitchen");
    useEditStore.getState().end();
  });
});

describe("PlanView: adding a wall", () => {
  it("shows the wall across the room under the pointer, checks it, and places it on click", async () => {
    const entrance = bySemanticKey(index.model, "room:entrance");
    const check = vi.fn().mockResolvedValue({
      valid: true,
      model: demoModelJson(),
      summary: null,
      warnings: [],
      changed_ids: [],
      rejection: null,
    });
    const apply = vi.fn().mockResolvedValue(true);
    useEditStore.getState().end();
    useEditStore.getState().begin("p1", { id: "v1", model: demoModelJson() });
    useEditStore.setState({ check, apply });
    useEditStore.getState().setPlacingWall({
      direction: "north_south",
      door: true,
      doorWidth: 0.8,
      doorHeight: 2.1,
      newRoomType: "storage",
    });
    const { container } = render(<PlanView index={index} />);
    const svg = container.querySelector("svg")!;
    const [vx, vy, vw, vh] = svg.getAttribute("viewBox")!.split(" ").map(Number);
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: vw, height: vh }) as DOMRect;
    svg.setPointerCapture = () => undefined;
    const at = (x: number, y: number) => ({ clientX: x * 10 - vx, clientY: -y * 10 - vy });

    fireEvent.pointerMove(svg, at(1.02, 1.44));
    expect(await screen.findByTestId("wall-ghost")).toBeInTheDocument();
    const op = {
      op: "add_wall",
      room_id: entrance.id,
      direction: "north_south",
      x_m: 1.0,
      y_m: 1.45,
      new_room_type: "storage",
      door_width_m: 0.8,
      door_height_m: 2.1,
    };
    await waitFor(() => expect(check).toHaveBeenLastCalledWith(op, expect.anything()));
    expect(
      await screen.findByText(/across Entrance · 4\.80 m · valid — click to place/),
    ).toBeInTheDocument();
    fireEvent.pointerDown(svg, { ...at(1.02, 1.44), button: 0 });
    fireEvent.pointerUp(svg, at(1.02, 1.44));
    await waitFor(() => expect(apply).toHaveBeenCalledWith(op, expect.anything()));
    useEditStore.getState().end();
  });
});
