import { buildingModelSchema } from "@buildai/schema";
import { z } from "zod";

import { indexModel, type ModelIndex } from "./model-index";

export class ModelSchemaError extends Error {
  constructor(readonly details: string) {
    super(`Building model does not match the schema:\n${details}`);
    this.name = "ModelSchemaError";
  }
}

/** Validate untrusted JSON against the generated schema, then index + integrity-check it. */
export function parseBuildingModel(json: unknown): ModelIndex {
  const parsed = buildingModelSchema.safeParse(json);
  if (!parsed.success) throw new ModelSchemaError(z.prettifyError(parsed.error));
  return indexModel(parsed.data);
}
