// Public entry of @buildai/schema. The canonical schemas live in Pydantic
// (apps/api/app/modules/building); everything under ./generated and ../generated is produced
// by `pnpm schema`. See docs/building-model.md §8 and CLAUDE.md rule 7.
import { z } from "zod";

import aiGenerationJsonSchema from "../generated/ai-generation.schema.json";
import buildingModelJsonSchema from "../generated/building-model.schema.json";
import buildingSpecificationJsonSchema from "../generated/building-specification.schema.json";
import type { AIGenerationList, AIGenerationOut } from "./generated/ai-generation";
import type { BuildingModel } from "./generated/building-model";
import type { BuildingSpecification } from "./generated/building-specification";

export type * from "./generated/building-model";
export type {
  BuildingSpecification,
  RoomRequirement,
  SpecRoomType,
  RoomFeature,
  ArchitecturalStyle,
  InteriorStyle,
  WindowStyle,
  FacadeMaterial,
  FinishLevel,
  Targets,
  Site,
  Style,
  RoofSpec,
  Features,
  Garage,
  Balcony,
  Terrace,
  Budget,
  Assumption,
} from "./generated/building-specification";
export { buildingModelJsonSchema, buildingSpecificationJsonSchema };

type JsonSchemaInput = Parameters<typeof z.fromJSONSchema>[0];

/**
 * Runtime validator derived from the same JSON Schema as the TS types, so the two can't drift.
 * Structural validation only — cross-element invariants live in the API (validation.py) and
 * in the web engine's model index.
 */
export const buildingModelSchema = z.fromJSONSchema(
  buildingModelJsonSchema as JsonSchemaInput,
) as z.ZodType<BuildingModel>;

/** Tier-1 (structural) validator for specifications; tier-2 rules run on the API. */
export const buildingSpecificationSchema = z.fromJSONSchema(
  buildingSpecificationJsonSchema as JsonSchemaInput,
) as z.ZodType<BuildingSpecification>;

// --- AI generation API contracts (app/modules/ai/schemas/responses.py) ---
export type {
  AIGenerateRequest,
  AIGenerationList,
  AIGenerationOut,
  AIGenerationSummaryOut,
  GenerationErrorOut,
  GenerationOptions,
  RequirementCheck,
} from "./generated/ai-generation";
export { aiGenerationJsonSchema };

function aiDefinition(name: string): JsonSchemaInput {
  return {
    $ref: `#/$defs/${name}`,
    $defs: aiGenerationJsonSchema.$defs,
  } as unknown as JsonSchemaInput;
}

/** Validator for GET/POST generation responses. */
export const aiGenerationSchema = z.fromJSONSchema(
  aiDefinition("AIGenerationOut"),
) as z.ZodType<AIGenerationOut>;

/** Validator for a project's generation history. */
export const aiGenerationListSchema = z.fromJSONSchema(
  aiDefinition("AIGenerationList"),
) as z.ZodType<AIGenerationList>;
