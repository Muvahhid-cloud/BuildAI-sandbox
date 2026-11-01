import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, type Mock, vi } from "vitest";

import { bySemanticKey, demoIndex, demoModelJson } from "@/engine/test-fixtures";
import { useEditStore } from "@/features/editing/store";
import { PropertiesPanel } from "@/features/editor/components/PropertiesPanel";
import type { EditOperation, EditPreview } from "@/lib/api/schemas";
import type { Wall } from "@/engine/model/types";
import { useSelectionStore } from "@/stores/selection-store";

const index = demoIndex();

const valid = (warnings: EditPreview["warnings"] = []): EditPreview => ({
  valid: true,
  model: demoModelJson(),
  summary: null,
  warnings,
  changed_ids: [],
  rejection: null,
});

const refused = (message: string): EditPreview => ({
  valid: false,
  model: null,
  summary: null,
  warnings: [],
  changed_ids: [],
  rejection: { code: "X", message, index: 0, element_id: null, related_ids: [], issues: [] },
});

let check: Mock<(op: EditOperation) => Promise<EditPreview>>;
let apply: Mock<(op: EditOperation, preview?: EditPreview) => Promise<boolean>>;

beforeEach(() => {
  useEditStore.getState().end();
  useEditStore.getState().begin("p1", { id: "v1", model: demoModelJson() });
  check = vi.fn<(op: EditOperation) => Promise<EditPreview>>().mockResolvedValue(valid());
  apply = vi.fn<(op: EditOperation, p?: EditPreview) => Promise<boolean>>().mockResolvedValue(true);
  useEditStore.setState({ check, apply });
  useSelectionStore.getState().select(null);
});

function select(key: string) {
  const el = bySemanticKey(index.model, key);
  useSelectionStore.getState().select(el.id);
  render(<PropertiesPanel index={index} />);
  return el;
}

async function retype(label: string, value: string) {
  const input = screen.getByLabelText(label);
  await userEvent.clear(input);
  await userEvent.type(input, value);
}

describe("Properties panel: door and window size", () => {
  it("resizes a window's width, height and sill after a live check", async () => {
    const win = select("window:bed3_s"); // 1.6 x 1.4, sill 0.9
    expect(screen.getByLabelText("Width in meters")).toHaveValue(1.6);
    expect(screen.getByLabelText("Sill in meters")).toHaveValue(0.9);
    await retype("Width in meters", "1.8");
    await retype("Height in meters", "1.5");
    await retype("Sill in meters", "1");
    const op = {
      op: "resize_opening",
      opening_id: win.id,
      width_m: 1.8,
      height_m: 1.5,
      sill_m: 1,
    };
    await waitFor(() => expect(check).toHaveBeenLastCalledWith(op, expect.anything()));
    expect(await screen.findByText(/1\.80 × 1\.50 m fits — valid/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Apply size" }));
    expect(apply).toHaveBeenCalledWith(op, expect.objectContaining({ valid: true }));
  });

  it("widens a door (no sill) and explains a refused size", async () => {
    const door = select("door:bedroom3");
    expect(screen.queryByLabelText("Sill in meters")).toBeNull();
    check.mockResolvedValue(refused("Door D-F01 would reach 2.90 m, above the top of W-F07"));
    await retype("Height in meters", "2.9");
    expect(await screen.findByRole("alert")).toHaveTextContent("above the top of W-F07");
    expect(screen.getByRole("button", { name: "Apply size" })).toBeDisabled();
    check.mockResolvedValue(valid());
    await retype("Height in meters", "2.1");
    await retype("Width in meters", "1");
    await waitFor(() =>
      expect(check).toHaveBeenLastCalledWith(
        { op: "resize_opening", opening_id: door.id, width_m: 1, height_m: 2.1 },
        expect.anything(),
      ),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Apply size" }));
    expect(apply).toHaveBeenCalled();
  });
});

describe("Properties panel: interior walls", () => {
  it("removes a wall after confirming, opening the rooms into each other", async () => {
    const wall = select("wall:G-I1");
    await userEvent.click(screen.getByRole("button", { name: "Remove wall…" }));
    const op = { op: "remove_wall", wall_id: wall.id, merge_rooms: false };
    await waitFor(() => expect(check).toHaveBeenLastCalledWith(op, expect.anything()));
    expect(await screen.findByText(/open into each other/)).toBeInTheDocument();
    expect(screen.getByText(/Door D-G02 in the wall will be removed with it/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm removal" }));
    expect(apply).toHaveBeenCalledWith(op, expect.objectContaining({ valid: true }));
    await waitFor(() => expect(useSelectionStore.getState().selectedId).toBeNull());
  });

  it("offers merging and can be cancelled", async () => {
    const wall = select("wall:G-I1");
    await userEvent.click(screen.getByRole("button", { name: "Remove & merge rooms…" }));
    await waitFor(() =>
      expect(check).toHaveBeenLastCalledWith(
        { op: "remove_wall", wall_id: wall.id, merge_rooms: true },
        expect.anything(),
      ),
    );
    expect(await screen.findByText(/become one room/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(apply).not.toHaveBeenCalled();
    expect(useEditStore.getState().draft).toBeNull();
  });

  it("shows the reason a wall cannot be removed", async () => {
    select("wall:G-I3");
    check.mockResolvedValue(refused("W-G07 encloses Bathroom."));
    await userEvent.click(screen.getByRole("button", { name: "Remove wall…" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("encloses Bathroom");
    expect(screen.getByRole("button", { name: "Confirm removal" })).toBeDisabled();
  });

  it("offers thickness and finish, not removal, for exterior walls", () => {
    const wall = select("wall:G-S") as Wall;
    expect(screen.getByRole("region", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByText(/whole facade on every storey/)).toBeInTheDocument();
    expect(screen.getByLabelText("Thickness in meters")).toHaveValue(
      Number(wall.dimensions.thickness.toFixed(3)),
    );
    expect(screen.getByRole("option", { name: "Facade (outside)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove wall…" })).toBeNull();
    expect(screen.queryByLabelText("Height in meters")).toBeNull(); // structural: fixed height
  });
});

describe("Properties panel: wall thickness, finish and height (D2.5)", () => {
  it("changes a facade's thickness after a live check", async () => {
    const wall = select("wall:G-S");
    await retype("Thickness in meters", "0.42");
    const op = { op: "set_wall_thickness", wall_id: wall.id, thickness_m: 0.42 };
    await waitFor(() => expect(check).toHaveBeenLastCalledWith(op, expect.anything()));
    expect(await screen.findByText(/0\.420 m fits/)).toBeInTheDocument();
    const [applyButton] = screen.getAllByRole("button", { name: "Apply" });
    await userEvent.click(applyButton);
    expect(apply).toHaveBeenCalledWith(op, expect.objectContaining({ valid: true }));
  });

  it("explains a refused thickness and keeps Apply disabled", async () => {
    select("wall:G-I1");
    check.mockResolvedValue(refused("W-G05: 0.500 m thick; interior walls must be 0.08 to 0.30 m"));
    await retype("Thickness in meters", "0.5");
    expect(await screen.findByRole("alert")).toHaveTextContent("interior walls must be");
    expect(screen.getAllByRole("button", { name: "Apply" })[0]).toBeDisabled();
  });

  it("sets a library finish on the facade face", async () => {
    const wall = select("wall:G-S");
    await userEvent.selectOptions(screen.getByLabelText("Finish material"), "exterior_wall");
    const op = {
      op: "set_wall_finish",
      wall_id: wall.id,
      face: "right",
      material_id: "exterior_wall",
    };
    await waitFor(() => expect(check).toHaveBeenLastCalledWith(op, expect.anything()));
    const applyButton = screen.getAllByRole("button", { name: "Apply" })[1];
    await waitFor(() => expect(applyButton).toBeEnabled());
    await userEvent.click(applyButton);
    expect(apply).toHaveBeenCalledWith(op, expect.objectContaining({ valid: true }));
  });

  it("offers a height for non-structural walls only", () => {
    select("wall:G-I1");
    const structural = bySemanticKey(index.model, "wall:G-I1").relationships.some(
      (r) => r.kind === "supports",
    );
    expect(screen.queryByLabelText("Height in meters") === null).toBe(structural);
  });
});

describe("Properties panel: rooms", () => {
  it("renames a room", async () => {
    const room = select("room:bedroom3");
    await retype("Room name", "Guest bedroom");
    const op = { op: "rename_room", room_id: room.id, name: "Guest bedroom" };
    await waitFor(() => expect(check).toHaveBeenLastCalledWith(op, expect.anything()));
    await userEvent.click(await screen.findByRole("button", { name: "Rename" }));
    expect(apply).toHaveBeenCalledWith(op, expect.anything());
  });

  it("changes a room's type, showing notes the server returns", async () => {
    const room = select("room:bedroom3");
    check.mockResolvedValue(
      valid([
        {
          severity: "warning",
          code: "EDIT_PROGRAM_CHANGED",
          path: "/rooms/7",
          message: "Bedroom 3 is the bedroom the specification asks for; it would become a study",
        },
      ]),
    );
    await userEvent.selectOptions(screen.getByLabelText("Room type"), "study");
    const op = { op: "set_room_type", room_id: room.id, room_type: "study" };
    await waitFor(() => expect(check).toHaveBeenLastCalledWith(op, expect.anything()));
    expect(await screen.findByText(/the specification asks for/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Change type" }));
    expect(apply).toHaveBeenCalledWith(op, expect.anything());
  });

  it("does not offer type changes for rooms tied to the building", () => {
    select("room:staircase");
    expect(screen.queryByLabelText("Room type")).toBeNull();
    expect(screen.getByText(/cannot be changed/)).toBeInTheDocument();
    expect(screen.getByLabelText("Room name")).toBeInTheDocument();
  });

  it("shows no edit controls outside an editing session", () => {
    useEditStore.getState().end();
    select("room:bedroom3");
    expect(screen.queryByLabelText("Room name")).toBeNull();
  });
});
