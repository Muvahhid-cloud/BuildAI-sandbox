# BuildAI 3D

AI-assisted residential building design. Describe a house in plain language and get a validated, element-level, procedural 3D building model. Material quantities and a preliminary construction cost are **planned** (Phase 4) and not implemented yet.

> "Create a modern two-story house with 280 m², 4 bedrooms, 3 bathrooms, a large open kitchen and living room, a two-car garage, balcony, panoramic windows and minimalist design."

```
Implemented:  Natural language → AI → BuildingSpecification → Validation → Layout engine
                → BuildingModel (walls, rooms, doors, windows, slabs, stairs, roofs… as typed objects)
                → Geometric validation → Procedural 3D (Three.js / React Three Fiber)
Planned:      → Quantities → Cost → MEP → AI analysis → Reports / IFC export
```

The AI produces **structured building data**, not images or geometry. A deterministic engine turns that data into geometry, so every wall, room, door and window is a real, selectable object with its own properties.

Initial market: **Kazakhstan (KZT)**. Costing (planned) is currency-agnostic.

## Project information (diploma)

| | |
|---|---|
| Title (EN) | Development and Implementation of an Intelligent BIM-Based 3D Platform for AI-Assisted Generative Building Design |
| Title (RU) | «Разработка и внедрение интеллектуальной BIM-ориентированной 3D-платформы BuildAI 3D для генеративного проектирования зданий с применением искусственного интеллекта» |
| Team | SE-2406 |
| Students | Турсуналиев Зайниддин Хайдаралиевич · Усманов |
| Supervisor | Танырбергенова Камила Ислямовна |

BuildAI 3D is an early-stage conceptual design and visualization prototype. It doesn't produce construction-ready or professionally certified designs (see [Disclaimer](#disclaimer)).

### Implementation status (verified 2026-10-20)

| Scope | Status |
|---|---|
| Phase 0–3: foundations, procedural 3D viewer, deterministic layout engine, AI generation (mock, Anthropic, OpenRouter providers) | Implemented on `main` |
| Phase 3.5 K1 knowledge foundation · K2 families/types/assemblies · K2.5 geometric & placement validation | Implemented on `main` |
| Phase 3.5 K3 design systems + expressive design intent (facade color, facade-specific windows, room orientation) | Merged into `main` 2026-10-26 (design systems remain editorial drafts) |
| Design Intelligence V1: spec 1.2.0 (MUST/SHOULD requirement traces, area ranges, separation, priorities), editorial draft layout patterns used as soft heuristics, evaluation of every built candidate, bounded repair, 12-case quality benchmark (`pnpm benchmark`) | On `main`, awaiting review |
| Design Intelligence V1.1: single-storey L-shaped footprints (main bar + bedroom wing), explicit or pattern-suggested, measured and explained in the design report | On `main` (layout@1.5.0), awaiting review |
| Quantities and cost, NL modification, version compare, MEP, reports, IFC export | Planned / not started |

Checks on `main` (2026-10-20): web 135 tests passed; API 582 passed, 2 skipped (live-provider tests); lint and typecheck clean. The Anthropic provider has never been called live, and the OpenRouter provider was live-tested once. Docker Compose and CI haven't been verified (no Docker on the dev machine, no remote).

## Status

**Phase 3 complete: AI building generation** (followed on `main` by Phase 3.5 K1–K2.5, see above). Sign in, describe a house in plain language on the projects page (or in a project's "New design" drawer) and press **Generate 3D building**. The AI turns the description into a validated `BuildingSpecification` (asking for clarification when the request is too vague), the deterministic layout engine plans rooms, corridors, stairs, walls, doors, windows, slabs, roof, balconies, garage and furniture, and the result opens as a new immutable version in the 3D editor — with a summary of what was requested vs. generated, every warning and every assumption. Each generation is kept in the project's history.

The AI runs server-side only. `AI_PROVIDER=mock` (default for development, tests and CI) uses a deterministic offline interpreter; `AI_PROVIDER=anthropic` uses Claude:

```bash
# .env (never commit it)
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
AI_MODEL=claude-opus-5
```

or, through OpenRouter (OpenAI-compatible API, structured outputs):

```bash
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=anthropic/claude-opus-5.5
```

The specification form and reference presets from Phase 2 are still available ("Specification form" tab), and the hand-authored Phase 1 demo house is at http://localhost:3000 (no login).

Next: **Phase 4** — quantities and preliminary cost. See [docs/roadmap.md](docs/roadmap.md).

## Prerequisites

- Node.js ≥ 22 and pnpm 10 (`npm i -g pnpm` or `corepack enable`)
- Python 3.12 and [uv](https://docs.astral.sh/uv/) (`pip install --user uv` also works — scripts fall back to `python -m uv`)
- Docker Desktop (optional for local dev; required for `pnpm docker:up`)

## Quick start

### Option A — Docker Compose (full stack)

```bash
cp .env.example .env        # set JWT_SECRET
docker compose up --build   # db + api (migrates on start) + web
```

Web: http://localhost:3000 · API docs: http://localhost:8000/docs

### Option B — Local processes (no Docker needed)

```bash
pnpm install
pnpm api:install
pnpm db:local               # starts embedded PostgreSQL 16, prints DATABASE_URL
cp .env.example .env        # paste DATABASE_URL, set JWT_SECRET
pnpm migrate
pnpm dev                    # web on :3000 (proxies /api) + api on :8000
```

Stop the embedded database with `pnpm db:local --stop`. You can instead point `DATABASE_URL` at any PostgreSQL 16 (`postgresql+asyncpg://…`).

## Commands

| Command | What it does |
|---|---|
| `pnpm dev` | Web + API with reload |
| `pnpm lint` | ESLint, Ruff (lint + format check), import-linter boundaries |
| `pnpm typecheck` | `tsc --noEmit`, mypy (strict) |
| `pnpm test` | Vitest (web), pytest (API, real PostgreSQL, includes migration checks) |
| `pnpm check` | lint + typecheck + test |
| `pnpm migrate` | `alembic upgrade head` |
| `pnpm schema` | Regenerate `packages/schema` (JSON Schemas, TS types, Zod validators) from the Pydantic BuildingModel, BuildingSpecification and AI generation API contracts |
| `pnpm fixtures` | Regenerate the demo house fixture from its authoring script |
| `pnpm golden` | Regenerate the layout-engine golden files for the 10 reference specs (+ the generated-house fixture) — only for deliberate engine changes |
| `pnpm build:web` | Production Next.js build |
| `pnpm docker:up` / `docker:down` | Compose stack |

API tests use `TEST_DATABASE_URL` if set (CI); otherwise they start an embedded PostgreSQL automatically. They always use the mock AI provider; the live Anthropic test runs only with `RUN_LIVE_AI_TESTS=true` and `ANTHROPIC_API_KEY` set.

## Repository layout

```
apps/web/        Next.js (App Router): editor UI, engine/ (pure-TS geometry), viewer/ (R3F)
apps/api/        FastAPI modular monolith: auth, projects, versions, generation jobs,
                 building model + spec + validation, rules profiles, layout engine,
                 AI (providers, prompts, interpreter, NL generation + history)
packages/schema/ Contracts generated from Pydantic (JSON Schemas, TS types, Zod validators)
data/            Material library, rules profiles, demo fixture, reference specs + golden files
docs/            Architecture and design documents
infra/docker/    Dockerfiles
scripts/         Cross-platform helper scripts
```

## Documentation

| Doc | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System overview, repo/frontend/backend architecture, ADRs, cost/versioning/testing |
| [docs/building-model.md](docs/building-model.md) | Specification & model schemas, invariants, operations, rules profiles |
| [docs/ai-pipeline.md](docs/ai-pipeline.md) | AI providers (mock, Anthropic), prompts, validation + repair, generation API, persistence, limitations |
| [docs/3d-engine.md](docs/3d-engine.md) | Coordinates, units, geometry generation, selection, regeneration, performance |
| [docs/database.md](docs/database.md) | PostgreSQL schema, versioning storage |
| [docs/knowledge.md](docs/knowledge.md) | Architectural knowledge packs, families/types/assemblies (Phase 3.5) |
| [docs/roadmap.md](docs/roadmap.md) | Phases, verification checklists, decisions log |

## Disclaimer

BuildAI 3D produces conceptual designs, schematic MEP layouts and preliminary cost estimates for early-stage exploration only. Rules checks are conceptual, and seed cost catalogs contain demo/estimated rates. **It is not a replacement for licensed architectural, structural, MEP or regulatory review.**
