// Engine-facing aliases over the GENERATED building-model types (@buildai/schema).
import type {
  BuildingModel,
  Door,
  Furniture,
  Layer,
  Level,
  Railing,
  Roof,
  Room,
  Slab,
  Stair,
  Vec2,
  Vec3,
  Wall,
  Window,
} from "@buildai/schema";

export type {
  BuildingModel,
  Door,
  Furniture,
  Layer,
  Level,
  Railing,
  Roof,
  Room,
  Slab,
  Stair,
  Vec2,
  Vec3,
  Wall,
  Window,
};

export type BuildingElement = BuildingModel["elements"][number];
/** Type and assembly snapshots carried by the model (schema 1.1.0). */
export type TypeSnapshot = BuildingModel["types"][number];
export type AssemblySnapshot = BuildingModel["assemblies"][number];
export type ElementType = BuildingElement["type"];
export type Opening = Door | Window;
export type RoomType = Room["properties"]["room_type"];
export type ElementOfType<T extends ElementType> = Extract<BuildingElement, { type: T }>;

export const EPS = 1e-4; // meters, same as the API (primitives.py)
