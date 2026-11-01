# Building Model

Status: **Implemented for Phase 3.5 K2 (v0.6)**; schema 1.3.0 (V3 entrance canopy) · Canonical code: `apps/api/app/modules/building/` · Generated: `packages/schema/`

There are **two** schemas, deliberately separated:

| | `BuildingSpecification` | `BuildingModel` |
|---|---|---|
| Represents | What the client *wants* (intent, program) | What *is* designed (resolved elements) |
| Produced by | AI (or a form) | Layout engine + MEP generator + operations |
| Size | ~1–10 KB | ~0.5–3 MB |
| Coordinates | None | Everything positioned |
| Edited by | AI / user form, then re-layout | Typed operations |
| Source of truth for | Program & requirements | **Geometry, quantities, cost, rendering** |

After first generation, the **model** is the source of truth. The spec is kept as provenance and as input for full regeneration.

---

## 1. Conventions

| Convention | Value |
|---|---|
| Units | SI. Lengths **meters**, areas m², volumes m³, angles **radians**, money `Decimal` + ISO-4217 currency |
| Coordinate system | Right-handed, **Z-up**. Plan in X (east) / Y (north). Z = elevation above level 0 finished floor |
| Origin | Building origin at south-west corner of ground floor footprint |
| Precision | Geometry rounded to **1 mm** (3 decimals) on serialization; comparisons use `EPS = 1e-4` |
| IDs | UUID strings: uuid5 of the semantic key for generated/fixture elements, stable across regenerations where semantically the same object (see §7); uuid4 for rows created by the app |
| Enums | `snake_case` strings |
| Schema version | Semver string on every root document: `"schema_version": "1.0.0"` |

Three.js conversion (Y-up) happens in exactly one place: the viewer root group (`rotation.x = -π/2`). See [3d-engine.md](3d-engine.md).

---

## 2. BuildingSpecification (intent)

Implemented in `apps/api/app/modules/building/specification.py` (schema_version **1.1.0**; every 1.0.0 document is a valid 1.1.0 document with the same meaning — the 1.1.0 fields of §2.3 are optional and null means "not requested"). JSON Schema (validation shape: defaulted fields optional), TS types and a Zod validator are generated into `packages/schema` (`pnpm schema`). The spec contains **no geometry**: no coordinates, walls, element ids or levels' positions — unknown fields are rejected (`extra="forbid"`), vocabularies are closed enums. Reference specs: `data/fixtures/specs/*.spec.json`.

```jsonc
{
  "schema_version": "1.0.0",
  "building_type": "single_family_house",
  "name": "Modern family house",
  "description": "…",
  "targets": {
    "gross_floor_area_m2": 280,        // on wall centerlines, all storeys, garage/balconies/terraces excluded; null = derived
    "storeys": 2,                      // 1..3 (v1 scope)
    "floor_to_floor_height_m": 3.0,    // 2.4..4.0, default 3.0
    "max_footprint_width_m": null, "max_footprint_depth_m": null
  },
  "site": {                            // optional; the street is on the model's south side (-y)
    "plot_width_m": 20, "plot_depth_m": 30,
    "setback_front_m": 5, "setback_rear_m": 6, "setback_side_m": 1.5, "region_code": "KZ-ALA"
  },
  "style": {
    "architectural_style": "modern",   // modern|minimalist|contemporary|classic|traditional|scandinavian|industrial|mediterranean|luxury
    "interior_style": "minimalist",    // optional
    "roof": { "type": "flat", "pitch_deg": null },   // flat|gable|hip; pitch 5..45 (null = engine default 25°)
    "window_style": "large",           // standard|large|panoramic
    "facade_material": "render",       // render|brick|concrete|timber (mapped to material-library ids)
    "interior_finish_level": "standard",  // economy|standard|premium
    "design_system": null              // 1.1.0: e.g. "modern-minimal" (catalog; §2.3)
  },
  "design": {                          // 1.1.0 explicit design intent (§2.3); nulls = not requested
    "facade_color": "yellow",          // palette name or "#rrggbb": display color of the facade
    "windows": { "emphasis": "panoramic", "preferred_facades": ["rear"], "excluded_facades": ["front"] }
  },
  "rooms": [                           // 1..40 requirements; keys unique
    { "key": "living", "type": "living", "name": "Living room", "target_area_m2": 45, "level": 0,
      "open_to": ["kitchen"],          // open plan: no wall where they meet (or open onto the corridor between them)
      "faces": "rear" },               // 1.1.0: front|rear facade the room should face (§2.3)
    { "key": "kitchen", "type": "kitchen", "target_area_m2": 20, "adjacent_to": ["dining"] },
    { "key": "master_bedroom", "type": "bedroom", "target_area_m2": 22, "level": 1,
      "features": ["en_suite"] },      // en_suite | walk_in_closet: rooms reached through this bedroom
    { "key": "bedroom", "type": "bedroom", "count": 3, "min_area_m2": 12 }
  ],
  "features": {
    "garage": { "cars": 2 },           // 1..3, attached at the ground floor
    "balconies": [{ "level": 1, "attached_to": "master_bedroom", "side": "garden", "width_m": null, "depth_m": 1.5 }],
    "terrace": { "attached_to": "living", "width_m": null, "depth_m": 3.0 }   // ground floor, garden side
  },
  "budget": { "amount": "300000000.00", "currency": "KZT" },   // Decimal as string; a constraint only (nothing is costed in Phase 2)
  "assumptions": [{ "path": "/targets/floor_to_floor_height_m", "value": 3.0, "reason": "Not specified; residential default." }],
  "open_questions": ["Should the garage connect directly to the house interior?"]
}
```

Semantics:

- `level` is a 0-based storey index (0 = ground floor); `null` lets the engine choose.
- `count` expands one requirement into instances `bedroom_1`, `bedroom_2`, … (the instance key is the room's semantic key suffix, `room:bedroom_2`).
- Areas are per room, on wall centerlines. Rooms without `target_area_m2` get engine defaults (layout `LayoutConfig.default_areas`), scaled to fill the requested floor area (service rooms by at most ±30 %, living spaces and bedrooms up to 2×).
- `assumptions` / `open_questions` are filled by the AI interpreter (every inferred value is an assumption with its JSON pointer and reason) and shown to the user.

### 2.0 Produced by AI (Phase 3)

The schema is unchanged by Phase 3 (still 1.0.0): the AI must produce exactly this document. Models answer with a `SpecificationDraft` (`app/modules/ai/schemas/generation.py`) that wraps it with `outcome` (`specification` | `clarification`), `understanding`, `clarification_questions`, `conflicts` and `unsupported_requests`; the draft is validated like any untrusted input (tier 1 + tier 2, one repair call at most — docs/ai-pipeline.md §5). Requests the vocabulary cannot express are reported, never approximated silently; the closed vocabularies above are also what the prompt offers (generated from the enums).

`building/requirements.py` (pure) derives the key requirements of a spec (`SpecFacts`: storeys, floor area, bedrooms, bathrooms incl. en-suites, WCs, garage cars, balconies, terrace) and compares them with a generated model's `ModelSummary` (`RequirementCheck`: requested → delivered, met). It powers the "requested vs generated" summary and detects when an AI repair changed the user's program.

### 2.3 Design intent and design systems (1.1.0, Phase 3.5 K3)

Code: `building/design.py` (precedence, effective values, tier-2 checks), `building/facades.py`, `building/appearance.py`, `building/design_checks.py` (model checks).

**Facades** are semantic and derived from geometry, never stored: the street is on the model's south side (−y), so `front` = street/entrance side (outward normal −y), `rear` = garden/backyard (+y), `left`/`right` as seen from the street (−x/+x). An exterior wall's facade is the direction of its outward normal (exterior walls run counter-clockwise, outward normal `(sin θ, −cos θ)`). Words map through one fixed table (`FACADE_SYNONYMS`): backyard, back yard, garden, yard, back, rear → rear; street, entrance, road, front → front.

**Colors** are display appearance only: a palette name (`appearance.PALETTE`: white, off_white, warm_beige, sand, yellow, ochre, terracotta, brick_red, light_grey, grey, anthracite, black, sage_green, light_blue, timber_brown) or `#rrggbb`. A color never changes the facade material (a yellow render wall is still `exterior_wall`) and carries no thermal, structural, fire or cost meaning.

| Field | Meaning | Engine effect |
|---|---|---|
| `design.facade_color` | display color of the exterior wall faces | every exterior wall's exterior face (`finish_right_color`), incl. the garage |
| `design.windows` | `emphasis` (large/panoramic) on `preferred_facades`, never on `excluded_facades` | per-facade window size class (§3.3 `size_class`); preferred facades are glazed first |
| `rooms[].faces` | front or rear | the room is placed in the street- or garden-side band (left/right: `FACADE_PREFERENCE_INVALID`) |
| `style.design_system` | an approved design system (docs/knowledge.md §3.5) | its types, finishes, furniture palette and default facade color |

**Precedence** (deterministic, `building/design.py`): (1) explicit values in the spec; (2) the selected design system's allow-lists — a value outside them is a `DESIGN_OPTION_CONFLICT` error with compatible alternatives, never silently changed; (3) the system's defaults for what the spec leaves null (facade color, finishes, furniture palette, component types); (4) generic defaults (the pre-K3 behaviour). Window sizes per facade (`resolve_window_preferences`): preferred → emphasis; excluded → standard; others → `style.window_style` (capped to standard when that equals the emphasis, so the emphasis stays concentrated).

Tier-2 codes: `APPEARANCE_INVALID` (unknown color), `WINDOW_FACADE_CONFLICT` (a facade both preferred and excluded), `FACADE_PREFERENCE_INVALID` (duplicate facades, a room facing left/right), `DESIGN_SYSTEM_UNKNOWN`, `DESIGN_SYSTEM_NOT_APPROVED` (draft or incomplete system), `DESIGN_OPTION_CONFLICT`. Requested-vs-delivered checks (`requirements.design_checks`) read the generated model: facade color, emphasised windows per preferred facade, none on excluded facades, room orientation.

### 2.4 Priorities, ranges, separation and requirement traces (1.2.0, Design Intelligence V1)

Code: `building/specification.py`, `building/intent.py` (meaning of traces, tier-2 checks), `building/evaluation.py` (checked on the generated model). Additive: every field is optional/empty by default, so 1.0.0 and 1.1.0 documents keep their meaning.

| Field | Meaning | Engine effect |
|---|---|---|
| `rooms[].max_area_m2` | upper end of the permissible range (with `min_area_m2`) | search penalty outside the range; requirement check; `LAYOUT_AREA_DEVIATION` when missed |
| `rooms[].separate_from` | rooms that must not share a wall with this one | search penalty when neighbours (bands, order); requirement check; `LAYOUT_SEPARATION` when missed |
| `design.priorities` | ordered subset of `daylight, privacy, garden_connection, compactness, open_plan` | ×3 weight of the matching evaluation criterion; selects layout patterns (docs/knowledge.md §3.6) |
| `design.footprint_shape` | `rectangular` \| `l_shape` \| `t_shape` \| `u_shape` \| `courtyard` (null = the engine chooses; values beyond L added in V1.3, still spec 1.2.0 — additive) | topology selection (docs/3d-engine.md §16.10–16.12); checked against the shape measured on the model; what can be generated is `building/footprint.py CAPABILITIES` (L and T one storey; U and courtyard not yet): otherwise `SPEC_FOOTPRINT_UNSUPPORTED`, an error if MUST (refused with the reason, never a rectangle), a warning if SHOULD |
| `requirements[]` | `{path, priority: must\|should, origin: user_text\|form\|assumption, quote}` per spec value | MUST = hard (candidate rejected; generation fails with `LAYOUT_REQUIREMENTS_UNMET` rather than relaxing it); SHOULD = scored and reported |

**Permissible area range** of an explicit room target: `[min_area_m2, max_area_m2]` where given, else target ± 10 % (`intent.DEFAULT_AREA_TOLERANCE`, an evaluation default, not a rule; the rules profile still bounds every room from below). Before 1.2.0 a deviation was only reported above 15 % (decision 11); now every explicit target outside its range is reported.

**Requirement traces** name the value they govern by JSON pointer. MUST is accepted only where the engine can check it on the model: `/rooms/<i>/target_area_m2`, `/rooms/<i>/adjacent_to/<j>`, `/rooms/<i>/open_to/<j>`, `/rooms/<i>/separate_from/<j>`, `/rooms/<i>/faces`, `/design/windows`, `/design/footprint_shape`. Values without a trace are SHOULD. Tier-2 codes: `SPEC_REQUIREMENT_PATH` (pointer names nothing), `SPEC_REQUIREMENT_UNSUPPORTED` (MUST on a value the engine cannot enforce), `SPEC_REQUIREMENT_CONFLICT` (a room both next to and separate from another), `SPEC_UNKNOWN_ROOM_KEY` (separate_from), `SPEC_AREA_BELOW_MINIMUM` (max below the rules minimum), `SPEC_RANGE_WITHOUT_TARGET` (warning).

**Evaluation** (`building/evaluation.py`, derived, never stored in the model): every requirement → met/not met with expected vs delivered and the user's words; soft criteria in [0, 1] with weights and an explanation: requested room sizes, preferences met, circulation share, room proportions, daylight (window or glazed door), bedroom privacy, garden connection, kitchen–dining–living sequence, footprint compactness. "Next to" = ≥ 0.9 m shared boundary; "open to" = ≥ 0.9 m without a wall, directly or facing each other across an open corridor stretch; "apart" = < 0.05 m shared. It does not evaluate structure, code compliance, acoustics, sun orientation or cost. The result is stored in the version's generation report.

### 2.1 Room types (v1)

A spec may request: `bedroom, bathroom, wc, kitchen, living, dining, open_kitchen_living, study, laundry, utility, storage, plant_room` (+ `en_suite`, `walk_in_closet` via bedroom `features`). The engine adds circulation (`entrance` hall, `corridor`, `staircase`/landing), `garage`, `balcony` and `terrace` rooms from `features`. `hall` exists in the model vocabulary but is not generated yet.

### 2.2 Spec validation (three tiers)

| Tier | Where | Examples | Result |
|---|---|---|---|
| 1. Structural | Pydantic (`specification.py`); the web form runs the generated Zod validator first | types, enums, ranges (`1 ≤ storeys ≤ 3`), unique room keys, no unknown fields | 422 `VALIDATION_ERROR` with JSON-pointer paths |
| 2. Semantic | `rules/spec_checks.py` against the project's `BuildingRulesProfile` | target area ≥ rule minimum; Σ room minimums ≤ 0.85 × GFA; ≥ 1 bathroom (or en-suite); `level` < storeys; `adjacent_to`/`open_to`/`attached_to` keys exist; open plan only between living/dining/kitchen/study; features only on bedrooms; clear height ≥ `ceiling.min_clear_height_m`; storey height ≤ one straight flight; balconies need an upper floor; plot/setbacks leave enough buildable area | errors block generation (422 `SPEC_INVALID`); warnings (no kitchen, no bedroom, feature on a service room) are shown |
| 3. Feasibility | layout engine | stair fits the street-side band; rooms fit their bands at minimum widths; footprint fits the plot/max footprint; every room reachable | job fails with `LAYOUT_INFEASIBLE` and reasons |

Every issue has the same shape (`building/issues.py`): `{ severity, code, path (JSON pointer), message, suggestion?, rule_ref?, element_id? }`. `rule_ref` is e.g. `generic-residential@1:rooms.bedroom.min_area_m2`.

---

## 3. BuildingModel (resolved)

Implemented in `apps/api/app/modules/building/{primitives,enums,elements,types,design,model}.py` (schema_version **1.3.0**; 1.0.0, 1.1.0 and 1.2.0 documents are upgraded on read, §8). JSON Schema, TS types and the Zod validator in `packages/schema` are generated from these classes (`pnpm schema`).

```jsonc
{
  "schema_version": "1.3.0",
  "id": "uuid",                       // the "building" object id
  "building": { "name": "Demo family house", "building_type": "single_family_house", "description": "…" },
  "units": "m",
  "engine_version": "layout@1.2.0",   // "fixture@1" for the hand-authored demo
  "seed": 0,                          // layout seed (null for fixtures)
  "levels": [ Level, ... ],           // the "floor" objects
  "elements": [ Element, ... ],       // discriminated union on "type"
  "metadata": { "source": "fixture" | "layout" | "operations", "generator": "layout@1.2.0 · rules generic-residential@1" },
  "types": [ TypeSnapshot, ... ],     // 1.1.0: every type an element refers to (sorted by id; §3.5)
  "assemblies": [ AssemblySnapshot, ... ],  // 1.1.0: every assembly a type or room refers to
  "design": DesignRecord | null       // 1.2.0: design system snapshot + effective intent (§3.6)
}
```

The spec a model was generated from is stored next to it in the project version (not inside the model). Versions produced by the AI pipeline have `source = "ai_generation"`, keep the user's `prompt`, and their generation report carries `generation` provenance (generation id, `building_generation`, provider, model, prompt version). `systems` (MEP) is added as a minor schema version in Phase 6.

### 3.1 Level ("floor")

```jsonc
{ "id": "uuid", "name": "Floor 1", "index": 0, "elevation": 0.0, "height": 3.0, "semantic_key": "level:L0" }
```

`elevation` = finished floor level above level 0; `height` = floor-to-floor. All lengths are meters (no `_m` suffixes in the model).

### 3.2 Element base (every object)

```jsonc
{
  "id": "uuid",                        // stable: uuid5(namespace, semantic_key) for fixtures
  "type": "wall",                      // discriminator
  "name": "W-G01",
  "layer": "structure",                // architecture | structure | furniture | plumbing | electrical | hvac | fire_safety | landscaping
  "level_id": "uuid",
  "position": { "x": 0, "y": 0, "z": 0 },   // element-local anchor, meaning per type (below)
  "rotation": { "x": 0, "y": 0, "z": 0 },   // radians, XYZ Euler; most elements use z (yaw)
  "dimensions": { ... },               // typed per element type
  "material_id": "brick" | null,       // id in data/materials/library.json
  "properties": { ... },               // typed per element type (no free-form bag)
  "relationships": [ { "kind": "bounds", "target_id": "uuid" } ],
  "origin": "generated" | "user",
  "locked": false,
  "semantic_key": "wall:G-S",
  "type_ref": "type.wall.generic_exterior_300" | null   // 1.1.0: id of a TypeSnapshot (§3.5)
}
```

Absolute elevation = `level.elevation + position.z`. Polygon properties (room boundary, slab/roof outline) are relative to `position`, rotated by `rotation.z`. All models are `extra="forbid"`; lengths are rounded to 1 mm, areas to 0.01 m², angles to 1e-6 rad on validation.

### 3.3 Element types (implemented in schema 1.0.0; unchanged in 1.1.0)

| type | usual layer | position = | dimensions | properties |
|---|---|---|---|---|
| `wall` | structure (load-bearing exterior) / architecture | axis start; `rotation.z` = axis direction | `length, thickness, height` | `wall_kind` (exterior/interior/partition), `alignment` (center/left/right), `load_bearing`, `finish_left_id`, `finish_right_id` (left = +normal side; exterior walls are authored CCW so left = interior), `finish_left_color`, `finish_right_color` (1.2.0: display color `#rrggbb` of that face or null; appearance only) |
| `door` | architecture | host-wall-local: x = offset of the start edge, z = 0 | `width, height, thickness` | `door_kind` (entrance/interior/sliding/garage), `swing` (left/right/double/sliding), `frame_material_id` |
| `window` | architecture | host-wall-local: x = offset, z = sill height | `width, height` | `window_kind` (fixed/casement/sliding/panoramic), `frame_material_id`, `mullions`, `size_class` (1.2.0: standard/large/panoramic for main windows of habitable rooms; null for service/stair windows and older models) |
| `room` | architecture | boundary origin | `area, perimeter, height` (validated against the boundary) | `room_type`, `zone`, `boundary` (CCW, rectilinear, wall centerlines), `floor_material_id` |
| `slab` | structure (a canopy: architecture) | outline origin; **top face** at `position.z` | `thickness, area` (outline − holes) | `slab_kind` (ground/floor/balcony; **canopy** since 1.3.0: an entrance canopy cantilevered from the facade over an entrance door, top face above the door head and below the next level — not a floor, carries nothing, no `supports` relationship and no type; constraint `slab.canopy`, §4.1), `outline`, `holes` |
| `stair` | structure | bottom corner at the first riser; flight along local +x, width along local +y | `width, run_length, rise_total` | `stair_type` (straight), `risers`, `riser_height`, `tread_depth`, `from_level_id`, `to_level_id` |
| `roof` | architecture | outline origin; `position.z` = top of covering at the eaves | `thickness, overhang` | `roof_type` (flat/gable/hip), `outline` (eaves, rectangle for pitched), `pitch_deg`, `ridge_axis`, `parapet_height` |
| `railing` | architecture | start of the base line; runs along local +x | `length, height` | `railing_kind` (glass/bars), `rise` (0 = level, > 0 = sloped/stair), `post_spacing` |
| `furniture` | furniture | base center on the floor; front faces local −y | `width, depth, height` | `furniture_kind` (18 kinds: sofa, armchair, coffee_table, tv_unit, dining_table, chair, bed, nightstand, wardrobe, bookshelf, desk, kitchen_counter, kitchen_island, fridge, toilet, basin, bathtub, shower), `asset_id` (GLB/glTF catalog id, null = procedural) |

Planned types (later phases): `column`, `beam` (structure); `pipe_segment`, `fixture`, `equipment` (plumbing); `conduit_run` (electrical); `duct_segment`, `terminal` (HVAC); `system` objects for MEP networks.

Wall derived geometry (not stored): `start = position`, `end = position + length·(cos θ, sin θ)`, `θ = rotation.z`.

### 3.4 Relationships

Directed, typed edges stored on the source element; targets must exist (API validator + web index).

| kind | from → to | meaning |
|---|---|---|
| `hosted_by` | door/window → wall | the opening lives in that wall (exactly one) |
| `bounds` | wall → room | the wall's axis runs along the room's boundary |
| `adjacent_to` | room → room | the rooms share a boundary edge (with or without a wall) |
| `connects` | door → room | rooms joined by the door (2, or 1 for exterior doors) |
| `supports` | wall → slab/roof | load path (ground facades carry the floor slab, upper facades the roof) |
| `located_in` | furniture/stair/railing → room | placement |
| `serves`, `connected_to`, `part_of_system` | MEP (Phase 6) | reserved |

Level membership is `level_id` (not a relationship).

Rooms additionally carry `properties.ceiling_assembly_ref` (1.1.0, `null` = none): an assembly of kind `ceiling`. Nothing assigns ceilings yet.

### 3.5 Types and assemblies (1.1.0, Phase 3.5 K2)

Code: `building/types.py`. A model is **self-contained**: every type or assembly an element refers to is copied into the model when it is generated, with the catalog record it came from (`source`, e.g. `buildai-generic-types@1`) and that record's `content_sha256`. Versions stay reproducible when the catalog moves on.

```jsonc
// TypeSnapshot
{ "id": "type.door.generic_interior", "family": "family.door.hinged", "name": "Interior door",
  "params": { "element_type": "door", "door_kind": "interior", "height": 2.1, "thickness": 0.06,
              "material_id": "wood", "frame_material_id": "window_frame", "default_width": 0.9 },
  "assembly_id": null, "source": "buildai-generic-types@1", "content_sha256": "…" }
// AssemblySnapshot (walls: layers exterior→interior; floors/roofs/ceilings: top→bottom)
{ "id": "assembly.wall.generic_exterior_300", "kind": "wall", "name": "Generic exterior wall 300",
  "layers": [ { "function": "structure", "material_id": null, "thickness": 0.3, "side": null } ],
  "total_thickness": 0.3, "source": "buildai-generic-types@1", "content_sha256": "…" }
```

- `params` is typed per element type (wall, slab, roof, door, window, stair, railing). **Fixed** parameters must match every element of the type; **defaults** (`default_*`, `glazing_ratio`, `mullion_spacing`, `width_per_car`) are the design values the layout engine starts from and an element may differ (a door narrowed to fit a short wall, a window lowered under a lintel).
- Walls, slabs and roofs name an assembly of kind wall / floor / roof; their `thickness` equals the assembly's `total_thickness`.
- `Layer`: `function` (structure, insulation, membrane, air_gap, screed, finish, surface), `material_id` (material library id; `null` = unspecified), `thickness` (0 only for `surface`), optional `side`. Assemblies are the quantities basis for Phase 4 (volume per layer, finish areas); they carry no item codes or prices.
- Wall face finishes stay on the wall instance (`finish_left_id` / `finish_right_id`): they depend on the rooms on each side, not on the wall type.
- Untyped elements (`type_ref: null`) are valid; 1.0.0 documents upgrade to untyped 1.1.0.
- `TYPE_ROLES` names the roles the layout engine fills (`wall.exterior`, `door.wet_room`, `window.stair`, …); a catalog role mapping assigns one type per role (docs/knowledge.md §3.4).

### 3.6 Design record (1.2.0, Phase 3.5 K3)

`BuildingModel.design` (`building/design.py DesignRecord`, null = generic design without intent) makes a model self-contained for design: `design_system` is a `DesignSystemSnapshot` (id, name, catalog `source` pack, record `content_sha256`, allow-lists, defaults, finishes, furniture palette and the `type_ids` its role mapping resolved to — copied, like type snapshots, so stored versions never depend on the future catalog); `facade_color` is the effective color `{hex, name, source: user|design_system}`; `windows` is the effective window intent `{emphasis, preferred_facades, excluded_facades, source}`. Model checks (`building/design_checks.py`, part of `validate_model` so the layout search skips a violating candidate): `WINDOW_FACADE_CONFLICT` (error, emphasised window on an excluded facade), `WINDOW_PREFERENCE_UNSATISFIABLE` (warning, a preferred facade got no emphasised window), `DESIGN_OFF_SYSTEM` (error, a type outside the system's `type_ids` or a generic finish/furniture material the system replaces), `APPEARANCE_INVALID` (error, an exterior face color that differs from the record). The layout engine adds `ROOM_FACADE_UNMET` (warning) when a room could not reach the facade it should face. `ModelSummary` (derived) reports `facade_colors`, `windows_by_facade` (size class counts) and `rooms_on_facade`.

---

## 4. Invariants (enforced by `building/validation.py`)

Errors (model rejected):

1. Unique ids across model, levels and elements; unique semantic keys; level indices 0..n-1.
2. Every `level_id` and relationship target exists.
3. Every material id (element, finishes, frames, floor finishes) exists in the material library (when the library is supplied).
4. Doors/windows and walls: the geometric invariants of §4.1 (hosting, placement inside the wall and clear of junctions, no overlaps, …).
5. Wall height ≤ level height (`WALL_TOO_TALL`, now in §4.1).
6. Room boundaries: CCW, rectilinear, simple; `area`/`perimeter` match the boundary; rooms on a level do not overlap.
7. Slabs: CCW simple outline, holes inside, `area` = outline − holes. Pitched roofs need a rectangular outline.
8. Stairs: `risers × riser_height ≈ rise_total` and `(risers − 1) × tread_depth ≈ run_length` (±0.5 mm rounding per riser); start on `from_level`, reach the next level; `rise_total` = level difference.
9. Railings no steeper than 45°. Pydantic: all dimensions finite and > 0 (area/overhang ≥ 0).
10. Types (`building/type_validation.py`): unique snapshot ids (`TYPE_SNAPSHOT_DUPLICATE`); every `type_ref` is carried by the model (`TYPE_REF_UNKNOWN`) and is a type for the element's type (`TYPE_ELEMENT_MISMATCH`).
11. A wall/slab/roof type names a carried assembly of the right kind (`TYPE_ASSEMBLY_UNKNOWN`); other types name none (`TYPE_ASSEMBLY_UNEXPECTED`); an assembly's layers add up to its total (`ASSEMBLY_THICKNESS_SUM`); layer and type materials exist (`UNKNOWN_MATERIAL`).
12. Elements match the FIXED parameters of their type, including thickness = assembly total (`TYPE_PARAM_MISMATCH`, listing every difference).
13. A room's `ceiling_assembly_ref` names a carried ceiling assembly (`CEILING_ASSEMBLY_UNKNOWN`).

Warnings (reported, model accepted): a type or assembly snapshot nothing uses (`SNAPSHOT_UNUSED`); room not fully supported by a slab; habitable room (living, dining, kitchen, bedroom, study) without a window or glazed door on its own boundary; furniture outside every room; **room not reachable from the entrance** (`ROOM_UNREACHABLE`: graph over doors — `connects` computed geometrically —, open boundaries where no wall axis runs along a shared room edge for ≥ 0.6 m, and stairs linking the room at the bottom to the room at the top landing; start = rooms with an `entrance` door, else any exterior door); no exterior door at all (`NO_ENTRANCE`).

The layout engine rejects its own candidates on any error **or** `ROOM_UNREACHABLE`, so generated models always satisfy them; Hypothesis properties over random specs check this (`tests/layout/test_invariants.py`). Not yet checked: stair headroom (a rules-profile value, `stairs.min_headroom_m`, not evaluated yet), wet-room fixture placement.

Rules findings (conceptual, per rules profile) are a separate evaluator, `rules/model_checks.py` (§10); they are warnings with a `rule_ref` and never invalidate a model.

### 4.1 Geometric invariants (Phase 3.5 K2.5)

Code: `building/geometry_checks.py` (checker), `building/constraints.py` (catalog), `building/geometry.py` (plan primitives and tolerances), `building/hosting.py` (host-relative opening arithmetic, shared with the layout engine), `building/axes.py` (derived coordination axes). `validate_model` runs the checker, so its findings reach the layout engine (candidate rejection), the generation pipeline (last line of defence) and every stored version's report (computed on read — no database change).

Four things stay separate:

| | What | Where | Effect |
|---|---|---|---|
| A. Geometric invariants | mathematical/structural consistency of the model itself | `building/constraints.py`, this section | errors reject a model/candidate |
| B. Architectural knowledge | descriptive, source-attributed | `catalog/`, `data/knowledge` ([knowledge.md](knowledge.md)) | none at runtime unless **approved** — nothing is approved, so K2.5 consumes none |
| C. Project/regional rules | enforceable minimums/maximums | rules profiles (§10) | warnings with a `rule_ref` |
| D. Design intent | what the user asked for | `BuildingSpecification` (§2) | deviations reported by the engine |

A geometric constraint never contains a dimensional requirement (no minimum pier width, headroom or clearance — those belong in a rules profile); it only states what must hold for the geometry to be coherent.

**Finding shape.** Every geometric finding is an `Issue` (the shared shape) with `code`, `severity`, a JSON-pointer `path`, `element_id` (where), `message` (English fallback) and three additive fields: `constraint` (which constraint was violated — a catalog id), `related_ids` (the other elements involved: host wall, the other opening, supporting wall, slab …) and `measure` (why, in numbers: `{quantity, actual, limit, unit}`), so a UI or report can explain a finding without parsing the message. Findings never modify the model.

**Tolerances** (`building/geometry.py`): stored coordinates are rounded to 1 mm, so containment and overlap of stored values compare with `EPS` = 0.1 mm (a real violation is ≥ 1 mm); values derived from several rounded numbers (a roof underside via tan(pitch), sums of elevations) use `DERIVED_TOLERANCE` = 1.5 mm; polygon intersections below `OVERLAP_AREA_TOLERANCE` = 0.001 m² are contact; angles compare with 1e-5 rad. Two probes ask "which room is there": 0.01 m off a wall axis beside a door and 0.1 m beyond each end of a flight — sampling distances, not requirements. Touching (zero-length overlap) is always valid.

| Constraint | Code | Severity | Must hold |
|---|---|---|---|
| `host.exists` | `HOST_NOT_FOUND` | error | A door/window has a `hosted_by` relationship to an existing element |
| `host.unique` | `HOST_AMBIGUOUS` | error | … exactly one |
| `host.is_wall` | `HOST_INCOMPATIBLE` | error | … and it is a wall |
| `host.same_level` | `OPENING_LEVEL` | error | The opening is on its host's level |
| `host.local_position` | `INVALID_HOST_POSITION` | error | Host-wall coordinates: `position.y = 0`, no rotation; doors stand on the wall base (`z = 0`) |
| `opening.within_length` | `OPENING_OUTSIDE_WALL` | error | `0 ≤ offset` and `offset + width ≤ wall length` |
| `opening.above_base` | `OPENING_OUTSIDE_WALL` | error | sill ≥ 0 |
| `opening.within_height` | `OPENING_TOO_TALL` | error | `sill + height ≤ wall height` |
| `opening.clear_of_junctions` | `OPENING_IN_WALL_JUNCTION` | error | The opening does not reach into the body of a wall that joins or crosses its host (L-corner, T-junction, crossing; the zone is the other wall's thickness around the meeting point) |
| `opening.within_thickness` | `OPENING_THICKER_THAN_WALL` | error | A door leaf is not thicker than its wall |
| `opening.no_overlap` | `OPENINGS_OVERLAP` | error | Openings in one wall do not overlap along it (every pair is checked) |
| `wall.within_level_height` | `WALL_TOO_TALL` | error | Wall height ≤ floor-to-floor height |
| `wall.orientation` | `INVALID_WALL_GEOMETRY` | error | Untilted and axis-aligned (v1 is rectilinear) |
| `wall.no_overlap` | `WALLS_OVERLAP` | error | Walls on one level and coordination axis do not overlap |
| `wall.connected` | `WALL_UNCONNECTED` | error | Both ends of an exterior wall meet another wall's body (closed envelope) |
| `wall.on_slab` | `WALL_NOT_ON_SLAB` | error | A wall's footprint lies on its level's slabs (not over an opening) |
| `room.enclosed` | `INVALID_ROOM_BOUNDARY` | error | Each edge of an indoor room runs along a wall body, another room (open plan) or a slab opening (stair arrival) |
| `room.not_crossed` | `ROOM_CROSSED_BY_WALL` | error | No wall axis runs through a room's interior |
| `room.attached` | `ROOM_DETACHED` | warning | An outdoor room touches a wall or an indoor room |
| `door.opens_to_rooms` | `DOOR_TO_NOWHERE` | error | A door has a room on at least one side; in an interior wall on both sides |
| `relationship.kinds` | `RELATIONSHIP_INVALID` | error | A relationship joins the element types its kind allows (§3.4; MEP kinds are reserved) |
| `relationship.geometry` | `RELATIONSHIP_INCONSISTENT` | error | `bounds`, `adjacent_to`, `connects`, `located_in` are true of the geometry (same level; the wall runs along the room, the rooms share an edge, the door opens into the room, the element is in the room) |
| `level.stacking` | `LEVEL_ELEVATION_MISMATCH` | error | Level 0 at 0; each level starts where the one below ends |
| `stair.orientation` | `STAIR_GEOMETRY_INVALID` | error | A flight is untilted and axis-aligned |
| `stair.in_rooms` | `STAIR_OUTSIDE_ROOMS` | error | The flight lies within the rooms of its starting level |
| `stair.clear_of_walls` | `STAIR_INTERSECTS_WALL` | error | The flight does not intersect a wall of its starting level |
| `stair.access` | `STAIR_ACCESS_INVALID` | error | It starts from a room and arrives in a room of the arrival level |
| `stair.slab_opening` | `STAIR_SLAB_CONFLICT` | error | Where treads rise above the arrival slab's underside, they pass through a slab opening |
| `slab.no_overlap` | `SLABS_OVERLAP` | error | Slabs of one level do not overlap (canopies hang above and are exempt) |
| `slab.canopy` | `CANOPY_PLACEMENT_INVALID` | error | An entrance canopy (1.3.0) hangs from the outer face of an exterior wall of its level over an entrance door: outside the walls, spanning the door, underside above the door head, top below the next level |
| `support.slab` | `SLAB_RELATIONSHIP_INVALID` | error | A wall that `supports` a slab lies under it and its top meets the slab's underside |
| `roof.shape` | `ROOF_GEOMETRY_INVALID` | error | Flat: no pitch; pitched: a pitch and no parapet; untilted |
| `roof.covers_supports` | `ROOF_FOOTPRINT_INVALID` | error | The outline covers the walls that support the roof |
| `roof.overhang` | `ROOF_OVERHANG_MISMATCH` | error | The outline extends exactly `overhang` beyond the supporting walls, on every side |
| `support.roof` | `ROOF_SUPPORT_INVALID` | error | The underside meets the supporting walls' tops (no floating) and never cuts into them |
| `roof.supported` | `ROOF_UNSUPPORTED` | warning | Some wall supports each roof |
| `type.fits_host` | `TYPE_GEOMETRY_MISMATCH` | error | The FIXED dimensions of an opening's type (door height, thickness) fit its host wall |
| `type.fits_storey` | `TYPE_GEOMETRY_MISMATCH` | error | Before generation: the fixed door sizes the building needs (from its types, or the engine defaults the generic types mirror) fit the storey's walls — else `LAYOUT_INFEASIBLE` with path `/targets/floor_to_floor_height_m` and a suggestion |

Compatibility: existing codes keep their names (`OPENING_OUTSIDE_WALL`, `OPENING_TOO_TALL`, `OPENINGS_OVERLAP`, `OPENING_LEVEL`, `WALL_TOO_TALL`, and the §4 codes `ROOMS_OVERLAP`, `ROOM_UNREACHABLE`, `STAIR_LEVELS`, …). The catch-all `OPENING_HOST` is replaced by `HOST_NOT_FOUND` / `HOST_AMBIGUOUS` / `HOST_INCOMPATIBLE`. Findings are computed on read, so no stored data changes; 1.0.0 fixtures and the demo house have no findings. "A valid type is not enough": `type.fits_host` and the placement checks apply to the element as placed — a 2.4 m window type must also find 2.4 m of free wall between junctions and other openings.

**Host-relative representation.** Doors and windows already are host-relative (§3.3): `hosted_by` = host id, `position.x` = offset along the host axis, `width`, `position.z` = sill, `height`. K2.5 keeps this representation (no schema change, no migration): it is exactly `(host_id, offset_along_host, width, sill, height)`, moving a wall moves its openings, and `building/hosting.py` works on it directly. `host.local_position` rejects anything that would make it ambiguous.

**Coordination axes.** Derived, not stored (`building/axes.py`): v1 walls are axis-aligned, so the model's axes are the distinct lines `x = c` / `y = c` of wall axes, building-wide, each with its walls ordered by level. Axes cannot drift from the walls; the checks use them to find collinear overlaps. Persistent grid elements, labelling (the K1 `spds` pack's axis conventions are unreviewed and not consumed) and dimension chains are deferred to drawing output.

---

## 5. Operations (the only way to change a model)

```jsonc
// discriminated union on "op"
{ "op": "move_wall",       "wall_id": "uuid", "offset_m": 0.4 }          // implemented (Phase 3.6 D2.1; exterior walls: the facade, D2.5)
{ "op": "set_wall_thickness", "wall_id": "uuid", "thickness_m": 0.4 }    // implemented (D2.5): interior, or the whole facade
{ "op": "set_wall_finish", "wall_id": "uuid", "face": "right", "material_id": "brick" }  // implemented (D2.5): left | right | both
{ "op": "set_wall_height", "wall_id": "uuid", "height_m": 2.4 }        // implemented (D2.5): non-structural walls only
{ "op": "add_element",     "element": Element }
{ "op": "remove_element",  "element_id": "uuid" }                    // implemented (D2.3) for doors and windows only
{ "op": "remove_wall",     "wall_id": "uuid", "merge_rooms": false }   // implemented (D2.4): interior walls; merge_rooms joins the two rooms
{ "op": "resize_opening",  "opening_id": "uuid", "width_m": 1.8, "height_m": 1.4, "sill_m": 0.9, "offset_m": 0.8 }  // implemented (D2.4): sill/offset optional
{ "op": "rename_room",     "room_id": "uuid", "name": "Guest bedroom" }   // implemented (D2.4)
{ "op": "add_wall",        "room_id": "uuid", "direction": "north_south", "x_m": 1.0, "y_m": 1.45, "new_room_type": "storage", "door_width_m": 0.8, "door_height_m": 2.1 }  // implemented (D2.4): divides the room
{ "op": "update_element",  "id": "uuid", "set": { "material_id": "oak_parquet", "properties.finishes.floor": "oak_parquet" } }
{ "op": "move_element",    "id": "uuid", "delta": { "x": 0.5, "y": 0, "z": 0 } }
{ "op": "resize_room",     "room_id": "uuid", "edge": 2, "delta_m": 0.3 }  // implemented (D2.2): side 2 of the boundary, + = outwards
{ "op": "set_room_type",   "room_id": "uuid", "room_type": "study" }   // implemented (D2.4)
{ "op": "add_opening",     "host_wall_id": "uuid", "kind": "window", "offset_m": 1.2, "width_m": 2.4, "height_m": 2.2, "sill_m": 0.3 }  // implemented (D2.3)
{ "op": "move_opening",    "opening_id": "uuid", "offset_m": 2.0, "host_wall_id": "uuid?" }  // implemented (D2.3): start edge along the wall; another wall of the same level
{ "op": "change_spec",     "patch": [JSON Patch ops] }                      // requires relayout
```

Pipeline for applying a batch:

```
validate ops (refs exist, params in range)
 → apply (pure: model, ops → model')
 → regenerate derived: rebuild room boundaries/walls where affected, rehost openings, recompute slab outlines, rerun MEP for affected levels (locked elements kept)
 → validate model' invariants
 → diff(model, model')
```

Each operation also records its **inverse** for undo within a draft. Batches that contain `change_spec` trigger a full relayout that **preserves locked elements and IDs by semantic key**; the UI warns which unlocked manual edits may be lost.


### 5.1 Implemented: `move_wall` (Phase 3.6 D2.1)

`building/operations` (pure; schemas, `walls.py`, `relationships.py`, `apply.py`). `offset_m` moves
the wall sideways, + towards its left face (the left of its start→end direction), rounded to 1 mm,
|offset| ≤ 20 m. An exterior wall moves its whole facade on every storey, with the slabs and the
roof (D2.5, §5.6); the rest of this section describes the move of one wall, which the facade move
applies per storey.

- The wall keeps its length and openings. At each end: against the side of another wall the end
  slides along it (`WALL_END_UNSUPPORTED` past its end); where the wall's line goes on (another
  wall, or a room or void boundary on the same line) a perpendicular wall running with the move
  keeps its length and a **step wall** (`<key>:jog:<start|end>`, uuid5 of the model id) closes the
  gap when none does; otherwise the walls ending there stretch or shrink (a step wall shrinking to
  zero is removed; any other wall → `WALL_WOULD_VANISH`). Walls ending on its side stretch too;
  walls crossing it → `WALL_CROSSED`.
- Every room boundary edge along the wall moves with it (partly overlapping edges step); area and
  perimeter are recomputed; a room that would close or fold → `ROOM_WOULD_COLLAPSE`.
- Openings of a wall whose start moves keep their plan position (offsets adjust). Furniture within
  10 cm of either face, along the wall, moves with it. `bounds` and `adjacent_to` are recomputed for
  the level from the geometry (the layout engine writes exactly these sets).
- The moved wall gets `origin: user`; the model `metadata.source` becomes `operations`.

**Acceptance (modules/editing/evaluate.py).** The edited model is held to the standard of a
generated one: schema, `validate_model` and `rules.model_checks`. The edit is refused
(`EDIT_INVALID`, with the blocking findings) if it introduces a model error, a rules-profile finding
(same code on the same element as in the base does not count) or a corridor/hall part narrower than
the profile's corridor minimum (`EDIT_CIRCULATION_PINCH`; the rules' clear width measures a room's
main part, which allows alcoves, so passages are checked separately). New non-rule warnings are
returned for display. Operations are replayed on the stored base version on every preview and on
save; nothing the client renders is trusted.

### 5.2 Implemented: `resize_room` (Phase 3.6 D2.2)

`building/operations/rooms.py`. `edge` is the index of a side of the room's boundary as stored
(side i runs from vertex i to i + 1; indices refer to the model the operation is applied to, so a
client must take them from the latest model); `delta_m` moves it outwards (+, the room grows) or
inwards (−), |delta| ≤ 20 m. A side is a set of walls, not geometry of its own: the operation
issues `move_wall` for every wall along the side, each by ±delta so the side moves outwards. The
neighbouring room on the other side of a shared wall, joined walls, step walls, openings, furniture
and relationships follow exactly as for a wall move (§5.1), and the same acceptance applies.
Refused, naming the room and side: `ROOM_NOT_FOUND`, `ROOM_SIDE_NOT_FOUND`, `NO_CHANGE`,
`ROOM_SIDE_OPEN` (no wall: an open-plan boundary), `ROOM_SIDE_PARTLY_OPEN` (walls cover only part
of the side), `ROOM_SIDE_FACADE` (a balcony or terrace at the facade it hangs on: move the
facade itself), `ROOM_SIDE_MIXED` (a side along several walls, one of them a facade); a side along
one exterior wall moves that facade (§5.6, D2.5); errors of the wall moves are re-raised prefixed with
"Resizing <room>:".

**Mandatory requirements (all edits, D2.2).** When the version has a spec, the edited model is
evaluated with `building.evaluation.evaluate_design`; a MUST requirement the base met and the
edit breaks blocks the edit (`EDIT_REQUIREMENT_UNMET`, "… is required: expected …, the edited plan
gives …"), a SHOULD becomes a warning (`EDIT_PREFERENCE_UNMET`). Requirements the base already
missed are not counted against an edit.

### 5.3 Implemented: doors and windows (Phase 3.6 D2.3)

`building/operations/openings.py`. Openings stay host-relative (§4.1: host wall, `position.x` =
start-edge offset, `position.z` = sill); the wall is built around its hosted openings (panel
decomposition), so placing, moving or removing an opening changes the wall in the plan and in 3D
without touching the wall element.

- `move_opening {opening_id, offset_m, host_wall_id?}`: the start edge goes to `offset_m` (rounded
  to 1 mm) along its wall, or along `host_wall_id` (same level). Id, name, kind, size and sill are
  kept; `origin` becomes `user`; a door's `connects` rooms are recomputed (rooms whose boundary
  runs along the door's span; still-valid relationships keep their place). `NO_CHANGE` under 1 mm.
- `add_opening {kind: door|window, host_wall_id, offset_m, width_m, height_m, sill_m, door_kind?,
  swing?, window_kind?}`: defaults interior door / casement window; a door's sill must be 0
  (`INVALID_HOST_POSITION`). Material, frame material, door leaf thickness (never thicker than the
  wall) and window pane width follow the model's first opening of that kind (fallback ids from the
  material library). Key `<kind>:edit:<n>`, name `New <kind> <n>`, id uuid5(model id,
  `edit:<key>`), so replays are identical. It is inserted after its wall's last opening.
- `remove_element {element_id}`: doors and windows only (`ELEMENT_NOT_REMOVABLE` otherwise);
  relationships pointing at it are dropped; the wall closes over the opening.
- Refused in the operation, naming the elements: `OPENING_NOT_FOUND`, `ELEMENT_NOT_FOUND`,
  `ELEMENT_LOCKED`, `HOST_NOT_FOUND`, `HOST_INCOMPATIBLE` (not a wall), `OPENING_LEVEL` (another
  floor), `OPENING_WALL_INCOMPATIBLE` (windows and entrance / sliding / garage doors need an
  exterior wall; interior doors may go in any wall), `OPENING_OUTSIDE_WALL`, `OPENING_TOO_TALL`,
  `OPENINGS_OVERLAP`, `OPENING_IN_WALL_JUNCTION` (the same interval arithmetic as the validator,
  `hosting.py`).

**Acceptance additions (modules/editing/evaluate.py, all edits).** Besides §5.1/§5.2: an opening
the edit placed (moved or new) keeps the rules profile's `openings.min_clearance_m` of solid wall
to a joining wall, to its wall's ends and to the other openings of the wall
(`EDIT_OPENING_CLEARANCE`, with the measure); an edit may not introduce `ROOM_UNREACHABLE`,
`NO_ENTRANCE` or `HABITABLE_ROOM_WITHOUT_WINDOW` (`EDIT_BLOCKING_WARNINGS`: tolerated in stored
designs, never created by an edit) and may not remove the last entrance door
(`EDIT_ENTRANCE_REMOVED`). Rules minimums (door/window sizes, glazing ratio) apply as for every
edit. The clearance is not applied to openings an edit did not place, so wall moves (D2.1/D2.2)
behave as before.

### 5.4 Implemented: opening sizes, wall removal, room names and types (Phase 3.6 D2.4)

- `resize_opening {opening_id, width_m, height_m, sill_m?, offset_m?}` (`openings.py`): new width
  and height (rounded to 1 mm), a window's sill (`sill_m` omitted keeps it; a door's must stay 0,
  `INVALID_HOST_POSITION`). `offset_m` places the start edge; omitted, the opening keeps its centre,
  shifted only as far as needed to stay inside its wall. Id, name, host, kind, materials and a
  door's leaf thickness are kept; `origin` becomes `user`; a door's `connects` are recomputed; a
  window's mullions are recounted so the panes keep about their width; a `type_ref` whose fixed
  parameters (a door type's height) the new size contradicts is dropped (the opening becomes a
  custom one). The same fit checks as D2.3 refuse it (`OPENING_OUTSIDE_WALL`, `OPENING_TOO_TALL` —
  the wall height is the maximum, `OPENINGS_OVERLAP`, `OPENING_IN_WALL_JUNCTION`); `NO_CHANGE` when
  nothing changes. The editing check treats a resized opening as placed (the profile's
  `openings.min_clearance_m` applies) and applies the profile's minimum sizes, window guard and
  sill heights and glazing ratio like for every edit.
- `remove_wall {wall_id, merge_rooms = false}` (`wall_removal.py`): interior walls only
  (`EXTERIOR_WALL_FIXED`: the footprint, slabs and roof rest on exterior walls). The wall's doors
  are removed with it and every relationship pointing at a removed element is dropped (no orphaned
  openings). Without `merge_rooms` the rooms on both sides keep their outlines and open into each
  other along the former wall (an open boundary; validation links such rooms for reachability).
  With `merge_rooms` the wall must border exactly two rooms (`ROOM_MERGE_UNSUPPORTED`); they become
  one room with the union outline (rectilinear, counter-clockwise, area and perimeter recomputed):
  the larger room (ties: smaller semantic key) keeps its id, name, type, height and finishes, the
  other is removed and everything that pointed at it (doors' `connects`, furniture's
  `located_in`, …) points at the merged room; a merge that would leave another wall inside the
  room is refused (`ROOM_MERGE_WALL_INSIDE`, remove that wall first). Also refused:
  `WALL_HAS_JUNCTIONS` (walls end on or cross its middle and would stand free),
  `WALL_EDGES_OPEN_SPACE` (a room on one side only: the edge of a stair opening),
  `WALL_ENCLOSES_ROOM` (bathrooms, WCs, en-suites, garages and plant rooms keep their walls; two
  rooms of the same such type may be merged), `ELEMENT_LOCKED`, `WALL_NOT_AXIS_ALIGNED`.
  `remove_element` still refuses walls (`ELEMENT_NOT_REMOVABLE`, naming `remove_wall`).
- `rename_room {room_id, name}` (`rooms.py`): trimmed, inner whitespace collapsed, 1–120
  characters without control characters (`ROOM_NAME_INVALID`), unique among the model's rooms
  ignoring case (`ROOM_NAME_TAKEN`); id, key and geometry are kept.
- `set_room_type {room_id, room_type}` (`rooms.py`): the semantic type and its zone
  (`room_zone`: public / private / circulation / exterior / service, the same as the layout
  program for the types it plans). Staircase, garage, balcony and terrace are tied to other
  elements or the envelope: a change to or from them is refused (`ROOM_TYPE_UNSUPPORTED`). Name,
  geometry and finishes are kept (a bedroom turned into a bathroom keeps its parquet: finishes are
  not re-derived). The new type's rules apply through the editing check (minimum area and width,
  a window for habitable rooms, door widths of wet rooms, glazing).

**Acceptance additions (all edits, D2.4).** The design evaluation finds the spec's rooms by
semantic key, so it would still credit a bedroom turned into a study. `program_changes` therefore
compares the base and edited room of every spec room instance: a type change or a merge of a room
the spec asked for is a warning (`EDIT_PROGRAM_CHANGED`), and blocks the edit
(`EDIT_REQUIREMENT_UNMET`) when that spec room carries a MUST requirement.

### 5.5 Implemented: `add_wall` — divide a room (Phase 3.6 D2.4)

`building/operations/wall_addition.py`. `{room_id, direction: east_west | north_south, x_m, y_m,
new_room_type?, door_width_m?, door_height_m?}` (door width and height together or not at all).
The new interior wall runs `direction` through the point (rounded to 1 mm, strictly inside the
room) across the room from boundary to boundary — in an L-shaped room across the arm that holds
the point. Both ends must lie on an existing wall's axis (`WALL_END_OPEN` on an open boundary) and
not on a door or window of that wall, widened by half the new wall's thickness
(`WALL_END_ON_OPENING`).

- The room is split along the axis: the larger part keeps the room (id, name, type, key, height,
  finishes); the smaller part is a new room `room:edit:<n>` (uuid5 of the model id, name
  `New room <m>` unique among rooms) of `new_room_type` (default the room's type; zone from
  `room_zone`). Areas and perimeters are recomputed; outlines are counter-clockwise and simplified.
- The wall copies the build-up of an interior wall bounding the room (else of the level, else of
  the model; `WALL_TEMPLATE_MISSING` if none): thickness, height, finishes, type. Key
  `wall:edit:<n>`, name `New wall <n>`, `origin: user`, inserted after the level's last wall.
- Furniture and stairs `located_in` the room move to the part that holds their centre; doors
  opening into the room are reconnected (`connects` recomputed from geometry). Furniture whose
  footprint the wall body would cut is refused (`FURNITURE_IN_THE_WAY`, naming it).
- With a door size, `add_opening` places an interior door in the middle of the new wall (its
  refusals are re-raised as "The door of the new wall: …"). Without one, the editing check refuses
  a part that can no longer be reached (`ROOM_UNREACHABLE`).
- Also refused: `ROOM_NOT_FOUND`, `ELEMENT_LOCKED`, `POINT_OUTSIDE_ROOM`, `ROOM_TYPE_UNSUPPORTED`
  (staircase, garage, balcony, terrace can neither be divided nor created), `ADD_WALL_INVALID`.
  Minimum area and width of both parts, windows of habitable rooms and the spec's MUST
  requirements are judged by the editing check. `remove_wall {merge_rooms: true}` on the new wall
  gives the room back.

### 5.6 Implemented: envelope editing — facades, wall thickness, finish and height (Phase 3.6 D2.5)

`building/operations/envelope.py` (facades), `wall_properties.py` (thickness, finish, height). Pure
like every operation; `building` does not import `layout`, and the same model with the same
operations gives the same result (test).

**The facade of an exterior wall** is the set of exterior walls on the same line, one per storey,
with the same extent and thickness (`facade_of`). It is edited as one, or refused:

| Code | When |
|---|---|
| `FACADE_CONTINUES` | another exterior wall of the same storey overlaps it or continues it in line (e.g. a garage front flush with the house front) |
| `FACADE_STOREYS_DIFFER` | the walls on that line differ between storeys (extent or thickness) |
| `VOLUME_ATTACHED` | a wall end does not meet a perpendicular exterior wall at a corner, or another volume's exterior wall (garage, wing) joins the facade — L and T wings where a facade meets the other wing are refused, their free ends move |

**`move_wall` on an exterior wall** (`move_facade`): every stacked wall moves with `shift_wall` (the
§5.1 move: corner walls stretch or shrink, rooms along it change area, openings stay host-relative,
furniture against it follows). Then:

- what hangs outside the facade is translated unchanged: balcony and terrace rooms and slabs,
  their railings and furniture, the entrance canopy (`slab_kind: canopy`);
- floor slabs: outline edges on the facade's outer face line move with it; roofs it supports: the
  edge on the outer face line + overhang moves (eaves, verge, parapet line); outlines are
  simplified, areas recomputed; `bounds`/`adjacent_to` are recomputed per level;
- refused: `FACADE_CUTS_STAIR` (the wall body would run through a stair, or a slab's stair opening
  would leave the slab), `ROOF_CANNOT_FORM` (a supported roof has no edge on the facade line, or a
  pitched roof would not stay an axis-aligned rectangle), `ENVELOPE_INVALID` (an outline would
  fold), and every §5.1 refusal.

`resize_room` on a side along one exterior wall issues this facade move.

**`set_wall_thickness {wall_id, thickness_m}`** (0 < t ≤ 1.5 m by schema): an interior wall changes
alone (axis kept); an exterior wall changes on the whole facade with its axis kept, so the outer
face moves by Δt/2: slab and roof edges on the outer face move with it and the canopy follows.
Refused: `NO_CHANGE`, the facade codes above, `BALCONY_ATTACHED` (a balcony or terrace hangs on the
facade: its slab and railings start at the outer face). The limits are the active profile's
`walls.exterior_thickness_m` / `walls.interior_thickness_m` (generic-residential: 0.20–0.60 m and
0.08–0.30 m), enforced by `rules.model_checks` as `RULE_WALL_THICKNESS`, so the editing check
refuses an edit outside them (`EDIT_INVALID`). No thickness is hard-coded in operations.

**`set_wall_finish {wall_id, face: left|right|both, material_id}`**: sets `finish_left_id` /
`finish_right_id` (the right face of an exterior wall is the facade) and clears that face's display
colour; the material must be in the library (validated with the model). `NO_CHANGE` when nothing
changes. The wall core (`material_id`) is not changed.

**`set_wall_height {wall_id, height_m}`**: only where it stays consistent — `WALL_HEIGHT_FIXED` for a
wall that supports a slab or roof (its height is the storey's), `WALL_HEIGHT_EXCEEDS_STOREY` above
the storey's structural walls, `OPENING_ABOVE_WALL_TOP` when a door or window head would stand above
it; the profile's `walls.min_height_m` (`RULE_WALL_HEIGHT`) applies through the editing check.

All four join the `Operation` union, keep `origin: user` on what they change, and pass through the
same acceptance (§5.1: no new model error, rules finding or circulation pinch; MUST requirements the
base meets stay met). Tests: `tests/building/test_envelope_editing.py` (each operation, refusals,
determinism, a Hypothesis property: every facade move and thickness change on the demo,
generated rectangular, L and T houses is refused or consistent — no new model error or rules
finding, the facade's storeys on one axis with one thickness, pitched roofs still rectangles,
canopies valid) and `tests/test_editing_api.py` (save and reload).

---

## 6. Discipline layers & materials

- Layers: `architecture, structure, furniture, plumbing, electrical, hvac, fire_safety, landscaping`. Exactly one per element. Phase 1 populates the first three; the viewer's layer manager lists the rest as planned.
- Materials are referenced by id into the shared **material library** `data/materials/library.json` (JSON so both Python and TypeScript read it without extra dependencies). The API validates ids against it; the web renderer builds one shared THREE material per id from it.

```json
{ "id": "brick", "name": "Brick", "category": "masonry", "color": "#9a5038", "roughness": 0.88, "metalness": 0 }
```

Required presets: concrete, brick, glass, wood, roof, floor, interior_wall, exterior_wall (plus tile, parquet, decking, window_frame, wood_dark, metal, fabric, fabric_light, ceramic, countertop, cabinet, screen; K3 design systems add the render presets window_frame_white, oak_light, stone_tile, wall_warm, fabric_warm — colors and roughness only, like every entry). A display color (`finish_*_color`) is drawn over a preset by the renderer (`id@#rrggbb` material key); it is not a material. Costing fields (`item_code`, `unit`, `waste_factor`) are added in Phase 4; prices never live here (they live in cost catalogs).

---

## 7. ID stability across regeneration

Each generated element gets a `semantic_key` derived from what it *is*, not where it is: `level:L1`, `room:master_bedroom`, `room:bedroom_2`, `room:corridor_1`, `room:hall_0`, `wall:ext:L1:N`, `wall:garage:S`, `wall:L1:bedroom_2|corridor_1` (interior walls: the two regions of their longest stretch), `door:front`, `door:bedroom_2`, `window:bedroom_2:S:0`, `slab:L1`, `stair:flight_0`, `roof:main`, `furniture:bedroom_2:bed:1`.

Element ids are `uuid5(id_namespace, semantic_key)`. The generation service uses the **project id** as the namespace, so regenerating the same kind of element in a project yields the same id, while two projects never share ids. `generate_layout(..., previous_ids={semantic_key: id})` additionally reuses the ids of an existing model (e.g. a hand-authored fixture) for matching keys — the hook Phase 5 regeneration with locks will build on.

---

## 8. Schema evolution

- `schema_version` follows semver. Additive optional fields → minor. Anything else → major with a migration function in `building/migrations/` (`v1_to_v2(doc: dict) -> dict`).
- Stored documents are upgraded on read; tests keep one fixture per historical version (`data/fixtures/historical/*.v1.0.0.model.json`, `generated-house.v1.1.0.model.json` = main before K3, `*.v1.2.0.model.json` = main before V3).
- **Every read of a stored or file-based model goes through `building.migrations.load_model`** (version rows, AI tools, demo fixture): it applies the pure, idempotent upgrade steps (`v1_0_0_to_v1_1_0.upgrade`: explicit empty `types`/`assemblies`, `type_ref: null`, `ceiling_assembly_ref: null`; `v1_1_0_to_v1_2_0.upgrade`: `design: null`, wall `finish_*_color: null`, window `size_class: null`; `v1_2_0_to_v1_3_0.upgrade`: the version only — 1.3.0 adds `slab_kind: canopy` — nothing is inferred) and validates. Stored rows are never rewritten: their JSON, `schema_version` column and `model_hash` stay as written (versions are immutable); the API serves the current schema. The web therefore only ever sees 1.3.0 (its validator uses the serialization schema, where defaulted fields are required).
- Specifications: 1.1.0 (K3) is additive; `schema_version` accepts "1.0.0" and "1.1.0" and a 1.0.0 document keeps its meaning (every new field is optional and null).

### 8.1 Geometry fingerprint

`building.fingerprint.geometry_sha256(model)` hashes levels and elements without type metadata (`type_ref`, `ceiling_assembly_ref`, `types`, `assemblies`) and without document fields (id, versions, metadata). Golden files record it next to the full-model hash: schema upgrades and type assignment must leave it unchanged (K2 verified it for all reference specs, typed and untyped, and for the upgraded 1.0.0 fixtures). K3 (1.2.0) also strips window `size_class` (classification metadata) and the `finish_*_color` keys **when null**: all ten reference specs (no design intent) and the upgraded 1.0.0/1.1.0 fixtures keep their exact pre-K3 fingerprints, while a colored model fingerprints differently (it renders differently).
- After changing Pydantic models: `pnpm schema` regenerates `packages/schema` (JSON Schema → TS types via json-schema-to-typescript; the Zod validator is built at runtime from the same JSON Schema with `z.fromJSONSchema`). After changing the demo fixture script: `pnpm fixtures`. Pytest fails if the committed JSON Schema or fixture is stale; CI fails if the generated TS is stale.

## 9. IFC alignment (future)

Types map cleanly to IFC: wall→IfcWall, room→IfcSpace, door→IfcDoor, window→IfcWindow, slab→IfcSlab, pipe_segment→IfcPipeSegment, duct_segment→IfcDuctSegment, system→IfcDistributionSystem, level→IfcBuildingStorey. We don't implement export now, but we avoid modeling choices that would prevent it.

---

## 9.1 Knowledge ontology (Phase 3.5)

The `core@1` knowledge pack (`data/knowledge/packs/core.v1/ontology.yaml`, [knowledge.md](knowledge.md) §3.2) binds every element type, room type, building type, the level and every relationship kind of this schema to an ontology class with an (editorial) IFC mapping, and adds vocabulary-only classes the model does not represent (foundation, lintel, column, pipeline, …). The Pydantic schema stays canonical: adding an element type, room type or relationship kind requires the matching ontology entry (integrity check `ONTOLOGY_COVERAGE`) and `pnpm knowledge:lock`.

## 10. BuildingRulesProfile (configurable conceptual rules)

Dimensional rules are **data, not code**. The layout engine and validators read every minimum/maximum from the active `BuildingRulesProfile`; no dimensional constant is hard-coded in business logic.

> Rules profiles support **conceptual validation only**. They are not a statement of compliance with any building code, including Kazakhstan's (SN/SP RK). BuildAI 3D does not replace licensed architectural, structural, MEP or regulatory review.

- Code: `apps/api/app/modules/rules/` (pure domain module): `profile.py` (Pydantic schema), `loader.py` (YAML files, `extends` resolved by deep merge), `spec_checks.py` (tier-2 spec validation, §2.2), `model_checks.py` (evaluation of any BuildingModel).
- Data: `data/rules-profiles/<id>.v<version>.yaml` (YAML: human-edited, commented data; PyYAML). Profiles are read from files and cached per process; the `rules_profiles` DB table is deferred until profiles become user-editable. A file is **immutable once used** — changes go into a new version file.
- Each project has a `rules_profile_id` (default `generic-residential@1`). Each version records the profile (`project_versions.rules_profile`) that validated it; rules findings are re-evaluated on read against that exact profile.
- Regional profiles (e.g. `kz-residential`) are added later as new YAML files that `extends` the generic profile and override values.

`model_checks` evaluates: room area and clear width per room type (clear width = the largest short side of an axis-aligned rectangle inside the room, i.e. the main part of an L-shaped room), corridor width, clear ceiling height (habitable vs service), glazing-to-floor ratio of rooms with `requires_window` (windows + glazed sliding doors on the room's boundary), door width/height by kind (entrance, interior, wet room, garage per car), window size, upper-floor sills below the guard height, stair riser/tread/2R+T/risers per flight/width, railing heights (balcony vs other). Not evaluated yet: headroom, accessibility (profile data present, `enabled: false`).

```yaml
id: generic-residential
version: 1
name: Generic residential (conceptual)
extends: null
disclaimer: Conceptual rules only. Not a building-code compliance check.
units: m
rooms:                      # per room type; unspecified types fall back to "default"
  default:             { min_area_m2: 4.0,  min_width_m: 1.5 }
  bedroom:             { min_area_m2: 9.0,  min_width_m: 2.7, requires_window: true }
  living:              { min_area_m2: 16.0, min_width_m: 3.6, requires_window: true }
  dining:              { min_area_m2: 8.0,  min_width_m: 2.7, requires_window: true }
  kitchen:             { min_area_m2: 6.0,  min_width_m: 2.2, requires_window: true }
  open_kitchen_living: { min_area_m2: 25.0, min_width_m: 4.0, requires_window: true }
  study:               { min_area_m2: 6.0,  min_width_m: 2.2, requires_window: true }
  bathroom:            { min_area_m2: 3.5,  min_width_m: 1.6 }
  en_suite:            { min_area_m2: 3.0,  min_width_m: 1.5 }
  wc:                  { min_area_m2: 1.2,  min_width_m: 0.9 }
  # … laundry, utility, storage, walk_in_closet, plant_room, entrance, hall, staircase
  corridor:            { min_area_m2: 0.0,  min_width_m: 1.0 }
  garage:              { min_area_m2: 18.0, min_width_m: 3.0, per_car_area_m2: 18.0 }
  balcony:             { min_area_m2: 1.5,  min_width_m: 0.9 }
  terrace:             { min_area_m2: 3.0,  min_width_m: 1.5 }
ceiling:
  min_clear_height_m: 2.5           # habitable rooms
  min_clear_height_service_m: 2.2   # storage, garage, wc, corridor
corridors:
  min_width_m: 1.0
  min_width_accessible_m: 1.2
doors:
  entrance:  { min_width_m: 0.9,  min_height_m: 2.1 }
  interior:  { min_width_m: 0.8,  min_height_m: 2.0 }
  bathroom:  { min_width_m: 0.7,  min_height_m: 2.0 }
  garage:    { min_width_per_car_m: 2.5, min_height_m: 2.1 }
windows:
  min_glazing_to_floor_ratio: 0.125  # habitable rooms (1:8)
  min_sill_height_m: 0.0             # panoramic allowed
  guard_required_below_sill_m: 0.9   # upper floors: sills lower than this need a guard/railing
  min_width_m: 0.6
  min_height_m: 0.6
openings:                            # plan editing (D2.3), optional: absent = no clearance rule
  min_clearance_m: 0.1               # solid wall from a moved/added opening to a corner/joining wall, wall end or next opening
walls:                               # envelope editing (D2.5), optional: absent = no wall rules
  exterior_thickness_m: { min: 0.2,  max: 0.6 }   # RULE_WALL_THICKNESS
  interior_thickness_m: { min: 0.08, max: 0.3 }
  min_height_m: 0.9                  # RULE_WALL_HEIGHT (lowest wall of any kind)
stairs:
  min_width_m: 0.9
  riser_m: { min: 0.15, max: 0.19 }
  tread_m: { min: 0.25, max: 0.32 }
  comfort_rule: { formula: "2R+T", min: 0.60, max: 0.65 }
  min_headroom_m: 2.0
  max_risers_per_flight: 16
  landing_min_depth_m: 0.9
railings:
  min_height_m: 0.9
  balcony_min_height_m: 1.0
accessibility:                       # basic geometry checks, reported as warnings
  step_free_entrance: warning
  turning_circle_diameter_m: 1.5     # checked in one ground-floor bathroom when enabled
  accessible_door_clear_width_m: 0.85
  enabled: false
```

Rule evaluation output uses the standard issue shape `{ severity, code, path, message, rule_ref, element_id }` where `rule_ref` = `generic-residential@1:stairs.riser_m` so every warning is traceable to the exact rule. (The originally sketched `bedroom_master` entry was dropped: the model has no "master" room type, so it could not be applied reliably.)
