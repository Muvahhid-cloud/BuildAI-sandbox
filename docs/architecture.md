# BuildAI 3D — System Architecture

Status: **Accepted (v0.2)** · Owner: Architecture · Last updated: 2026-09-28

This document is the top-level map. Deep dives:

| Topic | Document |
|---|---|
| BuildingSpecification & BuildingModel schemas | [building-model.md](building-model.md) |
| AI providers, prompting, validation loop, modification | [ai-pipeline.md](ai-pipeline.md) |
| Layout engine, procedural geometry, viewer | [3d-engine.md](3d-engine.md) |
| PostgreSQL schema, versioning storage | [database.md](database.md) |
| Architectural knowledge packs (Phase 3.5) | [knowledge.md](knowledge.md) |
| Phased delivery plan | [roadmap.md](roadmap.md) |

---

## 1. Guiding principles

1. **The BuildingModel is the source of truth.** Meshes, quantities, costs, reports and AI analyses are all *derived* from it. Nothing derived is ever edited directly.
2. **AI produces intent, never geometry.** The LLM emits a `BuildingSpecification` (what the client wants) or a `ModificationPlan` (typed operations). Deterministic code turns intent into coordinates. This keeps results reproducible, testable and valid.
3. **Deterministic core.** Given the same spec + seed + engine version, the layout engine produces a byte-identical model. Randomness only through an explicit seed.
4. **Modular monolith.** One FastAPI service, one Next.js app, one PostgreSQL database. Modules have hard boundaries (enforced by import rules) so they can be extracted later — but not before there is a measured reason.
5. **Pure domain, thin adapters.** Building, layout, MEP, quantities and costing are pure Python packages with no FastAPI/SQLAlchemy imports. HTTP and persistence are adapters around them.
6. **Residential first.** Single-family houses, 1–3 storeys, rectilinear plans. We are *not* building Revit. Every feature is judged against "does it help a homeowner/small builder get a credible early-stage design + budget?"
7. **Schemas are contracts.** Pydantic models are canonical; JSON Schema, TypeScript types and Zod validators are generated from them. Drift fails CI.

---

## 2. End-to-end pipeline

```
 ┌────────────┐   prompt    ┌──────────────┐  BuildingSpecification  ┌──────────────┐
 │  Browser   │────────────▶│  AI module   │────────────────────────▶│  Validation  │
 │ (Next.js)  │             │ AIProvider   │◀── errors fed back ─────│ schema+rules │
 └────────────┘             └──────────────┘   (max 2 repairs)       └──────┬───────┘
       ▲                                                                    │ valid spec
       │                                                                    ▼
       │  BuildingModel JSON                                       ┌──────────────────┐
       │  + Quantities + Cost                                      │  Layout engine   │
       │                                                           │ (constraints,    │
       │                                                           │  seeded search)  │
       │                                                           └────────┬─────────┘
       │                                                                    │ architectural model
       │                                                                    ▼
       │                                                           ┌──────────────────┐
       │                                                           │  MEP generator   │
       │                                                           │ plumbing/elec/   │
       │                                                           │ HVAC (schematic) │
       │                                                           └────────┬─────────┘
       │                                                                    │ full BuildingModel
       │                   ┌──────────────┐    ┌──────────────┐    ┌───────▼──────────┐
       └───────────────────│ AI analysis  │◀───│   Costing    │◀───│   Quantities     │
                           │ (optional)   │    │ catalog×qty  │    │ takeoff          │
                           └──────────────┘    └──────────────┘    └──────────────────┘

 In the browser:  BuildingModel ──▶ mesh builders (pure TS) ──▶ React Three Fiber scene
```

Modification loop:

```
"Make the kitchen 2 m wider and add a skylight"
  → AI: ModificationPlan { operations: [ResizeRoom, AddElement(skylight)], requires_relayout: false }
  → validate ops against current model
  → apply ops (pure function) → regenerate derived elements (walls/openings rehost, MEP)
  → diff vs. current version → user previews → commit as new ProjectVersion
  → quantities + cost recomputed
```

---

## 3. Repository architecture

Monorepo, two applications, one shared generated-contract package.

```
/
├── apps/
│   ├── web/                    # Next.js (App Router) + R3F viewer
│   └── api/                    # FastAPI modular monolith
├── packages/
│   └── schema/                 # GENERATED: JSON Schema, TS types, Zod validators
├── data/
│   ├── cost-catalogs/          # seed unit-rate catalogs (YAML)
│   ├── materials/              # material library (library.json: render + validation; costing fields in Phase 4)
│   ├── rules-profiles/         # BuildingRulesProfile YAML (generic-residential@1, …)
│   ├── knowledge/              # versioned, source-attributed knowledge packs + lock (Phase 3.5)
│   └── fixtures/               # canonical specs/models used by tests on both sides
├── docs/
├── infra/
│   └── docker/                 # Dockerfiles
├── scripts/                    # cross-platform helpers (uv.mjs)
├── .github/workflows/ci.yml
├── docker-compose.yml
├── Makefile                    # single entry point for common tasks
├── CLAUDE.md
└── README.md
```

Tooling decisions:

| Concern | Choice | Why |
|---|---|---|
| JS package manager | **pnpm workspaces** | Fast, strict, first-class monorepo support |
| Python package manager | **uv** | Fast, lockfile, manages Python version |
| Python | 3.12 | Stable, typed, good perf |
| Node | 22 LTS | Next.js requirement |
| Lint/format (Py) | ruff + mypy (strict on domain packages) | |
| Lint/format (TS) | ESLint + Prettier, `strict` TS | |
| Module boundaries (Py) | import-linter contracts | Keeps domain pure |
| Task runner | **Root `package.json` scripts** (`pnpm dev`, `pnpm test`, `pnpm lint`, …) calling pnpm/uv/docker; a thin `Makefile` mirrors them for Linux/macOS/CI | Works on Windows without `make`; one command surface for humans and Claude |

`data/fixtures/` is shared by backend and frontend tests: e.g. `simple-house.model.json` is used by Python quantity tests *and* by TS geometry-builder tests, so both sides agree on the same inputs.

---

## 4. Backend architecture (FastAPI modular monolith)

```
apps/api/
├── pyproject.toml
├── alembic/                     # migrations
└── app/
    ├── main.py                  # app factory, router registration
    ├── core/                    # config (pydantic-settings), db session, security, logging, errors
    ├── shared/                  # small cross-cutting utils (ids, geometry math, units)
    └── modules/
        ├── auth/                # users, JWT, refresh tokens
        ├── projects/            # project CRUD, membership
        ├── versions/            # versions, drafts, diff/compare
        ├── building/            # ★ DOMAIN: spec + model schemas, validation (incl. geometric checks, K2.5), operations
        ├── rules/               # ★ DOMAIN: BuildingRulesProfile schema + evaluator (configurable, regional)
        ├── catalog/             # ★ DOMAIN: architectural knowledge packs (loader, registry, integrity, lock); read-only, not consumed in K1
        ├── layout/              # ★ DOMAIN: spec → architectural model
        ├── mep/                 # ★ DOMAIN: plumbing / electrical / HVAC generation
        ├── quantities/          # ★ DOMAIN: model → quantity takeoff
        ├── costing/             # ★ DOMAIN: takeoff × catalog → estimate; catalog persistence
        ├── ai/                  # AIProvider (mock, anthropic), prompts, interpreter (validate/repair),
        │                        # NL generation use case + history (Phase 3), context, read-only tools
        ├── generation/          # use case: validate spec → layout job → version; shared layout_and_save pipeline
        ├── jobs/                # job table + in-process runner (async work)
        └── reports/             # report assembly (HTML → PDF)
```

Each non-domain module follows the same shape:

```
module/
├── router.py      # FastAPI routes, request/response DTOs only
├── service.py     # use-case orchestration; transaction boundary
├── repository.py  # SQLAlchemy queries
├── models.py      # SQLAlchemy ORM tables
└── schemas.py     # API DTOs (Pydantic)
```

★ Domain modules contain only pure Python (Pydantic + stdlib + numpy/shapely where needed). **Rule: domain modules never import FastAPI, SQLAlchemy, `core.db`, or `ai`.** Enforced by import-linter in CI, together with "core does not depend on feature modules" and "vendor AI SDKs are imported only by their provider adapter".

Dependency direction:

```
router → service → { repository, domain modules, ai }
ai → building, rules (schemas), generation.pipeline (use case); vendor SDKs only in ai/providers/<vendor>.py
rules → building (schemas only)
catalog → building (schemas only); generation → catalog (approved component types, K2); engines never import catalog (import-linter)
layout → building, rules  mep → building, rules
quantities → building    costing → quantities, building
```

### 4.1 API surface (v1, REST, JSON)

All routes under `/api/v1`. OpenAPI generated automatically.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout` | Auth |
| GET/POST | `/projects` | List / create |
| GET/PATCH/DELETE | `/projects/{id}` | Project CRUD (delete = soft) |
| POST | `/projects/{id}/generate` | ☑ Phase 2: `{spec, seed, label?}` → 202 job (layout → new version); tier-1/2 spec errors → 422 `SPEC_INVALID`; one active generation per project (409) |
| POST | `/ai/generate-building` | ☑ Phase 3: `{project_id?, prompt, options}` → 202 AI generation (NL → spec → validation/repair → layout → new version); without `project_id` a project is created; 409 busy, 429 rate limit, 503 provider not configured |
| GET | `/ai/generations/{id}` | ☑ Poll an AI generation: real stage, spec, assumptions, warnings, summary, requested-vs-delivered checks, version, error |
| GET | `/projects/{id}/generations` | ☑ AI generation history of a project |
| GET | `/jobs/{id}` | ☑ Poll job status / real stage / result / error (owner only) |
| POST | `/projects/{id}/spec/validate` | ☑ Validate a spec (schema + rules profile) without generating |
| GET | `/projects/{id}/versions` | ☑ Versions, newest first (summaries only) |
| GET | `/projects/{id}/versions/{vid}` | ☑ Full version: spec + model + generation report + rules/model findings evaluated on read |
| POST | `/projects/{id}/versions/demo` | ☑ Store the hand-authored demo house as a new version |
| POST | `/projects/{id}/versions/{vid}/modify/plan` | NL → ModificationPlan (preview, no write) |
| POST | `/projects/{id}/versions/{vid}/edits/preview` | Replay typed ops on the version and validate; returns the model or why not (nothing stored) — Phase 3.6 D2 |
| POST | `/projects/{id}/versions/{vid}/edits` | Replay + validate typed ops → new version (source `manual`, 422 `EDIT_REJECTED` if invalid) — Phase 3.6 D2 |
| GET | `/projects/{id}/versions/{vid}/quantities` | Takeoff |
| GET | `/projects/{id}/versions/{vid}/cost?catalog=` | Estimate |
| GET | `/projects/{id}/compare?a=&b=` | Element/quantity/cost diff |
| POST | `/projects/{id}/versions/{vid}/analysis` | AI analysis job |
| POST | `/projects/{id}/versions/{vid}/reports` | Report generation job |
| GET | `/cost-catalogs` | Available catalogs (region/currency/date) |
| GET | `/demo/building-model` | Public: the hand-authored demo house, validated before serving (Phase 1) |

### 4.2 Long-running work

LLM calls + layout search take 5–60 s (the Phase 2 layout engine alone: 0.05–1 s). Implemented: a `jobs` table (spec-form generation) and the `ai_generations` table (NL generation, docs/ai-pipeline.md §6) plus in-process `asyncio` background tasks (`modules/jobs/runner.py`; the CPU-bound layout runs in a worker thread); the client polls `GET /jobs/{id}` via TanStack Query and shows the job's real stages. The job interface (`enqueue(kind, payload) → job_id`) is designed so a real worker (arq + Redis) can replace the in-process runner without API changes. We add Redis only when we run >1 API replica or jobs outgrow the request process.

### 4.3 Authentication

- Passwords hashed with **argon2id**.
- **Access token**: JWT, 15 min, sent as `Authorization: Bearer`.
- **Refresh token**: opaque random, 30 days, httpOnly+Secure+SameSite=Lax cookie, stored **hashed** in DB, rotated on every use, reuse detection revokes the family.
- Authorization: project-level roles (`owner`, `editor`, `viewer`) checked in the service layer.

### 4.4 Errors

Uniform error envelope: `{ "error": { "code": "SPEC_INVALID", "message": "...", "details": [...] } }`. Validation issues always carry a JSON pointer path (`/rooms/3/target_area_m2`) so the UI can highlight them.

---

## 5. Frontend architecture (Next.js)

```
apps/web/src/
├── app/                         # App Router
│   ├── (auth)/login, register
│   ├── projects/                # project list
│   └── projects/[projectId]/    # editor (client-heavy)
├── features/                    # vertical slices: UI + hooks + api for one feature
│   ├── ai/                      # NL generator (prompt form, real-stage progress, clarification,
│   │                            # summary over the 3D view, history) — generated contracts
│   ├── auth/
│   ├── projects/
│   ├── generation/              # specification form, job progress
│   ├── editor/                  # layout shell, model tree, inspector
│   ├── modification/            # NL edit, plan preview, diff apply
│   ├── quantities/
│   ├── costing/
│   ├── versions/                # history tree, compare view
│   └── reports/
├── engine/                      # ★ pure TS: BuildingModel → THREE geometry. No React.
│   ├── builders/                # one builder per element type
│   ├── materials/               # material library → THREE materials (cached)
│   ├── scene-graph.ts           # model → render descriptors grouped by level/layer
│   └── math/
├── viewer/                      # React Three Fiber components using engine/
│   ├── Viewer.tsx, ElementMesh.tsx, LevelGroup.tsx
│   ├── controls/                # orbit, walk (first-person), section box
│   └── overlays/                # selection outline, dimensions, labels
├── stores/                      # Zustand
├── lib/                         # api client, auth, query client
└── schema/                      # re-export of @buildai/schema (generated)
```

### 5.1 State management split

| Kind of state | Owner | Examples |
|---|---|---|
| Server state | **TanStack Query** | projects, versions, jobs, quantities, cost |
| Current editing model | **Zustand `modelStore`** | loaded BuildingModel, pending ops, dirty flag |
| View state | **Zustand `viewStore`** | selection, hovered id, isolated level, visible layers, camera mode, section plane, x-ray |
| UI chrome | **Zustand `uiStore`** | panel sizes, open tabs |

Rules: never copy query data into Zustand except the model being edited; selectors must be granular (`useViewStore(s => s.selectedId)`) because the 3D scene re-renders are expensive.

### 5.2 Server authority

The backend is authoritative for applying operations and regenerating derived geometry. The client sends operations and renders the returned model. This keeps exactly one implementation of the ops engine (Python) during the MVP. If direct manipulation (dragging walls) needs sub-100 ms feedback later, we port the *operation applier* (not the layout engine) to TS and cross-test it against the same fixtures.

### 5.3 Validation on the client

Generated Zod schemas validate every API payload at the boundary (`lib/api.ts`). A model that fails Zod is a bug, surfaced loudly in dev.

---

## 6. Cross-cutting decisions (ADR summary)

| # | Decision | Alternatives rejected | Rationale |
|---|---|---|---|
| ADR-001 | Two-level schema: **Specification (intent)** → **Model (resolved elements)** | AI emits model directly | LLMs are bad at consistent coordinates; intent is small, checkable, editable |
| ADR-002 | Pydantic canonical; generate JSON Schema → TS + Zod | Hand-maintained dual schemas; TS canonical | Backend owns validation and geometry; one source avoids drift |
| ADR-003 | Store each version's model as **JSONB snapshot** | Normalized element tables | Models load/save whole; versions immutable; element count per house is small (≈1–5k) |
| ADR-004 | Model coordinates **Z-up, meters**, converted to Three.js Y-up at one root group | Y-up model | Matches architectural convention (plan = XY) and Python geometry libs |
| ADR-005 | Walls with openings built as **panel segments, no CSG** | three-bvh-csg | Deterministic, fast, and quantities never depend on mesh booleans |
| ADR-006 | Quantities computed from the **model in Python**, not from meshes | Measure meshes in browser | One truth; testable; reports run server-side |
| ADR-007 | Modifications are **typed operations**, not free-form model rewrites | LLM returns whole new model/spec | Small, reviewable, diffable, preserves UUIDs |
| ADR-008 | **Stable UUIDs** across regenerations via semantic keys | New IDs each generation | Needed for diff, selection persistence, user locks |
| ADR-009 | Money as **Decimal** with explicit currency; catalogs versioned by region/date | floats | Financial correctness and reproducibility |
| ADR-010 | In-process jobs first, worker later behind same interface | Celery from day 1 | Avoid infra before need |
| ADR-011 | MEP is **schematic** (rule-based routing), labeled "not for construction" | Engineering-grade design | Out of scope and liability; still gives quantities + visualization |
| ADR-012 | AI answers through **structured outputs** (JSON Schema of `SpecificationDraft`), validated by Pydantic + rules, **one** repair call at most | Forced tool use; free text + parsing; multi-call agents | Works on every current Claude model (newer models reject forced `tool_choice`); one call per generation; invalid output never accepted |
| ADR-014 | Architectural knowledge as **versioned, hash-locked YAML packs** with per-object provenance and a review lifecycle; only `approved` knowledge may be consumed; knowledge never replaces rules profiles (docs/knowledge.md) | Knowledge in the DB; RAG/vector search over sources; knowledge inside rules profiles | Reviewable diffs, reproducible loads, explicit attribution; no infra before need; keeps enforceable rules separate |
| ADR-015 | Models carry **self-contained type/assembly snapshots** (BuildingModel 1.1.0) resolved from approved catalog records; the engine receives a `TypeSet`, never the catalog; stored 1.0.0 models are upgraded on read, never rewritten | Types referenced by id only (catalog lookup at render/quantity time); rewriting stored versions | Immutable versions stay reproducible; renderers and quantities need no catalog; one read path |
| ADR-013 | AI generation runs as a background task recording its **real stage** on `ai_generations` (polled) | Synchronous request; SSE streaming | Same in-process runner as ADR-010; progress without invented percentages; history for free |

---

## 7. Infrastructure visualization architecture (summary)

Full details in [3d-engine.md §7](3d-engine.md) and [building-model.md §6](building-model.md).

- MEP elements are first-class model elements (`pipe_segment`, `duct_segment`, `conduit_run`, `fixture`, `equipment`, `terminal`) grouped into `System`s (e.g. `domestic_cold_water`, `sanitary_drain`, `lighting_circuit_2`, `supply_air`).
- Every element belongs to exactly one **discipline layer**: `architecture`, `structure`, `plumbing`, `electrical`, `hvac`, `site`.
- Viewer toggles layers; enabling any MEP layer switches architecture to *x-ray* (transparent, depth-write off) so services are visible through walls.
- Colors follow a fixed discipline palette (cold water blue, hot water red, drain brown, electrical yellow, supply air cyan, return air purple).
- Selecting a system highlights all its elements via the `part_of_system` relationship.

## 8. Cost calculation architecture (summary)

```
BuildingModel ──▶ quantities.takeoff(model) ──▶ [QuantityLine{item_code, unit, qty, element_ids, category}]
                                                   │
CostCatalog(region, currency, effective_date) ─────┤
                                                   ▼
                                costing.estimate(takeoff, catalog, params)
                                                   │
                  CostEstimate{lines, subtotals by category, labor, overhead %, contingency %, tax %, total}
```

- `item_code`s are a closed vocabulary (e.g. `CONC.SLAB.C25`, `MAS.WALL.BLOCK200`, `FIN.FLOOR.TILE`, `PLB.PIPE.PPR20`). Quantities and catalogs meet only through these codes.
- Material quantities include waste factors from the material library (e.g. tile +10 %).
- Unmapped item codes produce a **warning line** (cost 0, flagged), never a silent omission.
- Estimate is labeled *preliminary / order-of-magnitude (±25 %)*.
- Catalogs are data (YAML seeds → DB), editable per organization later.

**Region & currency (decided 2026-09-27):**

- Initial target region: **Kazakhstan**; primary currency **KZT**. Default catalog: `kz-almaty-demo` (KZT), flagged `is_demo: true` and labelled **"Demo / estimated rates — not market prices"** everywhere it is shown.
- The costing engine is **currency-agnostic**: every rate, line and total carries an ISO-4217 `currency`; the engine never assumes a currency and refuses to add amounts of different currencies. KZT, USD, EUR and others are supported by adding catalogs.
- Currency conversion (later) is an explicit, dated `ExchangeRateSet` applied to an estimate's output — never baked into catalogs.
- Display formatting per currency via `Intl.NumberFormat` (KZT: `₸`, 0 decimals by default; the catalog declares `minor_units`).
- **No prices in code.** Business logic only reads catalogs.

## 9. Versioning architecture (summary)

Full details in [database.md §4](database.md).

- `ProjectVersion` rows are **immutable** and form a tree (`parent_version_id`), so users can branch "Option A / Option B".
- Each version stores: full spec snapshot, full model snapshot, the operation list that produced it from its parent, engine + schema versions, and cached quantity/cost summaries.
- A per-user **draft** holds uncommitted edits; "Save version" commits it.
- **Compare**: element diff by UUID (added / removed / modified with field-level changes), plus quantity and cost deltas by category. The viewer can color-code a diff (green added, red removed, amber modified).
- Schema evolution: `schema_version` on every stored document; upgrade functions (`migrate_model_v1_to_v2`) run on read, lazily re-saved.

## 10. Testing strategy (summary)

| Layer | Tools | What |
|---|---|---|
| Domain (Py) | pytest, **Hypothesis** | Validation rules; layout invariants (no room overlap, all rooms reachable, openings inside host walls, area within tolerance); ops apply/inverse; quantities on hand-computed fixtures; cost arithmetic |
| Golden files | pytest snapshot | spec + seed → model JSON is stable; changes require explicit snapshot update |
| API | pytest + httpx + Postgres (testcontainers or compose service) | Auth, permissions, versioning, job flow end-to-end with MockAIProvider |
| Migrations | Alembic | upgrade head / downgrade base on empty DB in CI |
| AI | MockAIProvider in all automated tests; recorded fixtures for provider adapters; **offline eval suite** (prompt → spec scored against expectations) run manually/nightly | |
| Engine (TS) | Vitest | Builders produce expected vertex counts/bounds for fixtures; opening panels; no NaNs |
| UI (TS) | Vitest + React Testing Library | Panels, stores, forms |
| E2E | Playwright | Login → prompt → model renders → select wall → inspector shows props → modify → compare |
| Contracts | CI job | Regenerate `packages/schema` and fail on diff |

Coverage targets: domain modules ≥ 90 %, services ≥ 80 %. Performance budget test: fixture house (≈3k elements) builds geometry < 300 ms and renders ≥ 50 fps on a mid-range laptop.

---

## 11. Professional-review disclaimer

BuildAI 3D produces **conceptual** designs, schematic MEP layouts and preliminary cost estimates. Rules profiles perform conceptual checks only. The platform is **not** a replacement for licensed architectural, structural, MEP or regulatory review. This statement appears in the README, the app footer/about page, every report, every cost view, and every rules-validation panel (single source: `DISCLAIMER` constant in the web app and `app/core/disclaimer.py` in the API).

## 12. Non-goals (for now)

- Structural analysis / code-compliance certification
- Engineering-grade MEP sizing
- Curved/free-form architecture, non-residential typologies
- Real-time multi-user co-editing (versions + drafts are enough initially)
- IFC/DWG export (planned later; model is designed to map to IFC entities)
- Microservices, Kubernetes, event buses
