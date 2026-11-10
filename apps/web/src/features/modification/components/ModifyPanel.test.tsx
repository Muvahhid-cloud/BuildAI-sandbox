import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { bySemanticKey, demoModelJson } from "@/engine/test-fixtures";
import { useEditStore } from "@/features/editing/store";
import type { ModifyPlan, Version } from "@/lib/api/schemas";
import { useBuildingStore } from "@/stores/building-store";
import { useHighlightStore } from "@/stores/highlight-store";

import { saveEdits } from "@/features/editing/api";
import { compareVersions, planModification, resolveModification, restoreVersion } from "../api";
import { ComparePanel } from "./ComparePanel";
import { ModifyPanel } from "./ModifyPanel";

vi.mock("../api", () => ({
  planModification: vi.fn(),
  resolveModification: vi.fn(),
  restoreVersion: vi.fn(),
  compareVersions: vi.fn(),
}));
vi.mock("@/features/editing/api", () => ({ saveEdits: vi.fn(), previewEdits: vi.fn() }));

const plan = vi.mocked(planModification);
const resolve = vi.mocked(resolveModification);
const restore = vi.mocked(restoreVersion);
const save = vi.mocked(saveEdits);
const compare = vi.mocked(compareVersions);

const base = demoModelJson();
const kitchen = bySemanticKey(
  (useBuildingStore.getState().load(base), useBuildingStore.getState().index!.model),
  "room:kitchen",
);

/** The candidate: the demo house with the kitchen renamed (as the server would return it). */
function candidate() {
  const m = demoModelJson();
  return {
    ...m,
    elements: m.elements.map((e) => (e.id === kitchen.id ? { ...e, name: "Chef's kitchen" } : e)),
  };
}

const renameOp = { op: "rename_room", room_id: kitchen.id, name: "Chef's kitchen" };

function planOut(over: Partial<ModifyPlan> = {}): ModifyPlan {
  return {
    status: "ready",
    prompt: "rename the kitchen to Chef's kitchen and make the study bigger",
    understanding: "Rename the kitchen; enlarge the study.",
    draft: { understanding: "x", changes: [], unsupported: [] },
    answers: [],
    changes: [
      {
        index: 0,
        quote: "rename the kitchen to Chef's kitchen",
        action: "rename_room",
        status: "planned",
        summary: "Kitchen renamed to Chef's kitchen",
        operations: [renameOp],
        reason: null,
      },
    ],
    unsupported: [],
    questions: [],
    operations: [renameOp],
    preview: {
      valid: true,
      model: candidate(),
      summary: null,
      warnings: [],
      changed_ids: [kitchen.id],
      rejection: null,
    },
    diff: {
      added: [],
      removed: [],
      changed: [kitchen.id],
      lines: [{ kind: "room_renamed", text: "Kitchen renamed to Chef's kitchen" }],
    },
    ...over,
  };
}

const roomNames = () =>
  [...(useBuildingStore.getState().index?.elementsById.values() ?? [])]
    .filter((e) => e.type === "room")
    .map((e) => e.name);

beforeEach(() => {
  vi.resetAllMocks();
  useEditStore.getState().end();
  useEditStore.getState().begin("p1", { id: "v1", model: base });
  useBuildingStore.getState().load(base);
  useHighlightStore.getState().setIds(null);
});

async function ask(text: string) {
  render(<ModifyPanel projectId="p1" versionNumber={1} onSaved={vi.fn()} onClose={vi.fn()} />);
  await userEvent.type(screen.getByLabelText("What should change?"), text);
  await userEvent.click(screen.getByRole("button", { name: "Preview changes" }));
}

describe("Modify with AI", () => {
  it("previews the server's candidate in the viewer with the changes highlighted", async () => {
    plan.mockResolvedValue(planOut());
    await ask("rename the kitchen");
    expect(
      await screen.findByText("Kitchen renamed to Chef's kitchen", { selector: "li" }),
    ).toBeInTheDocument();
    expect(plan).toHaveBeenCalledWith("p1", "v1", "rename the kitchen", []);
    expect(roomNames()).toContain("Chef's kitchen"); // the 2D plan and 3D read this store
    expect(useHighlightStore.getState().ids.has(kitchen.id)).toBe(true);
    // Discard puts the session's model back and clears the highlight.
    await userEvent.click(screen.getAllByRole("button", { name: "Discard" })[0]);
    expect(roomNames()).toContain("Kitchen");
    expect(roomNames()).not.toContain("Chef's kitchen");
    expect(useHighlightStore.getState().ids.size).toBe(0);
  });

  it("asks instead of guessing and resolves the answers without a new AI call", async () => {
    plan.mockResolvedValue(
      planOut({
        status: "needs_clarification",
        operations: [],
        preview: null,
        diff: null,
        changes: [
          {
            index: 0,
            quote: "make the study bigger",
            action: "resize_room",
            status: "needs_clarification",
            summary: "By how many metres?",
            operations: [],
            reason: null,
          },
        ],
        questions: [
          {
            id: "0.amount_m",
            change_index: 0,
            field: "amount_m",
            text: "By how many metres should the wall of Study move?",
            input: "number",
            options: [{ value: "1", label: "1 m" }],
          },
        ],
      }),
    );
    resolve.mockResolvedValue(planOut());
    await ask("make the study bigger");
    expect(await screen.findByText("Please clarify")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply & save as new version" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "1 m" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() =>
      expect(resolve).toHaveBeenCalledWith(
        "p1",
        "v1",
        expect.any(String),
        expect.any(Object),
        [{ question_id: "0.amount_m", value: "1" }],
        [],
      ),
    );
    expect(plan).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Apply & save as new version" })).toBeEnabled();
  });

  it("shows changes that cannot be made and never applies an empty plan", async () => {
    plan.mockResolvedValue(
      planOut({
        status: "nothing_to_apply",
        operations: [],
        preview: null,
        diff: null,
        changes: [
          {
            index: 0,
            quote: "add a window to the corridor",
            action: "add_window",
            status: "refused",
            summary: "",
            operations: [],
            reason: "Corridor has no exterior wall; windows go in exterior walls.",
          },
        ],
        unsupported: [{ quote: "add a pool", reason: "Pools are not supported." }],
      }),
    );
    await ask("add a window to the corridor and add a pool");
    expect(await screen.findByText(/has no exterior wall/)).toBeInTheDocument();
    expect(screen.getByText("Pools are not supported.")).toBeInTheDocument();
    expect(screen.getByText("Nothing in this request can be applied.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply & save as new version" })).toBeDisabled();
  });

  it("applies as a new AI version with the session's edits, then undoes by restoring", async () => {
    const onSaved = vi.fn();
    const sessionOp = { op: "rename_room" as const, room_id: kitchen.id, name: "K1" };
    useEditStore.setState({ ops: [sessionOp], cursor: 1 });
    plan.mockResolvedValue(planOut());
    save.mockResolvedValue({ id: "v2", number: 2, label: "AI changes on v1" } as Version);
    restore.mockResolvedValue({ id: "v3", number: 3, label: "Restored v1" } as Version);
    render(<ModifyPanel projectId="p1" versionNumber={1} onSaved={onSaved} onClose={vi.fn()} />);
    expect(screen.getByText(/Builds on your 1 unsaved plan edit/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("What should change?"), "rename the kitchen");
    await userEvent.click(screen.getByRole("button", { name: "Preview changes" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "Apply & save as new version" }),
    );
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith("p1", "v1", [sessionOp, renameOp], undefined, {
        prompt: "rename the kitchen to Chef's kitchen and make the study bigger",
      }),
    );
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ id: "v2" }));
    expect(await screen.findByText(/Saved as v2/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo — restore v1" }));
    await waitFor(() => expect(restore).toHaveBeenCalledWith("p1", "v1"));
    expect(onSaved).toHaveBeenLastCalledWith(expect.objectContaining({ id: "v3" }));
  });

  it("explains a failed request", async () => {
    const { ApiError } = await import("@/lib/api/errors");
    plan.mockRejectedValue(
      new ApiError(504, "AI_TIMEOUT", "The AI service did not answer in time. Please try again."),
    );
    await ask("rename the kitchen");
    expect(await screen.findByRole("alert")).toHaveTextContent("did not answer in time");
  });
});

describe("Compare versions", () => {
  const versions = [
    { id: "v2", number: 2, label: "AI changes on v1", parent_version_id: "v1" },
    { id: "v1", number: 1, label: "Demo", parent_version_id: null },
  ] as never;

  it("compares the shown version with its parent and highlights its changes", async () => {
    compare.mockResolvedValue({
      a: "v1",
      b: "v2",
      a_number: 1,
      b_number: 2,
      diff: {
        added: ["x1"],
        removed: [],
        changed: [kitchen.id],
        lines: [{ kind: "room_resized", text: "Kitchen: 27.6 m² → 39.6 m²" }],
      },
    });
    render(
      <ComparePanel projectId="p1" versions={versions} shownVersionId="v2" onClose={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Compare" }));
    await waitFor(() => expect(compare).toHaveBeenCalledWith("p1", "v1", "v2"));
    expect(await screen.findByText("Kitchen: 27.6 m² → 39.6 m²")).toBeInTheDocument();
    expect(useHighlightStore.getState().ids).toEqual(new Set(["x1", kitchen.id]));
  });
});
