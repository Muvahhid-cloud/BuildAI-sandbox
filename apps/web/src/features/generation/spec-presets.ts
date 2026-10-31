import { type BuildingSpecification, buildingSpecificationSchema } from "@buildai/schema";

// Reference specifications shared with the API's layout-engine tests (data/fixtures/specs).
import familyHouse from "@data/fixtures/specs/01-family-house-280.spec.json";
import bungalow from "@data/fixtures/specs/03-bungalow-150-terrace.spec.json";
import villa from "@data/fixtures/specs/05-three-storey-villa-360.spec.json";
import panoramic from "@data/fixtures/specs/07-panoramic-modern-200.spec.json";

export interface SpecPreset {
  id: string;
  label: string;
  spec: BuildingSpecification;
}

export const SPEC_PRESETS: SpecPreset[] = [
  { id: "family-280", label: "Family house · 2 floors · 280 m²", spec: familyHouse },
  { id: "panoramic-200", label: "Panoramic modern · 2 floors · 200 m²", spec: panoramic },
  { id: "bungalow-150", label: "Garden bungalow · 1 floor · 150 m²", spec: bungalow },
  { id: "villa-360", label: "Villa · 3 floors · 360 m²", spec: villa },
].map((p) => ({ ...p, spec: buildingSpecificationSchema.parse(p.spec) }));

export const ROOM_TYPE_LABELS: Record<string, string> = {
  bedroom: "Bedroom",
  bathroom: "Bathroom",
  wc: "WC",
  kitchen: "Kitchen",
  living: "Living room",
  dining: "Dining room",
  open_kitchen_living: "Kitchen & living",
  study: "Study",
  laundry: "Laundry",
  utility: "Utility room",
  storage: "Storage",
  plant_room: "Plant room",
};

export function emptySpec(): BuildingSpecification {
  return {
    schema_version: "1.0.0",
    building_type: "single_family_house",
    name: "New house",
    targets: { storeys: 2, gross_floor_area_m2: 180, floor_to_floor_height_m: 3.0 },
    rooms: [
      { key: "kitchen_living", type: "open_kitchen_living", count: 1 },
      { key: "bedroom", type: "bedroom", count: 3 },
      { key: "bathroom", type: "bathroom", count: 1 },
      { key: "wc", type: "wc", count: 1 },
    ],
  };
}

/** A room key not used yet in `spec`, derived from the room type. */
export function nextRoomKey(spec: BuildingSpecification, type: string): string {
  const used = new Set(spec.rooms.map((r) => r.key));
  if (!used.has(type)) return type;
  for (let i = 2; ; i++) if (!used.has(`${type}_${i}`)) return `${type}_${i}`;
}
