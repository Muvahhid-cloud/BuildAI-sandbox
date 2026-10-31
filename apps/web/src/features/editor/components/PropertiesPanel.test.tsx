import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { parseBuildingModel } from "@/engine/model/parse";
import { bySemanticKey, demoIndex, typedDemoModelJson } from "@/engine/test-fixtures";
import { useSelectionStore } from "@/stores/selection-store";

import { PropertiesPanel } from "./PropertiesPanel";

const index = demoIndex();

beforeEach(() => useSelectionStore.getState().select(null));

describe("PropertiesPanel", () => {
  it("prompts to select something when nothing is selected", () => {
    render(<PropertiesPanel index={index} />);
    expect(screen.getByText(/Click any object in the 3D view/)).toBeInTheDocument();
  });

  it("shows the selected element's properties from the model", () => {
    useSelectionStore.getState().select(bySemanticKey(index.model, "wall:G-S").id);
    render(<PropertiesPanel index={index} />);
    expect(screen.getByRole("heading", { name: "W-G01" })).toBeInTheDocument();
    expect(screen.getByText("Exterior wall")).toBeInTheDocument();
    expect(screen.getByText("Length").nextSibling).toHaveTextContent("12 m");
    expect(screen.getByText("Material", { selector: "dt" }).nextSibling).toHaveTextContent("Brick");
  });

  it("selects a related element when its relationship is clicked", async () => {
    useSelectionStore.getState().select(bySemanticKey(index.model, "door:front").id);
    render(<PropertiesPanel index={index} />);
    await userEvent.click(screen.getByRole("button", { name: "W-G01 (Exterior wall)" }));
    expect(useSelectionStore.getState().selectedId).toBe(bySemanticKey(index.model, "wall:G-S").id);
    expect(await screen.findByRole("heading", { name: "W-G01" })).toBeInTheDocument();
  });

  it("shows the component type and its assembly layers", () => {
    const typed = parseBuildingModel(typedDemoModelJson());
    useSelectionStore.getState().select(bySemanticKey(typed.model, "wall:G-S").id);
    render(<PropertiesPanel index={typed} />);
    expect(screen.getByText("Component type", { selector: "dt" }).nextSibling).toHaveTextContent(
      "Test exterior wall",
    );
    expect(screen.getByText("Assembly · Test exterior wall 300")).toBeInTheDocument();
    expect(screen.getByText("1. Structure").nextSibling).toHaveTextContent(
      "Unspecified material · 0.28 m",
    );
    expect(screen.getByText("Catalog source").nextSibling).toHaveTextContent("test-types@1");
  });

  it("clears the selection", async () => {
    useSelectionStore.getState().select(bySemanticKey(index.model, "room:living").id);
    render(<PropertiesPanel index={index} />);
    await userEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(useSelectionStore.getState().selectedId).toBeNull();
  });
});
