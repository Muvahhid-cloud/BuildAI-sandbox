import { describe, expect, it } from "vitest";

import { formatMoney } from "./format";

describe("formatMoney", () => {
  it("formats KZT with the tenge sign", () => {
    expect(formatMoney("45750000", "KZT", { minorUnits: 0 })).toBe("₸45,750,000");
  });

  it("is currency-agnostic", () => {
    expect(formatMoney("1234.5", "USD")).toBe("$1,234.50");
    // de-DE separates the symbol with a non-breaking space.
    expect(formatMoney("1234.5", "EUR", { locale: "de-DE" })).toBe("1.234,50 €");
  });

  it("formats decimal strings exactly, without float rounding", () => {
    expect(formatMoney("9007199254740993.01", "USD")).toBe("$9,007,199,254,740,993.01");
  });
});
