# Architectural Knowledge (Phase 3.5)

Status: **K1, K2, K2.5 on main; K3 implemented (branch, awaiting review)** · Code: `apps/api/app/modules/catalog/` · Data: `data/knowledge/`

Phase 3.5 grounds BuildAI in structured, source-attributed architectural knowledge. K1 is the
foundation: schemas, provenance, the first packs, loading, integrity and hash locking. K2 adds
component records (families, types, assemblies, role mappings) and the gated resolver. K3 adds
design systems (§3.5). **Only the generation pipeline consumes the catalog** (import-linter
contract), and only APPROVED records; engines receive plain `building.types` /
`building.design` data. Nothing is approved yet, so generation is still untyped and no design
system is usable (explicit colors, window placement and room orientation work without one).

| Step | Scope | Status |
|---|---|---|
| **K1** Knowledge Foundation | catalog module, provenance, ontology, glossary, drawing profile, region-profile foundation, loader, registry, integrity, lock, first packs | ☑ |
| K2 Families, Types, Assemblies | family/type/assembly/role-mapping records, generic type pack (draft), resolver, BuildingModel 1.1.0 type snapshots, layout integration | ☑ (pack awaiting review) |
| K2.5 Architectural Geometry & Placement | geometric invariants and constraint-aware layout (§8.1); consumes no knowledge | ☑ |
| K3 Design Systems + expressive design intent | design-system records (4 editorial drafts), gated resolution, BuildingModel 1.2.0 design record, spec 1.1.0 design intent (facade color, facade-specific windows, room orientation), layout/renderer/AI integration | ◐ (branch, awaiting review) |
| K4 Templates | real building configurations (programme, relationships, circulation, constraints) | ☐ |
| K5 Knowledge API and Units | read-only catalog API; imperial display/input conversion | ☐ |
| K6 Optional Structural Elements | structural element types in the model | ☐ |

## 1. Principles

1. **Knowledge is not rules.** Knowledge describes; rules constrain. Enforceable minimums and
   maximums live only in `BuildingRulesProfile`s (`data/rules-profiles/`, CLAUDE.md rule 16).
   If knowledge should ever constrain a design, a rules-profile entry is created for it.
2. **Every object is attributed.** At least one citation to a source record, with printed page
   numbers for paginated sources.
3. **Only `approved` knowledge may be consumed** by engines or AI (`registry.approved_items()`),
   and approval requires a human review record. In K1 nothing is approved.
4. **Paraphrase only.** No quotations, reproduced figures, symbols or tables beyond parameters.
   Source documents are never committed; source records keep a SHA-256 fingerprint.
5. **Global vs scoped.** The `core` pack is region- and practice-independent. It may cite a
   published source only for the *existence* of a concept. Source-specific statements live in
   scoped packs (a drawing-convention profile or a region).
6. **The building model stays canonical.** The ontology *binds to* the Pydantic vocabulary and
   never replaces it (CLAUDE.md rule 7).
7. **Versioned and locked.** Packs are immutable once used (new `.v<n>` directory for changes);
   every data change needs `pnpm knowledge:lock`.

## 2. Sources

`data/knowledge/sources/<id>.yaml` holds one `Source` per document:

| Field | Meaning |
|---|---|
| `kind` | `reference_handbook`, `standard` or `editorial` (BuildAI-authored content) |
| `title`, `authors`, `publisher`, `publication_year`, `isbn`, `language` | bibliography |
| `page_count` | printed pages; citations must fall inside it (`null` = not paginated) |
| `basis`, `jurisdiction_context`, `temporal_note`, `scope_note` | what the source is and is not |
| `artifact` | format, `sha256`, artifact page count, page map; `stored_in_repo` is always false |
| `usage_policy` | `paraphrase_only: true`, `reproduce_figures: false` for published sources |

Current sources:

- **`georgievsky-2004`**: Георгиевский О.В., *Единые требования по выполнению строительных
  чертежей* (Архитектура-С, 2004, 144 pp.). A student reference handbook that, by its preface,
  follows ESKD/SPDS as of 2004. It is **one** source, scoped as the `spds` drawing-convention
  profile, **not** a global architectural standard and not a construction-code engine. It is
  mostly drafting conventions; it contains almost no room-programme or layout guidance.
- **`buildai-editorial`**: our own ontology structure, IFC mappings, English terms and
  definitions, and model bindings.

## 3. Packs

```
data/knowledge/
├── knowledge.lock.json
├── sources/{georgievsky-2004,buildai-editorial}.yaml
├── packs/
│   ├── core.v1/                      scope: global
│   │   ├── pack.yaml
│   │   ├── ontology.yaml             79 classes, 9 relationship definitions
│   │   └── glossary.en.yaml          60 canonical terms
│   ├── buildai-generic-types.v1/     scope: global, components (K2, draft)
│   ├── buildai-design-systems.v1/    scope: global, design systems + mappings (K3, draft)
│   └── spds-georgievsky-2004.v1/     scope: drawing_convention_profile (spds), depends on core@1
│       ├── pack.yaml
│       ├── model.yaml  layout.yaml  drawing-sheets.yaml  drawing-views.yaml
│       ├── structural.yaml  mep.yaml  reference.yaml   (89 knowledge items)
│       ├── glossary.ru.yaml          59 Russian wordings of core terms
│       └── drawing-profile.yaml      the spds@1 drawing profile
└── regions/generic.v1.yaml
```

A **pack manifest** (`pack.yaml`) declares `id`, `version`, `status`, `scope`
(`global` | `drawing_convention_profile` | `regional`, with jurisdiction and era), the `sources`
it may cite, `depends_on` (pack refs) and `contents`, which lists **every** file (unlisted or
missing files are errors).

### 3.1 Knowledge items

```yaml
- id: drawing.plan.cut_plane          # dotted, unique per pack; ref = spds-georgievsky-2004@1:drawing.plan.cut_plane
  kind: convention                    # principle|convention|definition|code_list|content_list|
                                      # dimension_table|symbol_set|example|reference
  category: drawing                   # building_model|layout|drawing|structural_drawing|mep|reference
  concept: floor plan cutting plane
  statement: >-                       # paraphrase, <= 500 characters
    A floor plan is a horizontal section at the level of the window openings or at one third ...
  params: { cut_height_of_storey_ratio: 0.333 }
  inferences: []                      # anything NOT stated by the source
  confidence: high                    # high|medium|low
  usage: runtime_candidate            # or reference_only (never consumed)
  intended_use: [documentation.plan.cut]
  related: [term.floor_plan]          # class./term. ids or items of the same pack
  provenance: [{ source: georgievsky-2004, pages: [69], section: "6.2", figures: ["Рис. 76"] }]
  status: extracted
```

**Units:** every numeric parameter carries a unit through its own or an enclosing key suffix:
`_m`, `_m2` (building space, SI), `_paper_mm` (drawing sheet), `_deg`, `_ratio`, `_s` (multiples
of the main line thickness), `_count`, `_index`. Scales are quoted ratios (`"1:100"`); an
unquoted YAML `1:10` would parse as a number. Imperial conversion is a K5 display/input layer;
internal values stay SI.

`kind: example` marks values shown in a worked example (e.g. a slope on an illustration). They
are always `reference_only` and never rules.

### 3.2 Ontology (`core`)

- `OntologyClass`: `id` (`class.*`), English `label`, `kind` (building, storey, element, space,
  grid, system), `parent` (is-a), `model_binding`, `ifc` (entity + predefined type, editorial),
  `in_scope_v1` (residential, ≤ 3 storeys).
- `model_binding` targets exactly one of `element_type`, `room_type`, `building_type` or
  `level`, optionally with a `discriminator`/`value` (e.g. `wall_kind: partition`).
- **Coverage invariant:** every element type, room type, building type, the level, and every
  `RelationshipKind` is bound by exactly one primary class or relationship definition. A model
  vocabulary change without an ontology update fails the integrity check.
- `RelationshipDefinition`: `model_binding` (a `RelationshipKind`), allowed `source_classes` /
  `target_classes` (subclasses included), `per_source` cardinality, `reserved` for Phase 6 MEP.
- Unbound classes (foundation, lintel, column, pipeline, …) are vocabulary only. K1 introduces
  no model element types.

### 3.3 Glossary

`Term` (core): canonical id `term.*`, English `preferred`, `synonyms`, editorial `definition`,
`class_ref`. `LocalizedTerm` (scoped packs): `term_id`, `locale`, `preferred`, `synonyms`,
`abbreviations`, `codes` (e.g. `spds_letter: ПР`), each cited to the page where the source
uses the term.

### 3.4 Components: families, types, assemblies (K2)

Records live in a pack's `contents.components` files (`catalog/components.py`) and follow the
same provenance, lifecycle, lock and integrity rules as knowledge items:

| Record | Fields |
|---|---|
| `FamilyRecord` | `id` (`family.*`), `name`, `element_type`, `class_ref` (ontology class) |
| `TypeRecord` | `id` (`type.*`), `family`, `name`, `params` (the model's typed `TypeParams`), `assembly`, `derived_from {knowledge: [item refs], layout_config: [field names]}`, `usage` |
| `AssemblyRecord` | `id` (`assembly.*`), `kind` (wall/floor/roof/ceiling), `name`, `layers`, `total_thickness`, `derived_from` |
| `RoleMapping` | `id` (`mapping.*`), `name`, `roles {role: type id}` covering every `TYPE_ROLES` role |

**`buildai-generic-types@1`** (global, editorial, **draft**) migrates the layout engine's
existing defaults (`LayoutConfig` + the material ids `build.py` writes) into 7 families, 20
types, 7 assemblies and `mapping.generic`. It adds no construction data: assemblies are one
structural layer of today's thickness with an **unspecified** material. A test asserts that the
generic types reproduce `LayoutConfig` exactly. It is not derived from Georgievsky 2004 and is
not approved automatically.

Integrity adds: component ids unique; family element type and ontology class exist; type params
match their family's element type; wall/slab/roof types name an assembly of the right kind (and
only they do); assembly layers add up; materials exist in the material library; mappings cover
exactly the known roles with types of the right element type; `derived_from` knowledge exists,
and an **approved record may not be derived from unapproved knowledge**
(`APPROVED_DERIVED_UNAPPROVED`).

**Resolution** (`catalog/resolver.py`, `resolve_type_set(registry, mapping_id)`): a role gets a
type only if the mapping, type, family and assembly are all approved, the type is a runtime
candidate, and all derived knowledge is approved; otherwise the role is skipped with a reason
(never substituted). No resolved role ⇒ no type set ⇒ untyped generation. Roles are visited in
sorted order, snapshots are sorted by id and carry the sha256 of their catalog record, so the
result is deterministic. The generation pipeline then checks the set against the project's rules
profile (`rules/type_checks.py`): a type below a profile minimum fails the generation with
`TYPE_RULE_VIOLATION` reasons and a `rule_ref` — it is never resized.

Book-derived types (e.g. a GOST 11214-86 window family from
`spds-georgievsky-2004@1:layout.window_sizes_gost_11214_86`) stay blocked while that item is
`needs_verification`: integrity refuses to approve such a type and the resolver skips it.

### 3.5 Design systems (K3)

A **design system** (`DesignSystemRecord`, in a pack's `contents.components` file under
`design_systems:`) is an editorial, region-neutral aesthetic grouping of compatible choices. It
is **not** a building code, an engineering rule or a claim of architectural correctness, and it
contains no construction data: types and assemblies come only through its role mapping.

| Field | Meaning |
|---|---|
| `id` | kebab-case (`modern-minimal`), what `style.design_system` names |
| `style_tags`, `interior_styles` | allow-lists of the spec's architectural / interior styles |
| `role_mapping` | a K2 role mapping (types for every `TYPE_ROLES` role: walls, slabs, roofs, doors, windows, stair, railings) |
| `roof` | allowed roof types, default, default pitch |
| `windows` | allowed window sizes (standard/large/panoramic), default |
| `facade` | allowed facade materials + default; color palette (names from `building/appearance.py`), default color, whether custom colors are allowed |
| `finishes` | dry floor, wet floor, interior wall, wet-room wall (material ids) |
| `furniture` | palette per slot (upholstery, light upholstery, wood, dark wood, cabinet, countertop) |

**`buildai-design-systems@1`** (global, editorial, **draft**; depends on `core@1` and
`buildai-generic-types@1`) holds `modern-minimal`, `contemporary-warm`, `classic-brick` and
`scandinavian-timber`, their four role mappings, and nine *visual* type variants (steel/oak
entrance doors, a glass stair railing, white- and oak-framed windows) that copy the generic
types' dimensions and differ only in frame/leaf material or railing kind. Five render presets
were added to the material library (`window_frame_white`, `oak_light`, `stone_tile`,
`wall_warm`, `fabric_warm`; color and roughness only).

**Integrity** (`component_integrity.check_design_systems`, code `DESIGN_SYSTEM_INCOMPLETE`
unless noted): no duplicate values in allow-lists; defaults inside their allow-lists (roof,
window style, facade material, color); no pitch for a flat default roof; palette names exist;
a default color needs a palette or custom colors; finish/furniture materials exist
(`UNKNOWN_MATERIAL`); the role mapping exists (its roles and types are checked as K2
mappings); an **approved** system may only depend on an approved mapping, types, families and
assemblies.

**Resolution** (`catalog/design_systems.py`): `resolve_design(registry, id)` returns a
`building.design.DesignSystemSnapshot` (sorted, with the record's sha256 and the resolved
`type_ids`) plus the type set of its mapping — only if the system is approved **and** every
role of its mapping resolves (K2 gating); otherwise the reason (never a substitute).
`design_catalog(registry)` splits all systems into usable snapshots and unavailable ones with
reasons; the generation pipeline exposes it (`available_design_systems`) to tier-2 checks
(`building.design.check_design`), the AI prompt context (only usable systems are offered) and
`GET /api/v1/design-options` (the specification form). With the repository's drafts nothing is
usable: a spec naming a draft system fails tier 2 with `DESIGN_SYSTEM_NOT_APPROVED`.

Tests approve records only in temporary copies (`tests/catalog/helpers.py
approve_design_systems`, `approved_design_registry`), as in K2.

### 3.6 Layout patterns (Design Intelligence V1)

A **layout pattern** (`PatternRecord`, `catalog/patterns_schema.py`, listed under a pack's
`contents.patterns`) is a reusable arrangement recipe for the deterministic layout engine. Each
record has: intended use (`intent`), suitable `context`, room `relationships` (adjacency graph in
words), `circulation`, `privacy`, `daylight` and `facade` implications, `tradeoffs`,
`limitations`, `statements` (each `principle` | `source_rule` | `heuristic`), `engine_support`
(`full` | `partial` | `none`), `applicability` (triggers + optional storey-area threshold,
storeys) and a `recipe` the engine reads: `band_preferences` (room types → garden/street side,
weight), `affinities` / `separations` (room-type pairs, weight), `footprint_aspect` (preferred
width/depth range).

**Statement kinds stay apart.** A `principle` is a widely taught design principle stated without
a source claim; a `source_rule` needs a cited published source and a review
(`PATTERN_RULE_UNSOURCED` otherwise); a `heuristic` is BuildAI's own rule of thumb — every recipe
must be explained by one (`PATTERN_RECIPE_UNEXPLAINED`). A pattern the engine cannot realise is
`engine_support: none`, `usage: reference_only` and has no recipe
(`PATTERN_UNSUPPORTED_RUNTIME`); partial support must list its limitations.

**Consumption policy (decided 2026-10-26, exception to "only approved knowledge is
consumed").** Layout patterns are *soft heuristics*, like the `LayoutConfig` defaults the engine
already uses. Draft patterns may steer generation, under these conditions: they only change
scored preferences (never create, relax or override a user requirement or a rules-profile
limit); every use is reported with the pattern's status ("draft · experimental") in the
generation report and engine notes; they are never presented as verified standards. Patterns are
resolved by `catalog/patterns.py pattern_library` (deprecated and reference-only records are
left out) into `building.patterns.LayoutPattern` snapshots; only the generation pipeline reads
the catalog. Applicability is decided by the engine from the spec (`layout/patterns.py`).

A recipe may also name a footprint `topology` (`l_shape`, V1.1): the engine then searches that
topology **in addition to** rectangles and lets the evaluation decide; a pattern never replaces
the rectangular option and never satisfies or overrides a user's `design.footprint_shape`
(a requirement). Topology patterns must be single-storey (`PATTERN_TOPOLOGY_STOREYS`).
`applicability.required_triggers` (all must be present) and `min_floor_area_per_storey_m2`
narrow when a pattern applies.

**`buildai-layout-patterns@1`** (global, editorial, **draft**; amended before release with the L
pattern, V1.1): `compact_family_home`, `garden_oriented_living`, `l_shaped_garden_wing`
(garden focus **and** privacy, one storey, ≥ 110 m²), `narrow_plot_linear`, `open_plan_living`,
`public_private_zoning`, and
`courtyard_house` (reference only: the double-loaded engine cannot enclose an outdoor room). No
statement is a `source_rule`; all provenance is `buildai-editorial`.

## 4. Drawing profiles

A `DrawingProfile` (`spds@1`) is a versioned grouping of a pack's drawing items by topic (sets,
sheets, scales, lines, fonts, hatching, dimensions, axes, level marks, callouts, titles, views,
symbols, site) for future documentation generation. It must live in a
`drawing_convention_profile` pack scoped to its id, every topic reference must be a drawing item
of that pack, and every drawing item must be grouped. Symbols are stored as meanings and
parameters (e.g. door kinds, sash kinds, arrow semantics), never as glyphs. Another practice
(ISO, a regional standard) is a separate profile over separate knowledge.

## 5. Region profiles

`RegionProfile` composes regional choices **by reference**: `rules_profile`
(e.g. `generic-residential@1`), optional `drawing_profile`, `knowledge_packs`, `locales`,
`measurement` (internal SI; display metric until K5), `region_codes` (ISO 3166, empty =
region-independent). It holds no rules or knowledge itself. `generic@1` is the default and
deliberately does **not** include the SPDS pack; a region opts into a drawing profile
explicitly (and must then include the pack that defines it). Nothing reads region profiles
until later steps.

## 6. Lifecycle

| Status | Meaning | Allowed |
|---|---|---|
| `draft` | team-authored, unreviewed | editorial citations only |
| `extracted` | taken from a published source, unreviewed | needs a published-source citation |
| `needs_verification` | extracted, with legibility or interpretation doubts | same |
| `reviewed` | checked against the cited pages by a person | needs `review {reviewed_by, reviewed_on}` |
| `approved` | released for runtime use | needs `review`; not with `confidence: low` |
| `deprecated` | kept for provenance | may carry `superseded_by` |

In K1 all book-derived objects are `extracted` (83 items) or `needs_verification` (6: the window,
door and fixture size tables, minimum line thickness, pipeline codes, the standards list).
Twenty items are `reference_only` (structural drawing, bibliographic, examples).

## 7. Loading, integrity and lock

`catalog.loader.read_knowledge(data_dir)` parses every document (Pydantic, `extra="forbid"`),
builds the `KnowledgeRegistry`, runs `integrity.check_registry` and verifies the lock; any error
raises `KnowledgeLoadError` with all issues in the shared `Issue` shape (JSON-pointer paths).
`load_knowledge(data_dir)` is the cached variant.

Integrity checks: pack directory naming, unlisted/missing files, unknown sources and
dependencies, dependency cycles, duplicate ids; citation sources, declared sources, page ranges;
status ↔ source kind; global-scope borrowing; unit suffixes; scale format; approved
low-confidence items; unresolved `related`/`superseded_by`; class parents and cycles; binding
targets; relationship classes; ontology coverage; glossary links; drawing-profile scope, topic
references and grouping; region references (rules profile file, drawing profile, packs).

`knowledge.lock.json` stores a SHA-256 per source file, pack directory and region file
(LF-normalised, path-sorted). A stale, missing, unlisted or orphaned entry is an error.
Workflow: edit data → run tests → `pnpm knowledge:lock` → commit data and lock together.

## 8. What K1/K2 do not do

No K4–K6 content (templates, catalog API, units, structural elements; design systems are K3, §3.5), no
retrieval layer or vector search, no costing, no prompt or specification changes. K2 changes the
model schema (1.1.0, upgrade-on-read) and lets the layout engine use an approved type set; with
the repository's draft pack, generated geometry is unchanged (geometry fingerprints equal).

### 8.1 K2.5 and knowledge

K2.5 (geometric invariants, [building-model.md](building-model.md) §4.1; constraint-aware layout, [3d-engine.md](3d-engine.md) §16.7) is geometry, not knowledge, and **consumes no knowledge item at runtime**: only approved items may be consumed and none is approved. Nothing was converted into a rule or a constraint. Where the book pack describes a related concept, the geometric layer works from the model alone, and the item stays a review candidate for later steps:

| K1 item (status) | Related K2.5 behaviour | Why not consumed |
|---|---|---|
| `spds-georgievsky-2004@1:model.axes.definition`, `model.wall_axis_binding`, `core@1` `class.coordination_axis` (extracted) | coordination axes are *derived* from wall axes (`building/axes.py`), not stored or labelled | unreviewed; axis labelling and wall-to-axis binding are SPDS drawing conventions, not global geometry |
| `model.storey_height`, `model.zero_level` (extracted) | `level.stacking` uses only the model's own `elevation`/`height` | the model already defines both |
| `model.size_kinds` (extracted) | openings are checked at their modelled size | nominal vs construction sizes need review before they may affect fits |
| `layout.window_sizes_gost_11214_86`, `layout.door_sizes_gost_24698_81` (needs_verification) | none; `type.fits_host` works on the model's type snapshots | unverified tables; types derived from them stay blocked (K2) |
| `drawing.symbols.openings`, `drawing.symbols.stairs_ramps`, `drawing.plan.*` (extracted) | none | drawing output, not validation |

K2 types are used as the model carries them: a type's FIXED dimensions are checked against the host they are placed in (`type.fits_host`) and, before generation, against the storey's walls (`type.fits_storey`); defaults (`default_*`) may differ from the element by design and are not constraints.

## 9. Known limitations

- Book items are unreviewed. Several tables were read from a low-resolution scan; the book's
  cited standards may have been superseded since 2004.
- The book offers almost no room-programme knowledge; templates (K4) need other sources.
- Generic assemblies are single-layer with unspecified materials, so Phase 4 quantities from
  them are coarse (volume by function) until real build-ups come from a reviewed source.
- K3 design systems are editorial drafts; until a person reviews them (and the generic types
  they build on) no design system is usable. Their type variants are visual only (frame/leaf
  materials, railing kind); no system-specific assemblies or construction build-ups exist.
- IFC mappings and English definitions are editorial and unreviewed (`draft`).
- `params` are typed JSON values checked for units; typed per-kind schemas arrive with K2.
