import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import completed from "../__fixtures__/generation-completed.json";
import { GenerationSummary } from "./GenerationSummary";

const withDeviations = {
  ...completed,
  checks: [
    ...completed.checks,
    { key: "wcs", label: "WCs", requested: "1", delivered: "0", met: false },
  ],
  warnings: [
    {
      severity: "warning",
      code: "AI_UNSUPPORTED_REQUEST",
      path: "",
      message: "Swimming pool — not supported by the layout engine yet",
      suggestion: null,
      rule_ref: null,
      element_id: null,
    },
  ],
};

describe("GenerationSummary", () => {
  it("shows what was built, how it compares and every assumption", () => {
    render(<GenerationSummary generation={completed as never} onDismiss={vi.fn()} />);
    const summary = screen.getByRole("region", { name: "Generation summary" });
    expect(summary).toHaveTextContent("Building generated successfully");
    expect(summary).toHaveTextContent(completed.specification.name);
    expect(summary).toHaveTextContent("Saved as version 1");
    expect(summary).toHaveTextContent("279.7");
    expect(summary).toHaveTextContent("All key requirements were met.");
    expect(summary).toHaveTextContent(`Assumptions (${completed.assumptions.length})`);
    expect(summary).toHaveTextContent(completed.assumptions[0]!.reason);
    expect(summary).toHaveTextContent("Offline mock interpreter (development)");
    expect(summary).toHaveTextContent("not a replacement for licensed");
  });

  it("never hides deviations", () => {
    render(<GenerationSummary generation={withDeviations as never} onDismiss={vi.fn()} />);
    expect(screen.getByLabelText("deviation")).toBeVisible();
    expect(screen.queryByText("All key requirements were met.")).toBeNull();
    const warnings = screen.getByText("Warnings (1)").parentElement!;
    expect(within(warnings).getByText(/Swimming pool/)).toBeVisible();
  });

  it("collapses to a pill and can be dismissed", async () => {
    const onDismiss = vi.fn();
    render(<GenerationSummary generation={completed as never} onDismiss={onDismiss} />);
    await userEvent.click(screen.getByRole("button", { name: "Collapse summary" }));
    expect(screen.queryByRole("region", { name: "Generation summary" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /show summary/ }));
    await userEvent.click(screen.getByRole("button", { name: "Close summary" }));
    expect(onDismiss).toHaveBeenCalled();
  });
});
