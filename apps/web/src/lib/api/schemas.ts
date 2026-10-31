// Zod schemas for API DTOs (auth, projects).
// Building contracts (spec/model) are GENERATED into @buildai/schema from Pydantic (Phase 1);
// these small transport DTOs are hand-written and must mirror apps/api/app/modules/*/schemas.py.
import { z } from "zod";

export const userSchema = z.object({
  id: z.uuid(),
  email: z.string(),
  display_name: z.string(),
  created_at: z.string(),
});
export type User = z.infer<typeof userSchema>;

export const tokenResponseSchema = z.object({
  access_token: z.string().min(1),
  token_type: z.literal("bearer"),
  expires_in: z.number().int().positive(),
  user: userSchema,
});
export type TokenResponse = z.infer<typeof tokenResponseSchema>;

export const projectSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  description: z.string(),
  building_type: z.literal("single_family_house"),
  region_code: z.string(),
  currency: z.string().regex(/^[A-Z]{3}$/),
  rules_profile_id: z.string(),
  current_version_id: z.uuid().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Project = z.infer<typeof projectSchema>;

export const projectListSchema = z.object({ items: z.array(projectSchema) });

// --- Issues, versions, jobs (mirror app/modules/{building/issues,versions,jobs,generation}) ---

export const issueSchema = z.object({
  severity: z.enum(["error", "warning"]),
  code: z.string(),
  path: z.string(),
  message: z.string(),
  suggestion: z.string().nullable().optional(),
  rule_ref: z.string().nullable().optional(),
  element_id: z.uuid().nullable().optional(),
  // Geometric findings (Phase 3.5 K2.5): the violated constraint, other elements involved and
  // the measured value vs. its limit (app/modules/building/{issues,constraints}.py).
  constraint: z.string().nullable().optional(),
  related_ids: z.array(z.uuid()).optional(),
  measure: z
    .object({
      quantity: z.string(),
      actual: z.number(),
      limit: z.number(),
      unit: z.enum(["m", "m2"]),
    })
    .nullable()
    .optional(),
});
export type Issue = z.infer<typeof issueSchema>;

export const modelSummarySchema = z.object({
  storeys: z.number().int(),
  gross_floor_area_m2: z.number(),
  net_floor_area_m2: z.number(),
  rooms: z.number().int(),
  bedrooms: z.number().int(),
  bathrooms: z.number().int(),
  wcs: z.number().int(),
  garage: z.boolean(),
  balconies: z.number().int(),
  terraces: z.number().int(),
  walls: z.number().int(),
  doors: z.number().int(),
  windows: z.number().int(),
  elements: z.number().int(),
});
export type ModelSummary = z.infer<typeof modelSummarySchema>;

export const versionSummarySchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  parent_version_id: z.uuid().nullable(),
  number: z.number().int(),
  label: z.string(),
  source: z.string(),
  schema_version: z.string(),
  engine_version: z.string(),
  rules_profile: z.string(),
  seed: z.number().int().nullable(),
  model_hash: z.string(),
  summary: modelSummarySchema,
  created_at: z.string(),
});
export type VersionSummary = z.infer<typeof versionSummarySchema>;

export const versionListSchema = z.object({ items: z.array(versionSummarySchema) });

export const generationProvenanceSchema = z.object({
  generation_id: z.uuid(),
  generation_type: z.literal("building_generation"),
  provider: z.string(),
  model: z.string(),
  prompt_version: z.string(),
});

// Design Intelligence V1 (app/modules/building/evaluation.py): how the chosen layout answers
// the specification. Absent on reports written before layout@1.4.0.
export const requirementCheckSchema = z.object({
  path: z.string(),
  kind: z.string(),
  label: z.string(),
  priority: z.enum(["must", "should"]),
  origin: z.string(),
  quote: z.string().nullable(),
  expected: z.string(),
  delivered: z.string(),
  met: z.boolean(),
});
export const criterionScoreSchema = z.object({
  key: z.string(),
  label: z.string(),
  score: z.number(),
  weight: z.number(),
  explanation: z.string(),
});
export const designEvaluationSchema = z.object({
  requirements: z.array(requirementCheckSchema),
  criteria: z.array(criterionScoreSchema),
  score: z.number(),
});
export type DesignEvaluation = z.infer<typeof designEvaluationSchema>;
export const patternUseSchema = z.object({
  id: z.string(),
  name: z.string(),
  source: z.string(),
  status: z.string(),
  engine_support: z.string(),
  reasons: z.array(z.string()),
});
export type PatternUse = z.infer<typeof patternUseSchema>;
// Footprint topology, measured on the validated model (layout@1.5.0+).
export const topologySchema = z.object({
  generated: z.string(),
  requested: z.string().nullable(),
  mandatory: z.boolean(),
  searched: z.array(z.string()),
  reason: z.string(),
  explanation: z.string(),
  // Why the requested shape cannot be generated at all (layout@1.7.0+; absent before).
  limitation: z.string().nullable().optional(),
});
export type Topology = z.infer<typeof topologySchema>;

export const generationReportSchema = z.object({
  warnings: z.array(issueSchema),
  notes: z.array(z.string()),
  metrics: z.record(z.string(), z.unknown()),
  // Set when the version came from an AI generation (Phase 3).
  generation: generationProvenanceSchema.nullable().optional(),
  evaluation: designEvaluationSchema.nullable().optional(),
  patterns: z.array(patternUseSchema).optional(),
  topology: topologySchema.nullable().optional(),
});
export type GenerationReport = z.infer<typeof generationReportSchema>;

export const versionSchema = versionSummarySchema.extend({
  prompt: z.string().nullable(),
  // Building documents are validated by the generated schemas where they are used
  // (spec: form; model: building store), so they stay opaque here.
  spec: z.unknown().nullable(),
  model: z.unknown(),
  report: generationReportSchema.nullable(),
  issues: z.array(issueSchema),
});
export type Version = z.infer<typeof versionSchema>;

// --- Plan editing (mirror app/modules/editing/schemas.py and building/operations) ---

/** move_wall: shift a wall sideways; + = towards its left face (docs/building-model.md §5). */
export const moveWallOpSchema = z.object({
  op: z.literal("move_wall"),
  wall_id: z.uuid(),
  offset_m: z.number(),
});
export type MoveWallOp = z.infer<typeof moveWallOpSchema>;

/** resize_room: move side `edge` of the room's boundary; + = outwards (the room grows). */
export const resizeRoomOpSchema = z.object({
  op: z.literal("resize_room"),
  room_id: z.uuid(),
  edge: z.number().int().nonnegative(),
  delta_m: z.number(),
});
export type ResizeRoomOp = z.infer<typeof resizeRoomOpSchema>;

/** move_opening: put a door/window's start edge at `offset_m` along its wall, or another wall. */
export const moveOpeningOpSchema = z.object({
  op: z.literal("move_opening"),
  opening_id: z.uuid(),
  host_wall_id: z.uuid().optional(),
  offset_m: z.number().nonnegative(),
});
export type MoveOpeningOp = z.infer<typeof moveOpeningOpSchema>;

/** add_opening: a new door or window in a wall (docs/building-model.md §5.3). */
export const addOpeningOpSchema = z.object({
  op: z.literal("add_opening"),
  kind: z.enum(["door", "window"]),
  host_wall_id: z.uuid(),
  offset_m: z.number().nonnegative(),
  width_m: z.number().positive(),
  height_m: z.number().positive(),
  sill_m: z.number().nonnegative().optional(),
  door_kind: z.enum(["entrance", "interior", "sliding", "garage"]).optional(),
  swing: z.enum(["left", "right", "double", "sliding"]).optional(),
  window_kind: z.enum(["fixed", "casement", "sliding", "panoramic"]).optional(),
});
export type AddOpeningOp = z.infer<typeof addOpeningOpSchema>;

/** remove_element: doors and windows for now; the wall closes over the opening. */
export const removeElementOpSchema = z.object({
  op: z.literal("remove_element"),
  element_id: z.uuid(),
});
export type RemoveElementOp = z.infer<typeof removeElementOpSchema>;

/** resize_opening: new width/height (windows: sill); omitted offset keeps the centre (§5.4). */
export const resizeOpeningOpSchema = z.object({
  op: z.literal("resize_opening"),
  opening_id: z.uuid(),
  width_m: z.number().positive(),
  height_m: z.number().positive(),
  sill_m: z.number().nonnegative().optional(),
  offset_m: z.number().nonnegative().optional(),
});
export type ResizeOpeningOp = z.infer<typeof resizeOpeningOpSchema>;

/** remove_wall: an interior wall and its doors; merge_rooms joins the two rooms into one. */
export const removeWallOpSchema = z.object({
  op: z.literal("remove_wall"),
  wall_id: z.uuid(),
  merge_rooms: z.boolean().optional(),
});
export type RemoveWallOp = z.infer<typeof removeWallOpSchema>;

/** rename_room: a new, unique room name. */
export const renameRoomOpSchema = z.object({
  op: z.literal("rename_room"),
  room_id: z.uuid(),
  name: z.string().min(1).max(120),
});
export type RenameRoomOp = z.infer<typeof renameRoomOpSchema>;

/** set_room_type: the room's semantic type (its zone follows); the new type's rules apply. */
export const setRoomTypeOpSchema = z.object({
  op: z.literal("set_room_type"),
  room_id: z.uuid(),
  room_type: z.string(),
});
export type SetRoomTypeOp = z.infer<typeof setRoomTypeOpSchema>;

/** add_wall: divide a room with a new interior wall through a point (optional door). */
export const addWallOpSchema = z.object({
  op: z.literal("add_wall"),
  room_id: z.uuid(),
  direction: z.enum(["east_west", "north_south"]),
  x_m: z.number(),
  y_m: z.number(),
  new_room_type: z.string().optional(),
  door_width_m: z.number().positive().optional(),
  door_height_m: z.number().positive().optional(),
});
export type AddWallOp = z.infer<typeof addWallOpSchema>;

export type EditOperation =
  | MoveWallOp
  | ResizeRoomOp
  | MoveOpeningOp
  | AddOpeningOp
  | RemoveElementOp
  | ResizeOpeningOp
  | RemoveWallOp
  | RenameRoomOp
  | SetRoomTypeOp
  | AddWallOp;

export const editRejectionSchema = z.object({
  code: z.string(),
  message: z.string(),
  index: z.number().int().nullable(),
  element_id: z.uuid().nullable(),
  related_ids: z.array(z.uuid()),
  issues: z.array(issueSchema),
});
export type EditRejection = z.infer<typeof editRejectionSchema>;

export const editPreviewSchema = z.object({
  valid: z.boolean(),
  // Validated by the generated schema where it is used (building store / plan view).
  model: z.unknown().nullable(),
  summary: modelSummarySchema.nullable(),
  warnings: z.array(issueSchema),
  changed_ids: z.array(z.uuid()),
  rejection: editRejectionSchema.nullable(),
});
export type EditPreview = z.infer<typeof editPreviewSchema>;

export const jobSchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  kind: z.string(),
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  stage: z.string().nullable(),
  progress: z.number(),
  result: z.record(z.string(), z.unknown()).nullable(),
  error: z
    .object({
      code: z.string(),
      message: z.string(),
      details: z.array(z.object({ message: z.string() }).loose()),
    })
    .nullable(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
});
export type Job = z.infer<typeof jobSchema>;

export const specValidationSchema = z.object({
  valid: z.boolean(),
  issues: z.array(issueSchema),
  rules_profile: z.string(),
});
export type SpecValidation = z.infer<typeof specValidationSchema>;

export const errorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.array(z.object({ path: z.string().optional(), message: z.string() }).loose()),
  }),
});
export type ErrorDetail = z.infer<typeof errorEnvelopeSchema>["error"]["details"][number];
