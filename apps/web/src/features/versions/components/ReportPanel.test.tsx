import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { issueSchema, versionSchema, type Issue, type Version } from "@/lib/api/schemas";
import { useSelectionStore } from "@/stores/selection-store";

import { ReportPanel } from "./ReportPanel";

const WINDOW_ID = "5b0d4a1e-8c2f-4e3a-9d1b-2f6e7a8c9d01";
const WALL_ID = "5b0d4a1e-8c2f-4e3a-9d1b-2f6e7a8c9d02";

// A geometric finding as the API sends it (app/modules/building/geometry_checks.py).
const geometric: Issue = issueSchema.parse({
  severity: "error",
  code: "OPENING_OUTSIDE_WALL",
  path: "/elements/42/dimensions/width",
  message: "WN-G01 extends 0.100 m beyond the end of W-G01 (12.100 m of a 12.000 m wall)",
  suggestion: null,
  rule_ref: null,
  element_id: WINDOW_ID,
  constraint: "opening.within_length",
  related_ids: [WALL_ID],
  measure: { quantity: "opening_end", actual: 12.1, limit: 12.0, unit: "m" },
});

function version(issues: Issue[], report: unknown = null): Version {
  return versionSchema.parse({
    id: "5b0d4a1e-8c2f-4e3a-9d1b-2f6e7a8c9d10",
    project_id: "5b0d4a1e-8c2f-4e3a-9d1b-2f6e7a8c9d11",
    parent_version_id: null,
    number: 3,
    label: "Generated",
    source: "layout",
    schema_version: "1.1.0",
    engine_version: "layout@1.2.0",
    rules_profile: "generic-residential@1",
    seed: 0,
    model_hash: "0".repeat(64),
    summary: {
      storeys: 2, gross_floor_area_m2: 240, net_floor_area_m2: 200, rooms: 12, bedrooms: 3,
      bathrooms: 2, wcs: 0, garage: false, balconies: 1, terraces: 0, walls: 30, doors: 12,
      windows: 20, elements: 150,
    }, // prettier-ignore
    created_at: "2026-09-29T00:00:00Z",
    prompt: null,
    spec: null,
    model: {},
    report,
    issues,
  });
}

beforeEach(() => useSelectionStore.getState().select(null));

describe("ReportPanel design evaluation", () => {
  const report = {
    warnings: [],
    notes: [],
    metrics: {},
    evaluation: {
      score: 0.82,
      requirements: [
        {
          path: "/rooms/0/target_area_m2",
          kind: "room_area",
          label: "Living room: area",
          priority: "must",
          origin: "user_text",
          quote: "a 40 m2 living room",
          expected: "40 m² (36.0-44.0 m²)",
          delivered: "42.0 m²",
          met: true,
        },
        {
          path: "/rooms/1/adjacent_to/0",
          kind: "adjacent",
          label: "Kitchen next to Dining",
          priority: "should",
          origin: "user_text",
          quote: null,
          expected: "shared wall >= 0.9 m",
          delivered: "0.0 m shared",
          met: false,
        },
      ],
      criteria: [
        { key: "privacy", label: "Bedroom privacy", score: 1, weight: 3, explanation: "3 of 3" },
      ],
    },
    patterns: [
      {
        id: "pattern.open_plan_living",
        name: "Open-plan living, dining and kitchen",
        source: "buildai-layout-patterns@1",
        status: "draft",
        engine_support: "partial",
        reasons: ["open kitchen-living space"],
      },
    ],
  };

  it("shows requirements with their priority, the user's words and what was delivered", () => {
    render(<ReportPanel version={version([], report)} onClose={vi.fn()} />);
    expect(screen.getByText(/score 82\/100/)).toBeInTheDocument();
    expect(screen.getByText(/✓ Living room: area/)).toBeInTheDocument();
    expect(screen.getByText("required")).toBeInTheDocument();
    expect(screen.getByText(/“a 40 m2 living room”/)).toBeInTheDocument();
    expect(screen.getByText(/✗ Kitchen next to Dining/)).toBeInTheDocument();
    expect(screen.getByText("preference")).toBeInTheDocument();
  });

  it("labels draft patterns as experimental heuristics", () => {
    render(<ReportPanel version={version([], report)} onClose={vi.fn()} />);
    expect(screen.getByText("draft · experimental")).toBeInTheDocument();
    expect(screen.getByText(/not verified architectural standards/)).toBeInTheDocument();
  });

  it("names the generated footprint and why; a requested L that was not built is flagged", () => {
    const topology = {
      generated: "rectangular",
      requested: "l_shape",
      mandatory: false,
      searched: ["rect", "l"],
      reason: "an L-shaped footprint was requested as a preference",
      explanation: "no valid L-shaped layout met every mandatory requirement",
      candidates: { rect: 10, l: 0 },
      built_valid: { rect: 6 },
    };
    render(<ReportPanel version={version([], { ...report, topology })} onClose={vi.fn()} />);
    const section = screen.getByLabelText("Footprint");
    expect(section).toHaveTextContent("Rectangular");
    expect(section).toHaveTextContent("L-shaped requested (preference) — not generated");
    expect(section).toHaveTextContent(/no valid L-shaped layout/);
  });

  it("shows a generated L without a warning", () => {
    const topology = {
      generated: "l_shape",
      requested: "l_shape",
      mandatory: true,
      searched: ["l"],
      reason: "an L-shaped footprint is required",
      explanation: "an L-shaped footprint is required",
    };
    render(<ReportPanel version={version([], { ...report, topology })} onClose={vi.fn()} />);
    const section = screen.getByLabelText("Footprint");
    expect(section).toHaveTextContent("L-shaped · L-shaped requested (required)");
    expect(section).not.toHaveTextContent("not generated");
  });

  it("shows a generated T-shaped footprint", () => {
    const topology = {
      generated: "t_shape",
      requested: "t_shape",
      mandatory: true,
      searched: ["t"],
      reason: "a T-shaped footprint is required",
      explanation: "a T-shaped footprint is required",
      limitation: null,
    };
    render(<ReportPanel version={version([], { ...report, topology })} onClose={vi.fn()} />);
    const section = screen.getByLabelText("Footprint");
    expect(section).toHaveTextContent("T-shaped · T-shaped requested (required)");
    expect(section).not.toHaveTextContent("not generated");
    expect(section).not.toHaveTextContent("Not generated yet");
  });

  it("flags a preferred shape the engine cannot generate, with the reason", () => {
    const topology = {
      generated: "rectangular",
      requested: "u_shape",
      mandatory: false,
      searched: ["rect"],
      reason: "a U-shaped footprint was requested as a preference, but ...",
      explanation: "a rectangular footprint was used",
      limitation: "the layout engine cannot generate U-shaped footprints yet",
    };
    render(<ReportPanel version={version([], { ...report, topology })} onClose={vi.fn()} />);
    const section = screen.getByLabelText("Footprint");
    expect(section).toHaveTextContent(
      "Rectangular · U-shaped requested (preference) — not generated",
    );
    expect(section).toHaveTextContent(
      "Not generated yet: the layout engine cannot generate U-shaped footprints yet",
    );
  });

  it("renders older reports without an evaluation", () => {
    render(
      <ReportPanel
        version={version([], { warnings: [], notes: [], metrics: {} })}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText("Design evaluation")).not.toBeInTheDocument();
  });
});

describe("ReportPanel geometry checks", () => {
  it("says so when every element fits its geometry", () => {
    render(<ReportPanel version={version([])} onClose={vi.fn()} />);
    expect(screen.getByText("Geometry checks")).toBeInTheDocument();
    expect(
      screen.getByText(/every opening, wall, room, stair, slab and roof fits/),
    ).toBeInTheDocument();
  });

  it("lists geometric findings with their constraint and selects the element", async () => {
    render(<ReportPanel version={version([geometric])} onClose={vi.fn()} />);
    expect(screen.getByText("opening.within_length")).toBeInTheDocument();
    expect(screen.queryByText("Model checks")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /extends 0.100 m beyond/ }));
    expect(useSelectionStore.getState().selectedId).toBe(WINDOW_ID);
  });

  it("still accepts findings from before K2.5 (no constraint fields)", () => {
    const legacy = issueSchema.parse({
      severity: "warning",
      code: "ROOM_NOT_ON_SLAB",
      path: "/elements/3",
      message: "Balcony is not fully supported by a slab",
    });
    render(<ReportPanel version={version([legacy])} onClose={vi.fn()} />);
    expect(screen.getByText("Model checks")).toBeInTheDocument();
  });
});
