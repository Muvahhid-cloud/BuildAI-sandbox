import type { Room } from "@/engine/model/types";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { demoModelJson } from "@/engine/test-fixtures";
import type { EditOperation, EditPreview, Version } from "@/lib/api/schemas";
import { useBuildingStore } from "@/stores/building-store";

import { previewEdits, saveEdits } from "./api";
import { hasUnsavedEdits, useEditStore } from "./store";

vi.mock("./api", () => ({ previewEdits: vi.fn(), saveEdits: vi.fn() }));

const preview = vi.mocked(previewEdits);
const save = vi.mocked(saveEdits);
const base = demoModelJson();
const op = (offset: number): EditOperation => ({
  op: "move_wall",
  wall_id: "f297e2f0-d155-58c8-ba86-3786e039bcbc",
  offset_m: offset,
});

function valid(tag: string): EditPreview {
  const model = demoModelJson();
  model.building = { ...model.building, name: tag };
  return { valid: true, model, summary: null, warnings: [], changed_ids: [tag], rejection: null };
}

const refused: EditPreview = {
  valid: false,
  model: null,
  summary: null,
  warnings: [],
  changed_ids: [],
  rejection: {
    code: "EDIT_INVALID",
    message: "This change would make the design invalid: Corridor is too narrow",
    index: 0,
    element_id: null,
    related_ids: [],
    issues: [],
  },
};

const shownName = () => useBuildingStore.getState().index?.model.building.name;

beforeEach(() => {
  preview.mockReset();
  save.mockReset();
  useEditStore.getState().end();
  useEditStore.getState().begin("p1", { id: "v1", model: base });
  useBuildingStore.getState().load(base);
});

describe("plan editing session", () => {
  it("applies a change the server accepts and shows the server's model", async () => {
    preview.mockResolvedValueOnce(valid("after-1"));
    expect(await useEditStore.getState().apply(op(0.2))).toBe(true);
    expect(preview).toHaveBeenCalledWith("p1", "v1", [op(0.2)], undefined);
    const s = useEditStore.getState();
    expect(s.ops).toEqual([op(0.2)]);
    expect(s.cursor).toBe(1);
    expect(hasUnsavedEdits(s)).toBe(true);
    expect(s.changedIds).toEqual(["after-1"]);
    expect(shownName()).toBe("after-1");
  });

  it("keeps the model and explains a refused change", async () => {
    preview.mockResolvedValueOnce(refused);
    expect(await useEditStore.getState().apply(op(0.8))).toBe(false);
    const s = useEditStore.getState();
    expect(s.ops).toEqual([]);
    expect(s.message?.tone).toBe("error");
    expect(s.message?.text).toContain("too narrow");
    expect(shownName()).toBe(base.building.name);
  });

  it("undoes to the base model and redoes through the server", async () => {
    preview.mockResolvedValueOnce(valid("after-1")).mockResolvedValueOnce(valid("after-2"));
    await useEditStore.getState().apply(op(0.2));
    await useEditStore.getState().apply(op(-0.1));
    expect(preview).toHaveBeenLastCalledWith("p1", "v1", [op(0.2), op(-0.1)], undefined);

    preview.mockResolvedValueOnce(valid("after-1"));
    await useEditStore.getState().undo();
    expect(preview).toHaveBeenLastCalledWith("p1", "v1", [op(0.2)]);
    expect(useEditStore.getState().cursor).toBe(1);
    expect(shownName()).toBe("after-1");

    await useEditStore.getState().undo(); // to the base: no request needed
    expect(useEditStore.getState().cursor).toBe(0);
    expect(shownName()).toBe(base.building.name);

    preview.mockResolvedValueOnce(valid("after-1"));
    await useEditStore.getState().redo();
    expect(useEditStore.getState().cursor).toBe(1);
    expect(useEditStore.getState().ops).toHaveLength(2); // the redo branch is kept
  });

  it("drops the redo branch when a new change is made", async () => {
    preview.mockResolvedValueOnce(valid("a")).mockResolvedValueOnce(valid("b"));
    await useEditStore.getState().apply(op(0.2));
    await useEditStore.getState().apply(op(0.1));
    preview.mockResolvedValueOnce(valid("a"));
    await useEditStore.getState().undo();
    preview.mockResolvedValueOnce(valid("c"));
    await useEditStore.getState().apply(op(-0.3));
    expect(useEditStore.getState().ops).toEqual([op(0.2), op(-0.3)]);
  });

  it("checks a candidate on top of the applied changes without applying it", async () => {
    preview.mockResolvedValueOnce(valid("a"));
    await useEditStore.getState().apply(op(0.2));
    preview.mockResolvedValueOnce(refused);
    const result = await useEditStore.getState().check(op(0.5));
    expect(result.valid).toBe(false);
    expect(preview).toHaveBeenLastCalledWith("p1", "v1", [op(0.2), op(0.5)], undefined);
    expect(useEditStore.getState().ops).toEqual([op(0.2)]);
  });

  it("discards back to the base and saves the applied changes as a version", async () => {
    preview.mockResolvedValueOnce(valid("a"));
    await useEditStore.getState().apply(op(0.2));
    useEditStore.getState().discard();
    expect(useEditStore.getState().cursor).toBe(0);
    expect(shownName()).toBe(base.building.name);

    preview.mockResolvedValueOnce(valid("a"));
    await useEditStore.getState().apply(op(0.2));
    save.mockResolvedValueOnce({ id: "v2" } as Version);
    const saved = await useEditStore.getState().save();
    expect(saved?.id).toBe("v2");
    expect(save).toHaveBeenCalledWith("p1", "v1", [op(0.2)], undefined);
    expect(useEditStore.getState().versionId).toBeNull(); // the editor opens a session on v2
  });

  it("does nothing without changes or a session", async () => {
    expect(await useEditStore.getState().save()).toBeNull();
    useEditStore.getState().end();
    expect(await useEditStore.getState().apply(op(0.2))).toBe(false);
    expect(preview).not.toHaveBeenCalled();
  });
});

describe("resizing a room in the session", () => {
  it("applies resize_room and keeps the resized side chosen", async () => {
    const entrance = base.elements.find(
      (e): e is Room => e.type === "room" && e.name === "Entrance",
    )!;
    const index = useBuildingStore.getState().index!;
    const { roomSides } = await import("@/engine/drawing/room-edit");
    const north = roomSides(index, entrance).find((s) => s.compass === "north")!;
    const moved = demoModelJson();
    const target = moved.elements.find((e) => e.id === entrance.id)!;
    if (target.type !== "room") throw new Error("room expected");
    const top = Math.max(...target.properties.boundary.map((p) => p.y));
    target.properties.boundary = target.properties.boundary.map((p) =>
      p.y === top ? { ...p, y: p.y + 0.2 } : p,
    );
    preview.mockResolvedValueOnce({ ...valid("x"), model: moved });
    const op: EditOperation = {
      op: "resize_room",
      room_id: entrance.id,
      edge: north.index,
      delta_m: 0.2,
    };
    useEditStore.getState().chooseSide({ roomId: entrance.id, edge: north.index });
    expect(await useEditStore.getState().apply(op)).toBe(true);
    expect(preview).toHaveBeenCalledWith("p1", "v1", [op], undefined);
    expect(useEditStore.getState().side).toEqual({ roomId: entrance.id, edge: north.index });
    expect(useEditStore.getState().ops).toEqual([op]);
  });

  it("clears the chosen side on undo, since side numbers belong to one outline", async () => {
    preview.mockResolvedValueOnce(valid("a"));
    await useEditStore.getState().apply(op(0.2));
    useEditStore.getState().chooseSide({ roomId: "r", edge: 2 });
    await useEditStore.getState().undo();
    expect(useEditStore.getState().side).toBeNull();
  });
});

describe("D2.4 operations in the session", () => {
  const resize: EditOperation = {
    op: "resize_opening",
    opening_id: "6befa91d-bd3c-5214-89ec-3449cd3288e1",
    width_m: 1.8,
    height_m: 1.5,
  };
  const rename: EditOperation = {
    op: "rename_room",
    room_id: "0f436215-4c94-5c37-b508-d568f65d6f80",
    name: "Hall",
  };

  it("applies, undoes and redoes them like every operation; a draft ends when applied", async () => {
    preview.mockResolvedValueOnce(valid("resized"));
    useEditStore.getState().setDraft({ key: "k", op: resize, preview: valid("resized") });
    expect(await useEditStore.getState().apply(resize)).toBe(true);
    expect(useEditStore.getState().draft).toBeNull();
    preview.mockResolvedValueOnce(valid("renamed"));
    expect(await useEditStore.getState().apply(rename)).toBe(true);
    expect(useEditStore.getState().ops).toEqual([resize, rename]);
    expect(shownName()).toBe("renamed");
    preview.mockResolvedValueOnce(valid("resized"));
    await useEditStore.getState().undo();
    expect(shownName()).toBe("resized"); // replayed by the server: [resize]
    expect(preview).toHaveBeenLastCalledWith("p1", "v1", [resize]);
    preview.mockResolvedValueOnce(valid("renamed"));
    await useEditStore.getState().redo();
    expect(preview).toHaveBeenLastCalledWith("p1", "v1", [resize, rename]);
    expect(shownName()).toBe("renamed");
  });

  it("discard drops the operations and the draft and shows the base again", async () => {
    preview.mockResolvedValueOnce(valid("resized"));
    await useEditStore.getState().apply(resize);
    useEditStore.getState().setDraft({ key: "k", op: rename, preview: valid("x") });
    useEditStore.getState().discard();
    const s = useEditStore.getState();
    expect(s.ops).toEqual([]);
    expect(s.draft).toBeNull();
    expect(shownName()).toBe(base.building.name);
  });

  it("saves them as one new version", async () => {
    preview.mockResolvedValueOnce(valid("resized"));
    await useEditStore.getState().apply(resize);
    save.mockResolvedValueOnce({ id: "v2" } as Version);
    expect(await useEditStore.getState().save()).toEqual({ id: "v2" });
    expect(save).toHaveBeenCalledWith("p1", "v1", [resize], undefined);
  });
});
