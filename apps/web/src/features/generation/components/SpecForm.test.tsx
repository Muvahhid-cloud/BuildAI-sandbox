import type { BuildingSpecification } from "@buildai/schema";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { Issue } from "@/lib/api/schemas";

import type { DesignOptions } from "../api";
import { emptySpec, nextRoomKey, SPEC_PRESETS } from "../spec-presets";
import { checkSpecShape, SpecForm } from "./SpecForm";

const OPTIONS: DesignOptions = {
  available: [
    {
      id: "modern-minimal",
      name: "Modern minimal",
      source: "buildai-design-systems@1",
      style_tags: ["modern"],
      roof: { types: ["flat", "gable"], default: "flat", default_pitch_deg: null },
      windows: { styles: ["standard", "large", "panoramic"], default: "large" },
      facade: {
        materials: ["render", "concrete"],
        default_material: "render",
        colors: ["white", "yellow"],
        default_color: "white",
        custom_colors: true,
      },
    },
  ],
  unavailable: [{ id: "classic-brick", name: "Classic brick", reason: "it is draft; review" }],
  palette: [
    { name: "white", hex: "#f4f2ec" },
    { name: "yellow", hex: "#e8c547" },
  ],
};

function Harness({
  initial,
  onSpec,
  issues = [],
}: {
  initial: BuildingSpecification;
  onSpec: (s: BuildingSpecification) => void;
  issues?: Issue[];
}) {
  const [spec, setSpec] = useState(initial);
  const [seed, setSeed] = useState(0);
  return (
    <SpecForm
      spec={spec}
      onChange={(s) => {
        setSpec(s);
        onSpec(s);
      }}
      seed={seed}
      onSeedChange={setSeed}
      issues={issues}
      designOptions={OPTIONS}
    />
  );
}

function setup(initial = emptySpec(), issues: Issue[] = []) {
  let last = initial;
  render(<Harness initial={initial} onSpec={(s) => (last = s)} issues={issues} />);
  return () => last;
}

describe("SpecForm", () => {
  it("presets are the shared reference specs and pass the generated schema", () => {
    expect(SPEC_PRESETS.length).toBeGreaterThanOrEqual(4);
    for (const p of SPEC_PRESETS) expect(checkSpecShape(p.spec)).toEqual([]);
    expect(SPEC_PRESETS[0].spec.targets.gross_floor_area_m2).toBe(280);
  });

  it("loads a preset", async () => {
    const spec = setup();
    await userEvent.selectOptions(screen.getByLabelText(/reference specification/i), "family-280");
    expect(spec().name).toBe("Modern family house");
    expect(spec().features?.garage?.cars).toBe(2);
    expect(screen.getByLabelText("Name")).toHaveValue("Modern family house");
  });

  it("edits storeys, area and rooms", async () => {
    const spec = setup();
    await userEvent.click(screen.getByRole("button", { name: "3" }));
    expect(spec().targets.storeys).toBe(3);

    const area = screen.getByLabelText(/floor area/i);
    await userEvent.clear(area);
    await userEvent.type(area, "240");
    expect(spec().targets.gross_floor_area_m2).toBe(240);
    await userEvent.clear(area);
    expect(spec().targets.gross_floor_area_m2).toBeNull(); // blank = derived by the engine

    const before = spec().rooms.length;
    await userEvent.click(screen.getByRole("button", { name: "+ Add room" }));
    expect(spec().rooms).toHaveLength(before + 1);
    expect(new Set(spec().rooms.map((r) => r.key)).size).toBe(before + 1); // keys stay unique

    await userEvent.click(screen.getByRole("button", { name: "Remove room 1" }));
    expect(spec().rooms).toHaveLength(before);
  });

  it("offers en-suite only for bedrooms", async () => {
    const spec = setup();
    const bedroomRow = spec().rooms.findIndex((r) => r.type === "bedroom");
    const enSuites = screen.getAllByLabelText("En-suite");
    expect(enSuites).toHaveLength(1);
    await userEvent.click(enSuites[0]);
    expect(spec().rooms[bedroomRow].features).toEqual(["en_suite"]);
  });

  it("facade color: inherited, design-system default, then the user's explicit choice", async () => {
    const spec = setup();
    const group = screen.getByRole("radiogroup", { name: /facade color/i });
    expect(within(group.parentElement!).getByText("Inherited default")).toBeVisible();

    await userEvent.selectOptions(screen.getByLabelText("Design system"), "modern-minimal");
    expect(spec().style?.design_system).toBe("modern-minimal");
    expect(screen.getByText("Design-system default")).toBeVisible();

    await userEvent.click(screen.getByRole("radio", { name: "yellow" }));
    expect(spec().design?.facade_color).toBe("yellow");
    expect(screen.getAllByText("Your requirement").length).toBeGreaterThan(0);
    expect(screen.getByText(/display color only/)).toBeVisible();
  });

  it("draft design systems are listed but cannot be chosen", () => {
    setup();
    const option = screen.getByRole("option", { name: /Classic brick — not available/ });
    expect(option).toBeDisabled();
  });

  it("places emphasised windows on chosen facades and excludes others", async () => {
    const spec = setup();
    await userEvent.selectOptions(screen.getByLabelText("Emphasised windows"), "panoramic");
    expect(spec().design?.windows).toEqual({
      emphasis: "panoramic",
      preferred_facades: ["rear"],
      excluded_facades: [],
    });
    await userEvent.click(screen.getByLabelText("Exclude Front (street)"));
    expect(spec().design?.windows?.excluded_facades).toEqual(["front"]);
    await userEvent.selectOptions(screen.getByLabelText("Emphasised windows"), "");
    expect(spec().design?.windows).toBeNull();
  });

  it("lets a room face the garden", async () => {
    const spec = setup();
    await userEvent.selectOptions(screen.getByLabelText("Room 1 faces"), "rear");
    expect(spec().rooms[0].faces).toBe("rear");
    expect(checkSpecShape(spec())).toEqual([]);
  });

  it("shows design conflicts with their suggestions", () => {
    setup(emptySpec(), [
      {
        severity: "error",
        code: "DESIGN_OPTION_CONFLICT",
        path: "/design/facade_color",
        message: "Facade color yellow is not in the Classic brick palette",
        suggestion: "Choose another design system (or none) to color the facade.",
      },
    ]);
    const list = screen.getByRole("list", { name: "Design conflicts" });
    expect(list).toHaveTextContent("not in the Classic brick palette");
    expect(list).toHaveTextContent("Choose another design system");
  });

  it("balcony needs two floors", async () => {
    const spec = setup();
    await userEvent.click(screen.getByLabelText(/^Balcony/));
    expect(spec().features?.balconies).toEqual([{ level: 1 }]);
    await userEvent.click(screen.getByRole("button", { name: "1" }));
    expect(screen.getByLabelText(/^Balcony/)).toBeDisabled();
  });
});

describe("spec helpers", () => {
  it("nextRoomKey avoids collisions", () => {
    const spec = emptySpec();
    expect(nextRoomKey(spec, "study")).toBe("study");
    expect(nextRoomKey(spec, "bedroom")).toBe("bedroom_2");
  });

  it("checkSpecShape reports schema problems with JSON pointers", () => {
    const bad = { ...emptySpec(), targets: { storeys: 5 } } as BuildingSpecification;
    const issues = checkSpecShape(bad);
    expect(issues.length).toBeGreaterThan(0);
    expect(issues[0].path).toBe("/targets/storeys");
  });
});
