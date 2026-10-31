import { aiGenerationListSchema, aiGenerationSchema } from "@buildai/schema";
import { describe, expect, it } from "vitest";

// Real API responses captured from the running backend (MockAIProvider), so the generated
// validators are checked against what Pydantic actually serializes.
import completed from "./__fixtures__/generation-completed.json";
import clarification from "./__fixtures__/generation-clarification.json";
import history from "./__fixtures__/generation-history.json";
import { AI_STAGES, EXAMPLE_PROMPTS, isTerminal } from "./api";

describe("generated AI contracts", () => {
  it("validate a completed generation", () => {
    const parsed = aiGenerationSchema.parse(completed);
    expect(parsed.status).toBe("completed");
    expect(parsed.summary?.bedrooms).toBe(4);
    expect(parsed.checks.every((c) => c.met)).toBe(true);
    expect(parsed.specification?.targets.storeys).toBe(2);
    expect(parsed.assumptions.length).toBeGreaterThan(0);
  });

  it("validate a clarification and the history list", () => {
    expect(aiGenerationSchema.parse(clarification).clarification_questions).toHaveLength(3);
    expect(aiGenerationListSchema.parse(history).items[0]!.version_number).toBe(1);
  });

  it("reject malformed responses", () => {
    expect(aiGenerationSchema.safeParse({ ...completed, status: "done" }).success).toBe(false);
    expect(aiGenerationSchema.safeParse({ ...completed, id: "not-a-uuid" }).success).toBe(false);
  });
});

describe("AI helpers", () => {
  it("knows terminal states", () => {
    expect(isTerminal(aiGenerationSchema.parse(completed))).toBe(true);
    expect(isTerminal(aiGenerationSchema.parse({ ...completed, status: "running" }))).toBe(false);
    expect(isTerminal(undefined)).toBe(false);
  });

  it("mirrors the backend stages in order", () => {
    expect(AI_STAGES.map((s) => s.id)).toEqual([
      "interpreting",
      "validating",
      "repairing",
      "layout",
      "checking",
      "saving",
    ]);
    expect(EXAMPLE_PROMPTS[0]).toContain("280 square meters");
  });
});
