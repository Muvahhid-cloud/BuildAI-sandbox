// BuildingModel -> SceneGraph (render descriptors + lookup maps). Pure and deterministic.
import { Box3, type BufferGeometry } from "three";

import { buildElement } from "../builders/registry";
import {
  DEFAULT_ENGINE_CONFIG,
  type EngineConfig,
  type GeometryCache,
  type RenderDescriptor,
} from "../builders/types";
import { computeWallJoins } from "../builders/wall-layout";
import type { ModelIndex } from "../model/model-index";
import type { Wall } from "../model/types";

interface CachedMesh {
  geometry: BufferGeometry;
  materials: string[];
}

/** Content-keyed geometry cache. A rebuild can adopt the previous cache (scene regeneration). */
export class ContentCache implements GeometryCache {
  private readonly entries = new Map<string, CachedMesh>();

  constructor(private previous?: ContentCache) {}

  /** Stop consulting the previous cache (called after a build so old caches can be freed). */
  seal(): void {
    this.previous = undefined;
  }

  get(key: string, create: () => CachedMesh): CachedMesh {
    let entry = this.entries.get(key) ?? this.previous?.entries.get(key);
    if (!entry) entry = create();
    this.entries.set(key, entry);
    return entry;
  }

  get size(): number {
    return this.entries.size;
  }

  geometries(): BufferGeometry[] {
    return [...new Set([...this.entries.values()].map((e) => e.geometry))];
  }
}

export interface SceneStats {
  elements: number;
  meshes: number;
  triangles: number;
  geometries: number;
}

export interface SceneGraph {
  readonly index: ModelIndex;
  readonly descriptors: readonly RenderDescriptor[];
  readonly byElement: ReadonlyMap<string, readonly RenderDescriptor[]>;
  /** Model-space (Z-up) bounds of everything built. */
  readonly bounds: Box3;
  readonly stats: SceneStats;
  readonly cache: ContentCache;
}

/**
 * Builds every element in id order (independent of input order), so the same model and
 * config always produce identical descriptors and buffers. Pass the previous scene to reuse
 * geometry of unchanged elements.
 */
export function buildScene(
  index: ModelIndex,
  config: EngineConfig = DEFAULT_ENGINE_CONFIG,
  previous?: SceneGraph,
): SceneGraph {
  const walls = index.model.elements.filter((e): e is Wall => e.type === "wall");
  const cache = new ContentCache(previous?.cache);
  const ctx = { index, joins: computeWallJoins(walls), config, cache };
  const sorted = [...index.model.elements].sort((a, b) => a.id.localeCompare(b.id));
  const descriptors: RenderDescriptor[] = [];
  const byElement = new Map<string, RenderDescriptor[]>();
  const bounds = new Box3();
  let triangles = 0;
  for (const el of sorted) {
    const parts = buildElement(el, ctx);
    byElement.set(el.id, parts);
    for (const d of parts) {
      descriptors.push(d);
      const box = d.geometry.boundingBox;
      if (box) bounds.union(box.clone().applyMatrix4(d.matrix));
      triangles += (d.geometry.getAttribute("position")?.count ?? 0) / 3;
    }
  }
  cache.seal();
  return {
    index,
    descriptors,
    byElement,
    bounds,
    stats: {
      elements: sorted.length,
      meshes: descriptors.length,
      triangles,
      geometries: cache.size,
    },
    cache,
  };
}

/** Dispose GPU-side resources of a scene that is no longer rendered. */
export function disposeScene(scene: SceneGraph, keep?: SceneGraph): void {
  const kept = new Set(keep?.cache.geometries() ?? []);
  for (const g of scene.cache.geometries()) if (!kept.has(g)) g.dispose();
}

/** Union of an element's descriptor bounds in model space (for highlight / framing). */
export function elementBounds(scene: SceneGraph, elementId: string): Box3 | null {
  const parts = scene.byElement.get(elementId);
  if (!parts || parts.length === 0) return null;
  const box = new Box3();
  for (const d of parts)
    if (d.geometry.boundingBox) box.union(d.geometry.boundingBox.clone().applyMatrix4(d.matrix));
  return box.isEmpty() ? null : box;
}
