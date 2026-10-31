import type { ErrorDetail } from "./schemas";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: ErrorDetail[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Validation messages keyed by top-level field name (from JSON-pointer paths). */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const d of this.details) {
      const field = d.path?.split("/")[1];
      if (field && !out[field]) out[field] = d.message;
    }
    return out;
  }
}
