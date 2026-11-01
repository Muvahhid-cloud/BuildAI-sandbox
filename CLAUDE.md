# CLAUDE.md — BuildAI 3D

Permanent rules and decisions for every Claude Code session on this repository. Read this first. If a rule here conflicts with a request, raise the conflict instead of silently breaking the rule. Changing a rule = update this file + the relevant doc in `/docs` in the same change.

## What we are building

An AI-powered residential building design platform: natural language → validated `BuildingSpecification` → deterministic layout → `BuildingModel` (typed elements) → procedural 3D in the browser → quantities → preliminary cost → NL modifications → versions/compare → reports.

Docs (source of truth for design): `docs/architecture.md`, `docs/building-model.md`, `docs/ai-pipeline.md`, `docs/3d-engine.md`, `docs/database.md`, `docs/knowledge.md`, `docs/roadmap.md`.

Current phase: see the ☐/◐/☑ markers in `docs/roadmap.md`. Do not implement features from a later phase unless asked.

## Non-negotiable architecture rules

1. **The BuildingModel is the source of truth.** Meshes, quantities, costs, reports, AI analyses are derived. Never persist or edit derived data as if it were primary.
2. **AI produces intent, never geometry.** LLM output is a `BuildingSpecification`, a `ModificationPlan` (typed operations) or an analysis. LLMs never output coordinates, wall geometry or UUIDs. All AI output is untrusted until Pydantic + rule validation pass.
3. **Every element** has: `id` (UUID), `type`, `name`, `layer`, `level_id`, `position`, `rotation`, `dimensions`, `material_id`, `properties`, `relationships`, `origin`, `locked`, `semantic_key`, and (schema 1.1.0) an optional `type_ref` into the model's self-contained `types`. Walls are wall objects, rooms are room objects, windows are window objects, pipes are pipe objects. No "blob" geometry.
4. **Models change only through typed operations** (`building/operations`). No ad-hoc dict mutation of models in services or routes.
5. **Deterministic engines.** Layout/MEP/quantities/costing are pure functions of (input, seed, engine_version). No wall-clock, no global random, no I/O inside them.
6. **Domain purity.** `modules/{building,rules,layout,mep,quantities,costing}` must not import FastAPI, SQLAlchemy, `app.core.db`, or `modules/ai`. Enforced by import-linter.
7. **One schema source.** Pydantic models in `apps/api/app/modules/building/` are canonical. `packages/schema` is **generated** (`pnpm schema`) — never hand-edit it. Frontend uses the generated TS types and Zod validators.
8. **Units & axes.** Meters, radians, m², m³. Model is **Z-up** (plan = XY). The only Z-up→Y-up conversion is the viewer root `<group rotation-x={-Math.PI/2}>`. Geometry rounded to 1 mm; compare with `EPS = 1e-4`.
9. **Money** is `Decimal` in Python and a string on the wire (never JS float math for totals). Always carry a currency. Estimates are labelled preliminary.
10. **No CSG** for wall openings — use panel decomposition. Quantities are never measured from meshes.
11. **Versions are immutable.** Changes create new `project_versions` rows. Restores create a new version.
12. **Stable IDs.** Regeneration reuses IDs by `semantic_key`; `locked` elements are preserved.
13. **Vendor-neutral AI.** Vendor SDKs are imported only in `modules/ai/providers/<vendor>.py`. Tests always use `MockAIProvider`; never call a paid API in CI.
14. **Modular monolith.** No microservices, message buses, Kubernetes, or Redis until a documented need. New infra requires an ADR in `docs/architecture.md`.
15. **Residential, rectilinear, ≤ 3 storeys** in v1. Don't generalize beyond that without an explicit decision.
16. **No hard-coded prices or dimensional rules.** Prices come only from versioned cost catalogs; minimum/maximum dimensions come only from the active `BuildingRulesProfile` (`modules/rules`, `data/rules-profiles/`).
17. **Currency-agnostic costing.** Every amount carries an ISO-4217 currency; never add different currencies. Primary region Kazakhstan, primary currency **KZT**. Seed catalogs are demo data and must be flagged `is_demo` and labelled "Demo / estimated rates" in the UI.
18. **Disclaimer.** The platform is conceptual and not a replacement for licensed architectural, structural, MEP or regulatory review. Keep the single-source disclaimer (`app/core/disclaimer.py`, web `DISCLAIMER` constant) visible in the footer, cost views, rules panels and reports.
19. **Phase order is intentional:** 0 foundations → 1 hand-authored model → procedural 3D → 2 spec → layout engine → 3 NL → AI. The 3D pipeline must work without AI before AI is connected. No AI features before Phase 1 exits.
20. **Deterministic geometry:** same BuildingModel + same EngineConfig ⇒ identical geometry. No randomness/time in builders (see `docs/3d-engine.md`).

## Recorded product decisions (2026-09-27)

- Region: Kazakhstan · Currency: KZT (USD/EUR/others via additional catalogs) · Default catalog: `kz-almaty-demo` (demo rates)
- AI: `MockAIProvider` (dev/tests) → `AnthropicProvider` (first real) → OpenAI-compatible adapter (later)
- Rules: `generic-residential@1` profile, conceptual validation only; regional profiles later
- First 3D milestone: hand-authored 2-floor house (rooms, walls, doors, windows, floors, stairs, roof, basic furniture) with rotate/zoom/pan, select, isolate floors, inspector, layer toggles

## Tech stack (decided)

- **Web**: Next.js (App Router), React, TypeScript strict, React Three Fiber, three, @react-three/drei, Zustand, TanStack Query, Tailwind CSS, Zod. pnpm workspaces. Node 22.
- **API**: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async, asyncpg), Alembic, PostgreSQL 16, JWT (access 15 min) + rotating hashed refresh tokens (httpOnly cookie), argon2id. shapely for polygon ops. uv for packaging.
- **Infra**: Docker, Docker Compose. Root `package.json` scripts are the task entry point (work on Windows); `Makefile` mirrors them.
- **Tests**: pytest, Hypothesis, httpx; Vitest, React Testing Library, Playwright.
- **Quality**: ruff, mypy (strict for domain modules), import-linter; ESLint, Prettier, `tsc --noEmit`.

## Repository layout

```
apps/web/src/{app,features,engine,viewer,stores,lib,schema}
apps/api/app/{core,shared,modules/{auth,projects,versions,building,rules,catalog,layout,mep,quantities,costing,ai,jobs,reports}}
apps/api/{alembic,tests,evals}
packages/schema/          # generated
data/{materials,cost-catalogs,rules-profiles,knowledge,fixtures}
docs/  infra/  docker-compose.yml  Makefile
```

- Backend module shape: `router.py` (HTTP only) → `service.py` (use cases, transactions) → `repository.py` (SQLAlchemy) ; `models.py` ORM, `schemas.py` DTOs.
- Frontend: `engine/` is pure TS (no React, no stores) — geometry builders `(element, ctx) → RenderDescriptor[]`, all drawing through `engine/geometry/mesh-builder.ts`. `viewer/` is R3F. `features/*` are vertical slices.
- 3D rules: model→world conversion only via `engine/math/coords.ts` + the `ModelRoot` group; materials only from `data/materials/library.json` via `MaterialCache`; every mesh carries only `{ elementId, part }` and maps to one model element; new element types need a schema class, a builder in `engine/builders/registry.ts`, and tests (see `docs/3d-engine.md`).
- Rendering (V1 visual quality, `docs/3d-engine.md` §21): look-dev constants only in `viewer/render-settings.ts`; textures/HDRI only CC0 (ambientCG, Poly Haven), stored in `data/materials/{textures,hdri}` and recorded in `data/materials/ASSETS.md`, referenced from `library.json` with `tile_size_m`; a missing texture must fall back to the flat library color; no runtime CDN.
- Furniture models and site (V2, `docs/3d-engine.md` §22): CC0 glTF models are listed in `data/materials/models.json` and stored in `data/materials/models/` (meshopt, recorded in ASSETS.md). **Recorded exception (2026-11-01):** furniture and vegetation models keep their embedded CC0 materials; building elements still take materials only from `library.json` via `MaterialCache`. Furniture models are fitted to the element's width × depth × height (the model stays the source of truth); the placeholder stays the pick proxy and the fallback. The site (`planSite`) is environment only: derived deterministically from the model, never stored in it, never pickable.
- State: server state in TanStack Query; the model being edited + view state (selection, isolation, layers, camera mode) in Zustand with granular selectors.

## Conventions

- Python: snake_case, type hints everywhere, Pydantic models for every boundary, no bare `dict` in public domain APIs. Async in I/O layers only; domain code is sync.
- TS: camelCase in code; **API JSON is snake_case** (matches Pydantic/generated types — don't remap). No `any`. Components PascalCase; hooks `useX`.
- API: `/api/v1/...`, error envelope `{error:{code,message,details}}`, validation issues carry JSON-pointer `path`.
- IDs: UUIDv4 generated in application code.
- Migrations: one Alembic revision per schema change, reviewed by hand, reversible.
- JSONB document shape changes: bump `schema_version` and add a migration in `building/migrations/`.
- Shared test fixtures live in `data/fixtures/` and are used by both Python and TS tests.

## Testing rules

- Every domain function gets unit tests; layout changes need invariant (Hypothesis) tests and, if output changes, deliberate golden-file updates (explain why in the commit).
- Bug fix ⇒ regression test first.
- Before saying work is done: run `pnpm lint`, `pnpm typecheck`, `pnpm test` (or the per-app equivalents) and report real results.
- Changing Pydantic building schemas ⇒ run `pnpm schema` and commit generated output. Changing the demo fixture script ⇒ run `pnpm fixtures`.

## Commands (run from repo root)

```
pnpm install                 # JS deps (workspace)
pnpm api:install             # Python deps: uv sync in apps/api
pnpm db:local                # embedded PostgreSQL for local dev (no Docker); prints DATABASE_URL; --stop to stop
pnpm dev                     # web (3000, proxies /api) + api (8000); needs DATABASE_URL in .env
pnpm docker:up               # docker compose up --build (db, api, web)
pnpm lint                    # eslint + ruff + import-linter
pnpm typecheck               # tsc --noEmit + mypy
pnpm test                    # vitest + pytest (pytest auto-starts embedded Postgres unless TEST_DATABASE_URL is set)
pnpm check                   # lint + typecheck + test
pnpm migrate                 # alembic upgrade head
pnpm schema                  # regenerate packages/schema (model + spec + AI API JSON Schemas, TS types) from Pydantic
pnpm fixtures                # regenerate data/fixtures/demo-house.model.json from its authoring script
pnpm golden                  # regenerate layout golden files (data/fixtures/golden) + generated-house fixture
pnpm knowledge:lock          # re-hash data/knowledge after a reviewed knowledge change (knowledge.lock.json)
pnpm benchmark               # Design Intelligence benchmark (data/fixtures/benchmark), offline mock interpreter
```

Local environment notes (dev machine is Windows): `uv` may only be available as `py -3.12 -m uv`; the scripts in `package.json` call `uv` through `scripts/uv.mjs`, which falls back automatically. `make` is optional. `pnpm db:local` may come up on a new port after a restart — copy the printed `DATABASE_URL` into `.env`. The `api` preview config runs uvicorn without `--reload`: restart it after backend changes.

## Layout engine notes (Phase 2)

- Entry point `layout.engine.generate_layout(spec, profile, *, id_namespace, seed, ...)`; design in `docs/3d-engine.md` §16. The generation service passes the project id as `id_namespace`.
- Determinism: the only randomness is the seeded `random.Random` in the candidate search. Never break ties on object identity (`id()`), memory order, set/dict-of-hash iteration or float noise — a test runs the engine under two `PYTHONHASHSEED`s.
- Any change to layout output (incl. furniture) changes the golden files: run `pnpm golden` deliberately and explain the change in the commit. Bump `ENGINE_VERSION` in `layout/config.py` when generated models change meaningfully.
- Generated models must pass `validate_model` with no errors and no `ROOM_UNREACHABLE`, and `rules.model_checks` with no findings, for all reference specs (`data/fixtures/specs`).
## AI generation notes (Phase 3)

- Pipeline and contracts: `docs/ai-pipeline.md`. The AI answers only with a `SpecificationDraft` (structured output, JSON Schema from Pydantic) — never geometry, costs or code. Output is validated (Pydantic → `rules.spec_checks` → form fields); at most `AI_MAX_REPAIRS` (default 1) repair calls; invalid output is never accepted.
- Providers: `MockAIProvider` (deterministic, dev/tests/CI, refused in production) and `AnthropicProvider` (`AI_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, `AI_MODEL` — config only, never a model name in business logic). The `anthropic` SDK is imported only in `ai/providers/anthropic.py` (import-linter contract).
- Prompts live in `ai/prompts/`; changing their wording or structure = bump `PROMPT_VERSION`. The vocabulary in the prompt is generated from the spec enums, and dimensional numbers come from the rules profile — don't hard-code either.
- The generation use case orchestrates only; layout goes through `generation.pipeline.layout_and_save` (shared with the spec form). Record real stages on `ai_generations`; never show invented progress.
- Changing the mock interpreter must keep every mock prompt in `tests/ai/test_mock_provider.py` laying out without errors.
- Changing AI API DTOs (`ai/schemas/responses.py`) ⇒ `pnpm schema` (the web uses the generated validators) and refresh `apps/web/src/features/ai/__fixtures__` from a real response if the shape changed.
- Live Anthropic test: `RUN_LIVE_AI_TESTS=true` only; never in CI.

## Design Intelligence notes (layout@1.4.0)

- Design: `docs/building-model.md` §2.4, `docs/3d-engine.md` §16.9, `docs/knowledge.md` §3.6. Spec 1.2.0: `requirements[]` traces (MUST/SHOULD, origin, quote), `design.priorities`, `rooms[].max_area_m2`, `rooms[].separate_from`. Don't add intent fields the engine or evaluation does not consume.
- A MUST requirement is never relaxed: the engine ranks candidates by unmet MUSTs first, runs a bounded repair, then fails with `LAYOUT_REQUIREMENTS_UNMET`. SHOULD misses are reported as warnings, never hidden.
- `building/evaluation.py` evaluates the built model (not the plan); the benchmark (`apps/api/evals/design_benchmark.py`) computes its facts independently — keep it that way, so the engine never grades itself. Never weaken a benchmark expectation to match output; record a `known_gap` with the reason instead.
- Patterns only change scores, never the rectangular skeleton list (seeding). Pattern selection reads the spec, never free text.
- L footprints (layout@1.5.0, docs/3d-engine.md §16.10): single storey only; L skeletons are appended after the rectangular ones (rectangular seeds and golden geometry must not change). A requested shape is a requirement; a pattern-suggested L only competes on the evaluation. Report the shape measured on the model (`measure_footprint`), never the plan's intention. Rectangular envelopes keep their wall keys S/E/N/W.
- L layout quality (layout@1.6.0, docs/3d-engine.md §16.11): wing end-room wrap, corridor dead-end cuts and far-end alignment apply to wing plans only (L and T, `sk.has_wing`); garden-sized L skeletons come after all other L skeletons; the wing may stand on either side of a garage. Never let a cut remove the corridor end with the garage door, join a bedroom/study with a living space, or join rooms the spec keeps apart. Room outlines are position + offset sums with float noise: `measure_footprint`, the benchmark and tests measure them on the 1 mm grid; `building/evaluation.py _Facts` does not yet (doing so changes the chosen candidate of reference specs 01 and 08 — open decision).
- Footprint shapes (layout@1.7.0, docs/3d-engine.md §16.12): what can be generated is `building/footprint.py CAPABILITIES` only (rectangular; L and T single-storey; U and courtyard recognised, not generated) — never treat a recognised shape name as supported. Both interpreters read shapes with `SHAPE_WORDS` and `shape_priority` (an explicit request is MUST, softened wording SHOULD; `normalize_shape_requirement` applies it to any model's answer). A required shape without a generator is refused with the reason (`SPEC_FOOTPRINT_UNSUPPORTED`, not repairable by an AI call; `LAYOUT_SHAPE_UNSUPPORTED` in the engine) — never a silent rectangle. Depth bars are a fallback family per wing topology (only when the ratio bars give no feasible layout), so established L results never change. A new topology needs a CAPABILITIES entry, a skeleton generator in `WING_SKELETONS` (or its own), an `envelope` branch, a `measure_footprint` classification, benchmark cases and a web 3D-engine fixture test.

## Architectural design quality notes (layout@1.8.0, V3)

- Design: `docs/3d-engine.md` §16.13 and §23, `docs/building-model.md` (schema 1.3.0). Facade zoning changes **finishes only** (`finish_right_id`); wall cores keep the spec's facade material (the benchmark checks them). A requested facade colour disables zoning. Zoning and canopy material follow the architectural style (an approved design system's first style tag first) via `LayoutConfig` — design systems are drafts and carry no zoning yet.
- Entrance canopies are `slab_kind: canopy` slabs: untyped, no `supports` relationship, excluded from the floor-slab checks, validated by `slab.canopy`. Gable-end infill and parapet finishes are derived by the web roof builder from the roof's supporting walls (not stored).

## Facade grid notes (layout@1.9.0, V4)

- Design: `docs/3d-engine.md` §16.14. Partitions snap to the other storeys' facade grid only where every room keeps its minimum width/area and permitted area range (never relax a requirement or a rules limit to align a window). `facade_grid_snap = 0` must keep reproducing layout@1.8.0 (test). Alignment is measured on the built model in `tests/layout/test_facade_grid.py`; never weaken its threshold to match output.

## Facade bay grid notes (layout@1.11.0, V5)

- Design: `docs/3d-engine.md` §16.15. Bays come from the footprint (`layout/bays.py`, numbers in `LayoutConfig`); the search never sees them — the chosen design is re-laid on bays (`planner.rebay`) and kept only if it is valid, meets every MUST the original meets, scores no lower and adds no area deviation. `facade_bays = False` must reproduce layout@1.9.0 (test pins main's geometry fingerprints). Side-facade rhythm never on an excluded facade nor with a `privacy` priority.

## Window consistency notes (layout@1.14.0, V6)

- Design: `docs/3d-engine.md` §16.16. Merges, width unification and head alignment only happen where the room keeps its required glazing; sills are only raised (service and guard sills kept). `window_consistency = False` must reproduce layout@1.11.0 (test pins main's geometry fingerprints).

## Bay-aware rooms notes (layout@1.15.0, V7)

- Design: `docs/3d-engine.md` §16.17. `window_quick_wins = False` must reproduce layout@1.14.0 (test pins main's geometry fingerprints). Window-moving passes must terminate (each window moves at most once) and never break a stack across storeys to fix a pair. Rooms on whole bays need planner changes (bay-multiple skeletons appended after the existing ones, integer-bay bands); a ranking bonus alone does not get there (recorded finding).

## Knowledge notes (Phase 3.5)

- Design: `docs/knowledge.md`. Steps K1 Foundation → K2 Families/Types/Assemblies → K3 Design Systems → K4 Templates → K5 Knowledge API and Units → K6 Optional Structural Elements; don't rename, merge or start a step before the previous one is reviewed.
- **Knowledge is not rules.** Knowledge packs never hold enforceable minimums/maximums; those stay in rules profiles. Only `approved` knowledge and component records may ever be consumed by engines or AI — with one recorded exception (2026-10-26, decision 16): **layout patterns** (`buildai-layout-patterns@1`) are soft heuristics; draft patterns may steer the search but never create, relax or override a requirement or a rules limit, and every use is reported with its status. Never mark a pattern statement `source_rule` without a reviewed published source. Only `generation.pipeline` imports the catalog (import-linter contract): it resolves approved types (`catalog.resolver`), checks them against the rules profile (`rules.type_checks`, refuse — never resize) and passes a `building.types.TypeSet` to the layout engine.
- Every knowledge object needs provenance (source + printed pages) and a status. Source-derived knowledge starts `extracted`/`needs_verification`, editorial knowledge `draft`. Never mark knowledge reviewed/approved without a human review.
- Paraphrase only; never copy source text or reproduce figures/symbols; record inferences in `inferences`; never invent source-derived facts.
- Georgievsky 2004 is one source, scoped as the `spds` drawing-convention profile, never global. The `core` pack may cite published sources only for existence.
- Packs are immutable once used (new `.v<n>`); after any data change run the tests and `pnpm knowledge:lock`. New element/room types or relationship kinds need a `core` ontology entry.
- K2 types: `buildai-generic-types@1` stays `draft` until a person reviews it; it must keep reproducing `LayoutConfig` exactly (test). Never add types derived from unapproved knowledge (e.g. the GOST window table) as usable records. New layout roles go into `building/types.py TYPE_ROLES` and every role mapping.
- Stored models are read only through `building.migrations.load_model` (upgrade-on-read; never rewrite stored rows). A schema change keeps `geometry_sha256` in the golden files unchanged unless geometry is meant to change.

## Geometry notes (Phase 3.5 K2.5)

- Design: `docs/building-model.md` §4.1 (geometric invariants) and `docs/3d-engine.md` §16.7 (constraint-aware generation). Geometric invariants, knowledge, rules and design intent stay separate: `building/constraints.py` holds geometric constraints only — never a dimensional minimum/maximum (rules profile) and never a knowledge item.
- Every geometric check has a catalog entry (`CONSTRAINTS`: id, code, severity, statement) and a row in building-model.md §4.1 (a test keeps them in sync). Findings carry `constraint`, `related_ids`, `measure`; checks never modify the model.
- Openings stay host-relative (`hosted_by`, `position.x` offset, `position.z` sill). Opening placement in the layout engine and opening validation use the same `building/hosting.py` arithmetic — keep it that way.
- Coordination axes are derived from walls (`building/axes.py`), not stored.
- Local constraints in the search must not change the seeding of other candidates: skip inside the loop, never drop skeletons from the list (`sk_index` seeds the RNG).
- Tolerances: `EPS` for stored coordinates, `DERIVED_TOLERANCE` for derived heights, `OVERLAP_AREA_TOLERANCE` for polygon contact (`building/geometry.py`); don't invent new ones ad hoc.

## Plan drawing notes (Phase 3.6)

- Design: `docs/3d-engine.md` §19. Floor plans are derived from the BuildingModel by `engine/drawing` (pure TS): `buildPlanDrawing` → `renderPlanContent` / `buildPlanSheet`. The on-screen plan and every download (SVG, PNG, PDF) use the same SVG; never add a second renderer.
- Every drawn group maps to one element (`elementId`) or is an annotation; room names and areas come from the model, never from the drawing. Wall gaps use `computeWallJoins` + `wallPanels`, like the 3D walls.
- Units: model meters in, paper mm out; text is fitted for the scale. No clock or randomness in the engine (the sheet date is passed in).
- The SVG uses presentation attributes only (no CSS classes) so svg2pdf and image conversion render it; data attributes only with `interactive: true`.
- Plan editing (D2, `docs/3d-engine.md` §20, `docs/building-model.md` §5.1): operations live in `building/operations` (pure); `modules/editing` replays them on the stored base version and accepts the result only if it adds no model error, no rules-profile finding and no circulation pinch. The client keeps only the operation list (undo/redo cursor) and renders the model the API returned — never apply geometry changes in the web app. New operations join the `Operation` union with a refusal code per impossible case and tests that every result is refused or consistent; build them from existing operations where the meaning allows (`resize_room` = `move_wall` on the side's walls). MUST requirements of the version's spec that the base meets must stay met (`EDIT_REQUIREMENT_UNMET`). Doors/windows (D2.3, `building/operations/openings.py`, `docs/building-model.md` §5.3): `move_opening` / `add_opening` / `remove_element` (openings only) reuse `hosting.py` arithmetic; an edit may not introduce `ROOM_UNREACHABLE`, `NO_ENTRANCE` or `HABITABLE_ROOM_WITHOUT_WINDOW`, nor remove the last entrance door; openings an edit places keep the profile's `openings.min_clearance_m` (never a hard-coded margin). D2.4 (`docs/building-model.md` §5.4): `resize_opening`, `remove_wall` (interior; open or `merge_rooms`), `rename_room`, `set_room_type`, `add_wall` (divides a room, §5.5) — a spec room retyped or merged away is a warning, or blocked when it carries a MUST (`program_changes`); prepared changes are checked live as the session's `draft`. D2.5 (`docs/building-model.md` §5.6): an exterior `move_wall` moves the whole facade (`building/operations/envelope.py`: every storey, slabs, roofs, balconies, terraces, canopy) or is refused with the reason (`FACADE_CONTINUES`, `VOLUME_ATTACHED`, `FACADE_CUTS_STAIR`, `ROOF_CANNOT_FORM`, …); `set_wall_thickness` / `set_wall_finish` / `set_wall_height` — wall thickness limits come only from the profile's `walls` section, never from operations.

## Working agreements for Claude

- Read the relevant `/docs` file before changing a subsystem; update docs when behavior or decisions change.
- Prefer small, reviewable changes that follow the roadmap phase order.
- Don't add dependencies without stating why; prefer the decided stack.
- Don't introduce new element types, operations, or schema fields without updating `docs/building-model.md`.
- Never commit secrets; config via env vars (`.env`, with `.env.example` checked in).
