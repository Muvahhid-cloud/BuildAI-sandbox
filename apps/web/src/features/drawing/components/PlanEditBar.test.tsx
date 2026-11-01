import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Room } from "@/engine/model/types";
import { beforeEach, describe, expect, it, type Mock, vi } from "vitest";

import { newOpening } from "@/engine/drawing/opening-edit";
import { newWall } from "@/engine/drawing/wall-add";
import { bySemanticKey, demoIndex, demoModelJson } from "@/engine/test-fixtures";
import { useEditStore } from "@/features/editing/store";
import type { EditOperation } from "@/lib/api/schemas";
import { useSelectionStore } from "@/stores/selection-store";

import { PlanEditBar } from "./PlanEditBar";

const index = demoIndex();
const wall = bySemanticKey(index.model, "wall:G-I1"); // interior, runs east: + = north
const exterior = bySemanticKey(index.model, "wall:G-S");

let apply: Mock<(op: EditOperation) => Promise<boolean>>;
let undo: Mock<() => Promise<void>>;

beforeEach(() => {
  useEditStore.getState().end();
  useEditStore.getState().begin("p1", { id: "v1", model: demoModelJson() });
  apply = vi.fn<(op: EditOperation) => Promise<boolean>>().mockResolvedValue(true);
  undo = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
  useEditStore.setState({ apply, undo });
  useSelectionStore.getState().select(null);
});

describe("PlanEditBar", () => {
  it("starts with no changes and explains how to edit", () => {
    render(<PlanEditBar index={index} />);
    expect(screen.getByText("No changes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save version" })).toBeDisabled();
    expect(screen.getByText(/Select a wall, a room/)).toBeInTheDocument();
  });

  it("moves the selected wall by the typed distance in a compass direction", async () => {
    useSelectionStore.getState().select(wall.id);
    render(<PlanEditBar index={index} />);
    const input = screen.getByLabelText("Distance in meters");
    await userEvent.clear(input);
    await userEvent.type(input, "0.25");
    await userEvent.click(screen.getByRole("button", { name: "↑ North" }));
    expect(apply).toHaveBeenCalledWith({ op: "move_wall", wall_id: wall.id, offset_m: 0.25 });
    await userEvent.click(screen.getByRole("button", { name: "↓ South" }));
    expect(apply).toHaveBeenLastCalledWith({ op: "move_wall", wall_id: wall.id, offset_m: -0.25 });
  });

  it("nudges with the arrow keys and undoes with Ctrl+Z", async () => {
    useSelectionStore.getState().select(wall.id);
    render(<PlanEditBar index={index} />);
    await userEvent.keyboard("{ArrowUp}");
    expect(apply).toHaveBeenLastCalledWith({ op: "move_wall", wall_id: wall.id, offset_m: 0.05 });
    await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}");
    expect(apply).toHaveBeenLastCalledWith({ op: "move_wall", wall_id: wall.id, offset_m: -0.25 });
    await userEvent.keyboard("{ArrowLeft}"); // along the wall: ignored
    expect(apply).toHaveBeenCalledTimes(2);
    await userEvent.keyboard("{Control>}z{/Control}");
    expect(undo).toHaveBeenCalled();
  });

  it("moves an exterior wall as a whole facade", async () => {
    useSelectionStore.getState().select(exterior.id);
    render(<PlanEditBar index={index} />);
    expect(screen.getByText(/drag the facade on the plan/)).toBeInTheDocument();
    const input = screen.getByLabelText("Distance in meters");
    await userEvent.clear(input);
    await userEvent.type(input, "0.3");
    await userEvent.click(screen.getByRole("button", { name: "↓ South" }));
    expect(apply).toHaveBeenCalledWith(
      expect.objectContaining({ op: "move_wall", wall_id: exterior.id }),
    );
  });

  it("shows the server's reason for a refused change", () => {
    render(<PlanEditBar index={index} />);
    act(() =>
      useEditStore.setState({
        message: {
          tone: "error",
          text: "This change would make the design invalid: Corridor is too narrow",
          issues: [
            { severity: "error", code: "A", path: "", message: "Corridor is too narrow" },
            { severity: "error", code: "B", path: "", message: "D1 reaches into a junction" },
          ],
        },
      }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Corridor is too narrow");
    expect(screen.getByRole("alert")).toHaveTextContent("D1 reaches into a junction");
  });
});

describe("PlanEditBar room resizing", () => {
  const entrance = index.model.elements.find(
    (e): e is Room => e.type === "room" && e.name === "Entrance",
  )!;

  it("asks for a side, then resizes it outwards or inwards", async () => {
    useSelectionStore.getState().select(entrance.id);
    const { roomSides } = await import("@/engine/drawing/room-edit");
    const north = roomSides(index, entrance).find((s) => s.compass === "north")!;
    const { rerender } = render(<PlanEditBar index={index} />);
    expect(screen.getByText(/Click a side handle of Entrance/)).toBeInTheDocument();
    act(() => useEditStore.getState().chooseSide({ roomId: entrance.id, edge: north.index }));
    rerender(<PlanEditBar index={index} />);
    expect(screen.getByText(/north side \(W-G05\)/)).toBeInTheDocument();
    const input = screen.getByLabelText("Distance in meters");
    await userEvent.clear(input);
    await userEvent.type(input, "0.3");
    await userEvent.click(screen.getByRole("button", { name: "Enlarge" }));
    expect(apply).toHaveBeenLastCalledWith({
      op: "resize_room",
      room_id: entrance.id,
      edge: north.index,
      delta_m: 0.3,
    });
    await userEvent.click(screen.getByRole("button", { name: "Shrink" }));
    expect(apply).toHaveBeenLastCalledWith(
      expect.objectContaining({ op: "resize_room", delta_m: -0.3 }),
    );
    (document.activeElement as HTMLElement | null)?.blur();
    await userEvent.keyboard("{ArrowUp}");
    expect(apply).toHaveBeenLastCalledWith(expect.objectContaining({ delta_m: 0.05 }));
    await userEvent.keyboard("{ArrowLeft}"); // across the side: ignored
    expect(apply).toHaveBeenCalledTimes(3);
  });

  it("resizes a room at its facade side (the facade moves)", async () => {
    useSelectionStore.getState().select(entrance.id);
    const { roomSides } = await import("@/engine/drawing/room-edit");
    const exterior = roomSides(index, entrance).find((s) => s.kind === "exterior")!;
    useEditStore.getState().chooseSide({ roomId: entrance.id, edge: exterior.index });
    render(<PlanEditBar index={index} />);
    await userEvent.click(screen.getByRole("button", { name: "Enlarge" }));
    expect(apply).toHaveBeenCalledWith(
      expect.objectContaining({ op: "resize_room", room_id: entrance.id }),
    );
  });

  it("explains a side that cannot move", async () => {
    const balcony = bySemanticKey(index.model, "room:balcony") as Room;
    useSelectionStore.getState().select(balcony.id);
    const { roomSides } = await import("@/engine/drawing/room-edit");
    const side = roomSides(index, balcony).find((s) => !s.resizable)!;
    useEditStore.getState().chooseSide({ roomId: balcony.id, edge: side.index });
    render(<PlanEditBar index={index} />);
    expect(screen.getByText(/Balcony/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Enlarge" })).toBeNull();
  });
});

describe("PlanEditBar: doors and windows", () => {
  const door = bySemanticKey(index.model, "door:ent_corr"); // in G-I1 (runs east) at 1.2 m

  it("moves the selected opening to a typed position, slides it and removes it", async () => {
    useSelectionStore.getState().select(door.id);
    render(<PlanEditBar index={index} />);
    expect(screen.getByText(/0.90 × 2.10 m in W-G05/)).toBeInTheDocument();
    const position = screen.getByLabelText("Position");
    expect(position).toHaveValue(1.2);
    await userEvent.clear(position);
    await userEvent.type(position, "2.05{Enter}");
    expect(apply).toHaveBeenLastCalledWith({
      op: "move_opening",
      opening_id: door.id,
      offset_m: 2.05,
    });
    await userEvent.click(screen.getByRole("button", { name: "East →" }));
    expect(apply).toHaveBeenLastCalledWith({
      op: "move_opening",
      opening_id: door.id,
      offset_m: 1.25,
    });
    position.blur();
    await userEvent.keyboard("{Shift>}{ArrowLeft}{/Shift}");
    expect(apply).toHaveBeenLastCalledWith({
      op: "move_opening",
      opening_id: door.id,
      offset_m: 0.95,
    });
    await userEvent.keyboard("{ArrowUp}"); // across the wall: not a slide
    expect(apply).toHaveBeenCalledTimes(3);
    await userEvent.keyboard("{Delete}");
    expect(apply).toHaveBeenLastCalledWith({ op: "remove_element", element_id: door.id });
    await act(async () => undefined);
    expect(useSelectionStore.getState().selectedId).toBeNull(); // removed: nothing selected
  });

  it("starts adding a door or window sized like the model's own, and Esc stops", async () => {
    render(<PlanEditBar index={index} />);
    await userEvent.click(screen.getByRole("button", { name: "+ Window" }));
    const group = screen.getByRole("group", { name: "Add a window" });
    expect(group).toHaveTextContent(
      "Click a wall on the plan to place the window (exterior walls only)",
    );
    expect(useEditStore.getState().placing).toMatchObject({ kind: "window" });
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(useEditStore.getState().placing).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "+ Door" }));
    expect(useEditStore.getState().placing).toMatchObject({
      kind: "door",
      doorKind: "interior",
      width: 0.9,
    });
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "entrance");
    expect(useEditStore.getState().placing).toMatchObject({
      doorKind: "entrance",
      width: 1,
      height: 2.2,
    });
    const width = screen.getByLabelText("Width");
    await userEvent.clear(width);
    await userEvent.type(width, "1.2");
    expect(useEditStore.getState().placing?.width).toBe(1.2);
    await userEvent.keyboard("{Escape}");
    expect(useEditStore.getState().placing).toBeNull();
  });
});

describe("PlanEditBar: adding a wall", () => {
  it("opens the wall panel with its choices and closes it with Esc", async () => {
    render(<PlanEditBar index={index} />);
    await userEvent.click(screen.getByRole("button", { name: "+ Wall" }));
    expect(screen.getByRole("group", { name: "Add a wall" })).toBeInTheDocument();
    expect(useEditStore.getState().placingWall).toMatchObject({ direction: "north_south" });
    await userEvent.click(screen.getByRole("button", { name: "↔ East–west" }));
    expect(useEditStore.getState().placingWall?.direction).toBe("east_west");
    await userEvent.selectOptions(screen.getByLabelText("New room type"), "storage");
    expect(useEditStore.getState().placingWall?.newRoomType).toBe("storage");
    await userEvent.click(screen.getByLabelText("Door"));
    expect(useEditStore.getState().placingWall?.door).toBe(false);
    await userEvent.keyboard("{Escape}");
    expect(useEditStore.getState().placingWall).toBeNull();
  });

  it("adding a door or window and adding a wall exclude each other", async () => {
    render(<PlanEditBar index={index} />);
    await userEvent.click(screen.getByRole("button", { name: "+ Wall" }));
    act(() => useEditStore.getState().setPlacing(newOpening(index, "door")));
    expect(useEditStore.getState().placingWall).toBeNull();
    act(() => useEditStore.getState().setPlacingWall(newWall(index)));
    expect(useEditStore.getState().placing).toBeNull();
    act(() => useEditStore.getState().setPlacingWall(null));
  });
});
