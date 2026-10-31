// Turns a BuildingModel element into the rows of the properties panel.
// Everything shown comes from the model; only labels and units are presentation.
import { materialName } from "@/engine/materials/library";
import type { ModelIndex } from "@/engine/model/model-index";
import type { AssemblySnapshot, BuildingElement } from "@/engine/model/types";

export interface PropertyRow {
  label: string;
  value: string;
  /** Element id to select when the row is clicked (relationships). */
  targetId?: string;
  mono?: boolean;
}

export interface PropertySection {
  title: string;
  rows: PropertyRow[];
}

export interface ElementDescription {
  title: string;
  typeLabel: string;
  sections: PropertySection[];
}

const LENGTH_KEYS = new Set([
  "length", "thickness", "height", "width", "depth", "perimeter", "run_length", "rise_total",
  "overhang", "riser_height", "tread_depth", "rise", "post_spacing", "parapet_height",
]); // prettier-ignore
const AREA_KEYS = new Set(["area"]);
const ANGLE_KEYS = new Set(["pitch_deg"]);
const LABELS: Record<string, string> = {
  rise_total: "Total rise",
  run_length: "Run length",
  pitch_deg: "Pitch",
  finish_left_id: "Left face finish",
  finish_right_id: "Right face finish",
  frame_material_id: "Frame material",
  floor_material_id: "Floor finish",
  from_level_id: "From level",
  to_level_id: "To level",
  asset_id: "3D asset",
  load_bearing: "Load-bearing",
  ceiling_assembly_ref: "Ceiling assembly",
  finish_left_color: "Left face display color",
  finish_right_color: "Right face display color",
  size_class: "Size class",
};

/**
 * Semantic facade of an exterior wall from its outward normal (mirrors
 * apps/api/app/modules/building/facades.py): the street is on the model's -y side.
 */
export function facadeOfWall(el: BuildingElement): string | null {
  if (el.type !== "wall" || el.properties.wall_kind !== "exterior") return null;
  const nx = Math.sin(el.rotation.z);
  const ny = -Math.cos(el.rotation.z);
  if (Math.abs(ny) >= Math.abs(nx)) return ny < 0 ? "front" : "rear";
  return nx < 0 ? "left" : "right";
}

function hostWall(el: BuildingElement, index: ModelIndex): BuildingElement | undefined {
  const rel = el.relationships.find((r) => r.kind === "hosted_by");
  return rel ? index.elementsById.get(rel.target_id) : undefined;
}

/** Facade, display color, size class and design system of an element (K3). */
export function designSection(el: BuildingElement, index: ModelIndex): PropertySection[] {
  const rows: PropertyRow[] = [];
  const wall =
    el.type === "wall"
      ? el
      : el.type === "window" || el.type === "door"
        ? hostWall(el, index)
        : undefined;
  const facade = wall ? facadeOfWall(wall) : null;
  if (facade) rows.push({ label: "Facade", value: humanize(facade) });
  if (el.type === "wall" && el.properties.finish_right_color && facade) {
    const design = index.model.design?.facade_color;
    rows.push({
      label: "Facade color",
      value: `${design?.name ? humanize(design.name) + " · " : ""}${el.properties.finish_right_color}${
        design
          ? ` (${design.source === "user" ? "your requirement" : "design-system default"})`
          : ""
      }`,
    });
  }
  if (el.type === "window" && el.properties.size_class) {
    rows.push({ label: "Size class", value: humanize(el.properties.size_class) });
  }
  const system = index.model.design?.design_system;
  if (rows.length > 0 || system) {
    rows.push({
      label: "Design system",
      value: system ? `${system.name} (${system.source})` : "None (generic)",
    });
  }
  return rows.length > 0 ? [{ title: "Design", rows }] : [];
}

export function humanize(value: string): string {
  const s = value.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function formatMeters(v: number): string {
  return `${Number(v.toFixed(3))} m`;
}

function formatNumber(key: string, v: number): string {
  if (AREA_KEYS.has(key)) return `${Number(v.toFixed(2))} m²`;
  if (ANGLE_KEYS.has(key)) return `${Number(v.toFixed(1))}°`;
  if (LENGTH_KEYS.has(key)) return formatMeters(v);
  return String(v);
}

export function typeLabel(el: BuildingElement): string {
  switch (el.type) {
    case "wall":
      return `${humanize(el.properties.wall_kind)} wall`;
    case "room":
      return `Room · ${humanize(el.properties.room_type)}`;
    case "door":
      return `${humanize(el.properties.door_kind)} door`;
    case "window":
      return `${humanize(el.properties.window_kind)} window`;
    case "slab":
      return `${humanize(el.properties.slab_kind)} slab`;
    case "stair":
      return `${humanize(el.properties.stair_type)} stair`;
    case "roof":
      return `${humanize(el.properties.roof_type)} roof`;
    case "railing":
      return `${humanize(el.properties.railing_kind)} railing`;
    case "furniture":
      return `Furniture · ${humanize(el.properties.furniture_kind)}`;
  }
}

function formatProperty(key: string, value: unknown, index: ModelIndex): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return formatNumber(key, value);
  if (Array.isArray(value)) {
    if (key === "holes") return value.length === 0 ? "None" : `${value.length} hole(s)`;
    return `${value.length} points`;
  }
  if (typeof value === "string") {
    if (key.endsWith("level_id")) return index.levelsById.get(value)?.name ?? value;
    if (key.endsWith("_ref")) return index.assembliesById.get(value)?.name ?? value;
    if (key.endsWith("_color")) return value; // display color (#rrggbb), not a material
    if (key.endsWith("material_id") || key.startsWith("finish_")) return materialName(value);
    return humanize(value);
  }
  return JSON.stringify(value);
}

/** Layer rows of an assembly: "1. Structure" → "Unspecified · 0.3 m". */
export function assemblyRows(assembly: AssemblySnapshot): PropertyRow[] {
  return assembly.layers.map((layer, i) => ({
    label: `${i + 1}. ${humanize(layer.function)}${layer.side ? ` (${layer.side})` : ""}`,
    value: `${layer.material_id ? materialName(layer.material_id) : "Unspecified material"} · ${
      layer.function === "surface" ? "surface" : formatMeters(layer.thickness)
    }`,
  }));
}

/** The component type section: type, family, assembly layers and catalog provenance. */
export function typeSection(el: BuildingElement, index: ModelIndex): PropertySection[] {
  if (!el.type_ref) {
    return [
      { title: "Component type", rows: [{ label: "Component type", value: "None (untyped)" }] },
    ];
  }
  const type = index.typesById.get(el.type_ref);
  if (!type) {
    return [
      {
        title: "Component type",
        rows: [{ label: "Component type", value: `Missing (${el.type_ref})`, mono: true }],
      },
    ];
  }
  const sections: PropertySection[] = [
    {
      title: "Component type",
      rows: [
        { label: "Component type", value: type.name },
        { label: "Type id", value: type.id, mono: true },
        { label: "Family", value: type.family, mono: true },
        { label: "Catalog source", value: type.source, mono: true },
        { label: "Record hash", value: type.content_sha256.slice(0, 12), mono: true },
      ],
    },
  ];
  const assembly = type.assembly_id ? index.assembliesById.get(type.assembly_id) : undefined;
  if (assembly) {
    const rows = assemblyRows(assembly);
    rows.push({ label: "Total thickness", value: formatMeters(assembly.total_thickness) });
    if (el.type === "wall") {
      rows.push({ label: "Face finishes", value: "Per wall (see properties)" });
    }
    sections.push({ title: `Assembly · ${assembly.name}`, rows });
  }
  return sections;
}

export function describeElement(el: BuildingElement, index: ModelIndex): ElementDescription {
  const level = el.level_id ? index.levelsById.get(el.level_id) : undefined;
  const deg = (r: number) => `${Number(((r * 180) / Math.PI).toFixed(1))}°`;
  const { x, y, z } = el.position;
  const rot = el.rotation;

  const dimensions = Object.entries(el.dimensions).map(([k, v]) => ({
    label: LABELS[k] ?? humanize(k),
    value: formatNumber(k, v as number),
  }));
  const properties = Object.entries(el.properties).map(([k, v]) => ({
    label: LABELS[k] ?? humanize(k.replace(/_id$/, "")),
    value: formatProperty(k, v, index),
  }));
  const relationships = el.relationships.map((r) => {
    const target = index.elementsById.get(r.target_id);
    return {
      label: humanize(r.kind),
      value: target ? `${target.name} (${typeLabel(target)})` : r.target_id,
      targetId: target ? target.id : undefined,
    };
  });

  return {
    title: el.name,
    typeLabel: typeLabel(el),
    sections: [
      { title: "Dimensions", rows: dimensions },
      {
        title: "Material",
        rows: [
          { label: "Material", value: materialName(el.material_id) },
          { label: "Material id", value: el.material_id ?? "—", mono: true },
        ],
      },
      {
        title: "Placement",
        rows: [
          {
            label: "Level",
            value: level ? `${level.name} (+${formatMeters(level.elevation)})` : "—",
          },
          {
            label: "Position",
            value: `x ${formatMeters(x)} · y ${formatMeters(y)} · z ${formatMeters(z)}`,
          },
          {
            label: "Rotation",
            value:
              rot.x === 0 && rot.y === 0
                ? deg(rot.z)
                : `x ${deg(rot.x)} · y ${deg(rot.y)} · z ${deg(rot.z)}`,
          },
        ],
      },
      { title: "Properties", rows: properties },
      ...designSection(el, index),
      ...typeSection(el, index),
      { title: `Relationships (${relationships.length})`, rows: relationships },
      {
        title: "Identity",
        rows: [
          { label: "ID", value: el.id, mono: true },
          { label: "Semantic key", value: el.semantic_key, mono: true },
          { label: "Type", value: el.type, mono: true },
          { label: "Layer", value: humanize(el.layer) },
          { label: "Origin", value: humanize(el.origin) },
          { label: "Locked", value: el.locked ? "Yes" : "No" },
        ],
      },
    ],
  };
}
