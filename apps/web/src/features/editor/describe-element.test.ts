import { describe, expect, it } from "vitest";

import { parseBuildingModel } from "@/engine/model/parse";
import {
  bySemanticKey,
  demoIndex,
  generatedModelJson,
  typedDemoModelJson,
} from "@/engine/test-fixtures";

import { describeElement } from "./describe-element";

const index = demoIndex();
const rows = (key: string) => {
  const d = describeElement(bySemanticKey(index.model, key), index);
  return {
    d,
    row: (label: string) => d.sections.flatMap((s) => s.rows).find((r) => r.label === label)?.value,
  };
};

describe("describeElement", () => {
  it("describes a wall from the model (dimensions, material, identity)", () => {
    const wall = bySemanticKey(index.model, "wall:G-S");
    const { d, row } = rows("wall:G-S");
    expect(d.title).toBe("W-G01");
    expect(d.typeLabel).toBe("Exterior wall");
    expect(row("Length")).toBe("12 m");
    expect(row("Height")).toBe("2.8 m");
    expect(row("Thickness")).toBe("0.3 m");
    expect(row("Material")).toBe("Brick");
    expect(row("Left face finish")).toBe("Interior plaster (white)");
    expect(row("Load-bearing")).toBe("Yes");
    expect(row("ID")).toBe(wall.id);
    expect(row("Level")).toBe("Floor 1 (+0 m)");
  });

  it("names the facade of exterior walls and their openings (K3)", () => {
    expect(rows("wall:G-S").row("Facade")).toBe("Front");
    expect(rows("wall:G-N").row("Facade")).toBe("Rear");
    expect(rows("wall:G-S").row("Design system")).toBe("None (generic)");
  });

  it("shows a facade display color and window size class, not a material", () => {
    const doc = structuredClone(generatedModelJson());
    doc.design = {
      design_system: null,
      facade_color: { hex: "#e8c547", name: "yellow", source: "user" },
      windows: null,
    };
    for (const el of doc.elements) {
      if (el.type === "wall" && el.properties.wall_kind === "exterior") {
        el.properties.finish_right_color = "#e8c547";
      }
    }
    const colored = parseBuildingModel(doc);
    const wall = colored.model.elements.find(
      (e) => e.type === "wall" && e.properties.wall_kind === "exterior",
    )!;
    const d = describeElement(wall, colored);
    const row = (label: string) =>
      d.sections.flatMap((s) => s.rows).find((r) => r.label === label)?.value;
    expect(row("Right face display color")).toBe("#e8c547");
    expect(row("Facade color")).toBe("Yellow · #e8c547 (your requirement)");
    const window = colored.model.elements.find(
      (e) => e.type === "window" && e.properties.size_class !== null,
    )!;
    const w = describeElement(window, colored);
    expect(w.sections.find((s) => s.title === "Design")?.rows.map((r) => r.label)).toContain(
      "Size class",
    );
  });

  it("describes rooms with area and type", () => {
    const { d, row } = rows("room:living");
    expect(d.typeLabel).toBe("Room · Living");
    expect(row("Area")).toBe("29.6 m²");
    expect(row("Boundary")).toBe("4 points");
    expect(row("Floor finish")).toBe("Oak parquet");
  });

  it("lists relationships with clickable targets", () => {
    const { d } = rows("door:front");
    const rels = d.sections.find((s) => s.title.startsWith("Relationships"))!.rows;
    expect(rels.map((r) => r.label)).toEqual(["Hosted by", "Connects"]);
    expect(rels[0].value).toBe("W-G01 (Exterior wall)");
    expect(rels[1].targetId).toBe(bySemanticKey(index.model, "room:entrance").id);
  });

  it("resolves level references in stair properties", () => {
    const { row } = rows("stair:main");
    expect(row("From level")).toBe("Floor 1");
    expect(row("To level")).toBe("Floor 2");
    expect(row("Risers")).toBe("16");
  });
});

describe("describeElement: component types (schema 1.1.0)", () => {
  const typed = parseBuildingModel(typedDemoModelJson());
  const typedRow = (key: string, label: string) =>
    describeElement(bySemanticKey(typed.model, key), typed)
      .sections.flatMap((s) => s.rows)
      .find((r) => r.label === label)?.value;

  it("shows the type, family, assembly layers and catalog provenance", () => {
    const d = describeElement(bySemanticKey(typed.model, "wall:G-S"), typed);
    expect(d.sections.map((s) => s.title)).toContain("Assembly · Test exterior wall 300");
    expect(typedRow("wall:G-S", "Component type")).toBe("Test exterior wall");
    expect(typedRow("wall:G-S", "Type id")).toBe("type.wall.test_exterior_300");
    expect(typedRow("wall:G-S", "Family")).toBe("family.wall.basic");
    expect(typedRow("wall:G-S", "Catalog source")).toBe("test-types@1");
    expect(typedRow("wall:G-S", "Record hash")).toBe("cdcdcdcdcdcd");
    expect(typedRow("wall:G-S", "1. Structure")).toBe("Unspecified material · 0.28 m");
    expect(typedRow("wall:G-S", "2. Finish (interior)")).toBe("Interior plaster (white) · 0.02 m");
    expect(typedRow("wall:G-S", "Total thickness")).toBe("0.3 m");
    expect(typedRow("wall:G-S", "Face finishes")).toBe("Per wall (see properties)");
  });

  it("marks untyped elements", () => {
    expect(typedRow("room:living", "Component type")).toBe("None (untyped)");
    expect(rows("wall:G-S").row("Component type")).toBe("None (untyped)");
  });

  it("shows the ceiling assembly reference of rooms", () => {
    expect(rows("room:living").row("Ceiling assembly")).toBe("—");
  });

  it("refuses models whose elements reference unknown types", () => {
    const broken = typedDemoModelJson();
    broken.types = [];
    expect(() => parseBuildingModel(broken)).toThrow(/references unknown type/);
  });
});
