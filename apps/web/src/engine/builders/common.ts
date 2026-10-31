import type { Matrix4 } from "three";

import { type BuiltMesh, MeshBuilder } from "../geometry/mesh-builder";
import type { BuildingElement } from "../model/types";
import type { BuildContext, RenderDescriptor } from "./types";

/** 32-bit FNV-1a over a string, as 8 hex chars. Deterministic content keys for caching. */
export function fnv1a(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

/** Geometry cache key from everything that influences a part's geometry. */
export function contentKey(prefix: string, ...inputs: unknown[]): string {
  return `${prefix}:${fnv1a(JSON.stringify(inputs))}`;
}

export function descriptor(
  el: BuildingElement,
  part: RenderDescriptor["part"],
  geometryKey: string,
  mesh: BuiltMesh,
  matrix: Matrix4,
): RenderDescriptor {
  return {
    key: `${el.id}#${part}`,
    elementId: el.id,
    part,
    levelId: el.level_id,
    layer: el.layer,
    geometry: mesh.geometry,
    geometryKey,
    materials: mesh.materials,
    matrix,
    castShadow: part !== "glass",
  };
}

/**
 * Build (or reuse from the cache) one part of an element. `draw` receives an empty
 * MeshBuilder in element-local coordinates; parts that draw nothing are skipped.
 */
export function part(
  ctx: BuildContext,
  el: BuildingElement,
  name: RenderDescriptor["part"],
  key: string,
  matrix: Matrix4,
  draw: (mb: MeshBuilder) => void,
): RenderDescriptor[] {
  const fullKey = `${ctx.config.version}|${key}`;
  const mesh = ctx.cache.get(fullKey, () => {
    const mb = new MeshBuilder();
    draw(mb);
    return mb.build();
  });
  return mesh.materials.length === 0 ? [] : [descriptor(el, name, fullKey, mesh, matrix)];
}
