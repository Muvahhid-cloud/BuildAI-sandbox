import type { BufferGeometry, Matrix4 } from "three";

import type { ModelIndex } from "../model/model-index";
import type { BuildingElement, Layer } from "../model/types";
import type { WallJoin } from "./wall-layout";

export interface EngineConfig {
  /** Bumped whenever builder output changes for the same model (part of cache keys). */
  version: string;
}

export const DEFAULT_ENGINE_CONFIG: EngineConfig = { version: "engine@1" };

/**
 * One renderable part of one BuildingModel element. Every mesh in the viewer is created from
 * exactly one descriptor, and every descriptor points back to its element via `elementId`.
 */
export interface RenderDescriptor {
  /** Stable, unique: `${elementId}#${part}`. */
  key: string;
  elementId: string;
  part: "body" | "glass";
  levelId: string | null;
  layer: Layer;
  /** Geometry in element-local space. May be shared between descriptors (e.g. equal chairs). */
  geometry: BufferGeometry;
  geometryKey: string;
  /** Material key per geometry group. */
  materials: string[];
  /** Element-local -> model space (Z-up). */
  matrix: Matrix4;
  castShadow: boolean;
}

export interface GeometryCache {
  get(
    key: string,
    create: () => { geometry: BufferGeometry; materials: string[] },
  ): {
    geometry: BufferGeometry;
    materials: string[];
  };
}

export interface BuildContext {
  index: ModelIndex;
  joins: ReadonlyMap<string, WallJoin>;
  config: EngineConfig;
  cache: GeometryCache;
}

export class InvalidElementError extends Error {
  constructor(el: BuildingElement, reason: string) {
    super(`Cannot build ${el.type} "${el.name}" (${el.id}): ${reason}`);
    this.name = "InvalidElementError";
  }
}

/** Builders refuse non-finite or non-positive dimensions instead of emitting broken geometry. */
export function assertDimensions(el: BuildingElement): void {
  for (const [key, value] of Object.entries(el.dimensions)) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new InvalidElementError(el, `dimension "${key}" is not a finite number`);
    }
    const mayBeZero = key === "area" || key === "overhang";
    if (mayBeZero ? value < 0 : value <= 0) {
      throw new InvalidElementError(el, `dimension "${key}" must be ${mayBeZero ? ">= 0" : "> 0"}`);
    }
  }
  const p = el.position;
  if (![p.x, p.y, p.z, el.rotation.x, el.rotation.y, el.rotation.z].every(Number.isFinite)) {
    throw new InvalidElementError(el, "position/rotation must be finite");
  }
}
