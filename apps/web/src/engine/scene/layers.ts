import type { Layer } from "../model/types";

export interface LayerDefinition {
  id: Layer;
  label: string;
  /** "available" layers can hold elements today; "planned" ones are reserved for later phases. */
  status: "available" | "planned";
  plannedPhase?: string;
}

/** Order = display order. Adding a discipline = adding its schema enum value + a row here. */
export const LAYER_DEFINITIONS: readonly LayerDefinition[] = [
  { id: "architecture", label: "Architecture", status: "available" },
  { id: "structure", label: "Structure", status: "available" },
  { id: "furniture", label: "Furniture", status: "available" },
  { id: "plumbing", label: "Plumbing", status: "planned", plannedPhase: "Phase 6" },
  { id: "electrical", label: "Electrical", status: "planned", plannedPhase: "Phase 6" },
  { id: "hvac", label: "HVAC", status: "planned", plannedPhase: "Phase 6" },
  { id: "fire_safety", label: "Fire safety", status: "planned", plannedPhase: "later" },
  { id: "landscaping", label: "Landscaping", status: "planned", plannedPhase: "later" },
];

export const ALL_LAYERS_VISIBLE: Readonly<Record<Layer, boolean>> = Object.fromEntries(
  LAYER_DEFINITIONS.map((l) => [l.id, true]),
) as Record<Layer, boolean>;
