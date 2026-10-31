import { describe, expect, it } from "vitest";

import { demoModelJson } from "../test-fixtures";
import { ModelIntegrityError } from "./model-index";
import { ModelSchemaError, parseBuildingModel } from "./parse";

describe("parseBuildingModel (demo house)", () => {
  it("validates against the generated schema and indexes every element", () => {
    const index = parseBuildingModel(demoModelJson());
    expect(index.levels.map((l) => l.name)).toEqual(["Floor 1", "Floor 2"]);
    expect(index.elementsById.size).toBe(index.model.elements.length);
    const types = new Set(index.model.elements.map((e) => e.type));
    for (const t of ["wall", "room", "door", "window", "slab", "stair", "roof", "furniture"]) {
      expect(types).toContain(t);
    }
  });

  it("has unique ids across model, levels and elements", () => {
    const m = demoModelJson();
    const ids = [m.id, ...m.levels.map((l) => l.id), ...m.elements.map((e) => e.id)];
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("maps every opening to its host wall", () => {
    const index = parseBuildingModel(demoModelJson());
    const openings = index.model.elements.filter((e) => e.type === "door" || e.type === "window");
    expect(openings.length).toBeGreaterThan(20);
    for (const o of openings) expect(index.hostOf.get(o.id)?.type).toBe("wall");
  });

  it.each([
    [
      "negative wall length",
      (m: ReturnType<typeof demoModelJson>) => {
        const wall = m.elements.find((e) => e.type === "wall")!;
        (wall.dimensions as { length: number }).length = -1;
      },
    ],
    [
      "unknown element type",
      (m: ReturnType<typeof demoModelJson>) => {
        (m.elements[0] as { type: string }).type = "chimney";
      },
    ],
    [
      "unexpected property",
      (m: ReturnType<typeof demoModelJson>) => {
        (m.elements[0] as unknown as Record<string, unknown>).color = "red";
      },
    ],
    [
      "missing required field",
      (m: ReturnType<typeof demoModelJson>) => {
        delete (m.elements[0] as Partial<(typeof m.elements)[number]>).semantic_key;
      },
    ],
  ])("rejects a model with %s", (_, mutate) => {
    const m = demoModelJson();
    mutate(m);
    expect(() => parseBuildingModel(m)).toThrow(ModelSchemaError);
  });

  it("rejects duplicate ids and dangling relationships", () => {
    const dup = demoModelJson();
    dup.elements[1].id = dup.elements[0].id;
    expect(() => parseBuildingModel(dup)).toThrow(ModelIntegrityError);

    const dangling = demoModelJson();
    dangling.elements[0].relationships.push({
      kind: "adjacent_to",
      target_id: crypto.randomUUID(),
    });
    expect(() => parseBuildingModel(dangling)).toThrow(/does not exist/);
  });
});
