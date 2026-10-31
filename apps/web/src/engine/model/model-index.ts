// Lookup structures over a BuildingModel + referential-integrity checks.
// The index is derived data: it never changes the model.
import type {
  AssemblySnapshot,
  BuildingElement,
  BuildingModel,
  Level,
  Opening,
  Room,
  TypeSnapshot,
  Wall,
} from "./types";

export interface ModelIndex {
  readonly model: BuildingModel;
  readonly elementsById: ReadonlyMap<string, BuildingElement>;
  readonly levelsById: ReadonlyMap<string, Level>;
  /** Levels sorted by index (floor 1 first). */
  readonly levels: readonly Level[];
  readonly elementsByLevel: ReadonlyMap<string, readonly BuildingElement[]>;
  /** Openings per host wall, sorted by offset then id. */
  readonly hostedOpenings: ReadonlyMap<string, readonly Opening[]>;
  /** Host wall per opening id. */
  readonly hostOf: ReadonlyMap<string, Wall>;
  /** Walls that `bounds` each room. */
  readonly wallsBounding: ReadonlyMap<string, readonly Wall[]>;
  /** Type and assembly snapshots by id (schema 1.1.0; empty for untyped models). */
  readonly typesById: ReadonlyMap<string, TypeSnapshot>;
  readonly assembliesById: ReadonlyMap<string, AssemblySnapshot>;
}

export class ModelIntegrityError extends Error {
  constructor(readonly issues: string[]) {
    super(`Building model failed integrity checks:\n- ${issues.join("\n- ")}`);
    this.name = "ModelIntegrityError";
  }
}

function push<K, V>(map: Map<K, V[]>, key: K, value: V) {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

export function indexModel(model: BuildingModel): ModelIndex {
  const issues: string[] = [];
  const seen = new Set<string>([model.id]);
  const levelsById = new Map<string, Level>();
  for (const level of model.levels) {
    if (seen.has(level.id)) issues.push(`duplicate id ${level.id} (level ${level.name})`);
    seen.add(level.id);
    levelsById.set(level.id, level);
  }
  const elementsById = new Map<string, BuildingElement>();
  for (const el of model.elements) {
    if (seen.has(el.id)) issues.push(`duplicate id ${el.id} (${el.type} ${el.name})`);
    seen.add(el.id);
    elementsById.set(el.id, el);
  }

  const elementsByLevel = new Map<string, BuildingElement[]>();
  const hostedOpenings = new Map<string, Opening[]>();
  const hostOf = new Map<string, Wall>();
  const wallsBounding = new Map<string, Wall[]>();

  const typesById = new Map<string, TypeSnapshot>(model.types.map((t) => [t.id, t]));
  const assembliesById = new Map<string, AssemblySnapshot>(model.assemblies.map((a) => [a.id, a]));
  for (const el of model.elements) {
    if (el.type_ref !== null && !typesById.has(el.type_ref)) {
      issues.push(`${el.type} ${el.name} references unknown type ${el.type_ref}`);
    }
    if (el.level_id === null || !levelsById.has(el.level_id)) {
      issues.push(`${el.type} ${el.name} references unknown level ${el.level_id}`);
    } else {
      push(elementsByLevel, el.level_id, el);
    }
    for (const rel of el.relationships) {
      const target = elementsById.get(rel.target_id);
      if (!target) {
        issues.push(`${el.name}: ${rel.kind} target ${rel.target_id} does not exist`);
        continue;
      }
      if (rel.kind === "bounds" && el.type === "wall" && target.type === "room") {
        push(wallsBounding, target.id, el);
      }
    }
    if (el.type === "door" || el.type === "window") {
      const hosts = el.relationships.filter((r) => r.kind === "hosted_by");
      const host = hosts.length === 1 ? elementsById.get(hosts[0].target_id) : undefined;
      if (host?.type !== "wall") {
        issues.push(`${el.type} ${el.name} must be hosted by exactly one wall`);
        continue;
      }
      hostOf.set(el.id, host);
      push(hostedOpenings, host.id, el);
    }
  }
  for (const list of hostedOpenings.values()) {
    list.sort((a, b) => a.position.x - b.position.x || a.id.localeCompare(b.id));
  }
  if (issues.length > 0) throw new ModelIntegrityError(issues);

  return {
    model,
    elementsById,
    levelsById,
    levels: [...model.levels].sort((a, b) => a.index - b.index),
    elementsByLevel,
    hostedOpenings,
    hostOf,
    wallsBounding,
    typesById,
    assembliesById,
  };
}

export function roomsOf(index: ModelIndex, levelId: string): Room[] {
  return (index.elementsByLevel.get(levelId) ?? []).filter((e): e is Room => e.type === "room");
}
