# AI Pipeline

Status: **Implemented for Phase 3 (v0.3)** · Code: `apps/api/app/modules/ai/`

## 1. Role of AI

AI is used for **language → structure**, never for geometry. The AI produces a `BuildingSpecification` (intent: program, targets, style, features); the deterministic layout engine makes every spatial decision and the procedural 3D engine renders the resulting `BuildingModel`. The model never outputs coordinates, wall geometry, element ids, meshes, images, code or costs.

```
prompt ──▶ AIProvider (mock | anthropic | openrouter) ──▶ SpecificationDraft (structured output)
       ──▶ Pydantic (tier 1) ──▶ rules spec checks + form fields (tier 2)
       ──▶ [errors → one repair call → validate again] ──▶ BuildingSpecification
       ──▶ layout engine (tier 3, deterministic) ──▶ BuildingModel ──▶ model validation
       ──▶ rules findings ──▶ new immutable project version ──▶ 3D editor
```

| Task | Input | Output (validated) | Status |
|---|---|---|---|
| **Interpret** | NL prompt + form fields + project context | `SpecificationDraft` → `BuildingSpecification` | ☑ Phase 3 |
| **Plan modification** | NL instruction + `ProjectContext` | `ModificationPlan` (typed operations) | Phase 5 (context + read-only tools prepared) |
| **Analyze** | model summary + quantities + cost | `DesignAnalysis` | Phase 7 |

## 2. Provider abstraction

```python
# app/modules/ai/providers/base.py
class AIProvider(ABC):
    name: str; model: str
    async def complete_structured(self, request: StructuredRequest) -> StructuredResult  # the one primitive
    # built on top, from the versioned prompt modules (identical for every provider):
    async def generate_building_specification(prompt, *, options, context, max_tokens)
    async def repair_building_specification(prompt, *, options, context, repair, max_tokens)
```

`StructuredRequest` carries the system prompt, messages, the JSON Schema of the expected object and the prompt version; `StructuredResult` returns the parsed object (or `None`), the raw output, model, tokens, latency and stop reason. Providers raise only `AIProviderError` subclasses (`AI_UNAVAILABLE`, `AI_TIMEOUT`, `AI_NOT_CONFIGURED`), never vendor exceptions, and never validate or trust their own output.

| Provider | File | Purpose |
|---|---|---|
| `MockAIProvider` | `providers/mock.py` + `mock_interpreter.py` | **Development, tests, CI, offline.** Deterministic rule/regex interpreter: area, storeys, bedroom/bathroom counts, family size, garage cars, balcony (and its floor), terrace, study/WC/laundry/storage, open kitchen, style/interior style, windows, roof, facade, budget (KZT/USD/EUR, "300,000,000 KZT", "$250k"), city → region code, unsupported items (pool, sauna, basement…), prompt-injection phrases. Records every default as an assumption; asks for clarification when nothing describes the house or the request is out of scope (> 3 storeys, area outside 20–2000 m²). Refused when `ENVIRONMENT=production`. |
| `AnthropicProvider` | `providers/anthropic.py` | **First real provider.** One Messages API call via the official `anthropic` SDK (the only file importing it — enforced by import-linter). The answer is constrained with **structured outputs** (`output_config.format = json_schema`), which works on every current Claude model (forced `tool_choice` is rejected by newer models). Numeric/length constraints unsupported by structured outputs are moved into field descriptions and enforced by Pydantic afterwards. The static system prompt carries a cache breakpoint. SDK errors map to `AI_TIMEOUT` / `AI_UNAVAILABLE`; `refusal`/`max_tokens` stops yield "no object" (→ repair). **Schema-size fallback** (same shared mechanism as OpenRouter, `providers/json_schema.py`): a `BadRequestError` whose message says the compiled grammar/schema is too large switches the provider — for this and every later call — to `prompt_schema` mode (schema in the system prompt via `prompt_schema_system`, no `output_config.format`; `effort` kept). Any other error never triggers it. |
| `OpenRouterProvider` | `providers/openrouter.py` | **OpenAI-compatible gateway** (OpenRouter, e.g. `anthropic/claude-opus-5.5`). One `POST /chat/completions` over plain `httpx` (no vendor SDK). Structured outputs via `response_format = {type: json_schema, strict: true}` with the same transformed `SpecificationDraft` schema (`providers/json_schema.py`, shared with the Anthropic adapter); `provider.require_parameters = true` so OpenRouter never routes to an endpoint that would drop the schema. The system prompt carries a `cache_control` breakpoint (honoured by Anthropic upstreams). **Schema-size fallback:** Claude's structured outputs compile the schema into a grammar, and the full `SpecificationDraft` schema (≈50 optional properties, 23 unions) is rejected with "compiled grammar is too large" (400, before generation, not billed — observed live 2026-09-29 on every Claude upstream). On that specific rejection the provider switches — for this and every later call — to `prompt_schema` mode: the full JSON Schema is appended to the system prompt (`prompts.shared.schema_in_prompt_block`, versioned `schema-in-prompt@1`; the generation/repair prompts are unchanged) and no grammar is requested. Validation is identical in both modes; `metadata.output_mode` reports which was used. The answer is parsed with `json.loads` only — prose, fenced JSON, refusals (`message.refusal`, `content_filter`) and `length` cut-offs yield "no object" (→ one repair, then `AI_INVALID_OUTPUT`). HTTP errors map to `AI_UNAVAILABLE` (400/401/402/403/404/429/5xx, errors inside a 200 body or a choice, unexpected body) or `AI_TIMEOUT` (client timeout, 408); 408/429/5xx/connection errors are retried `AI_MAX_RETRIES` times (Retry-After honoured, ≤ 10 s), timeouts are not. Error details are redacted (key never included) and truncated. Usage (`prompt_tokens`, `completion_tokens`, `cost` in USD credits, cached/reasoning tokens, upstream provider, generation id) is returned; the returned `model` is recorded on `ai_runs`. |

Selection: `get_ai_provider()` (`providers/__init__.py`) from settings; `use_ai_provider()` overrides it in tests.

| Setting | Default | Notes |
|---|---|---|
| `AI_PROVIDER` | `mock` | `mock` \| `anthropic` \| `openrouter`; `mock` refused in production |
| `AI_MODEL` | — | Required for `anthropic` (e.g. `claude-opus-5`); never hard-coded in business logic |
| `ANTHROPIC_API_KEY` | — | Required for `anthropic`; `SecretStr`, backend only, never logged |
| `ANTHROPIC_BASE_URL` | SDK default | Optional gateway |
| `OPENROUTER_API_KEY` | — | Required for `openrouter`; `SecretStr`, backend only, never logged |
| `OPENROUTER_MODEL` | — | Required for `openrouter` (e.g. `anthropic/claude-opus-5.5`); never hard-coded in business logic |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Optional override |
| `AI_EFFORT` | model default | `output_config.effort` (anthropic) / `reasoning.effort` (openrouter; `max` → `xhigh`) |
| `AI_TIMEOUT_SECONDS` / `AI_MAX_RETRIES` | 120 / 1 | Request timeout and transient retries |
| `AI_MAX_REPAIRS` | 1 | Repair calls after invalid output (0–2) |
| `AI_MAX_OUTPUT_TOKENS` | 16000 | Non-streaming request |
| `AI_MAX_PROMPT_CHARS` | 4000 | Also capped by the request schema |
| `AI_GENERATIONS_PER_HOUR` | 30 | Per user (429 `AI_RATE_LIMITED`) |
| `AI_LOG_PROMPTS` | false | Otherwise only prompt length + sha256 prefix are logged |

The API refuses to start with `AI_PROVIDER=anthropic` or `openrouter` and no key/model.

## 3. Prompts (`ai/prompts/`, version `building-generation@4`)

`@4` (V1.1) adds `design.footprint_shape` (`rectangular` | `l_shape`, single-storey only; a courtyard is not an L) and `/design/footprint_shape` as a traceable requirement. The offline interpreter reads "L-shaped"/"L-plan"/"rectangular house", takes the priority from the sentence that states it (so "…; the L shape is required" is a MUST) and assumes one storey for an L when none is given.

`@3` (Design Intelligence V1) adds to the vocabulary: per-room area ranges (`min_area_m2`/`max_area_m2`), `separate_from`, `design.priorities`, plot dimensions, and `requirements[]` traces (path, must/should, origin, the user's words). A stated room size is a room target, never the house's floor area; must only for mandatory wording or an exact room size. The offline interpreter reads the same intent with regular expressions (room sizes in several phrasings, "X next to Y" bound to the nearest room noun, bedrooms separated from living spaces, priorities, "8 m wide" plots, open-plan living–dining–kitchen as one sequence) and reports courtyards as unsupported.

`@2` (Phase 3.5 K3) adds design intent to the vocabulary — facades (from `FacadeSide` and the synonym table `building/facades.py FACADE_SYNONYMS`), the facade color palette (`building/appearance.py`), `design.windows`, `rooms[].faces`, `style.design_system` — and rules for it: explicit visual/directional wishes are requirements ("yellow walls" → `design.facade_color = "yellow"`; "panoramic windows facing the backyard, not on the front" → `design.windows = {emphasis: panoramic, preferred_facades: [rear], excluded_facades: [front]}` with `style.window_style` standard; "living room facing the garden" → `faces: rear`), only what the vocabulary cannot express is unsupported, and a design system is chosen only from `<project_context>.design_systems` — the **usable (approved) systems only**, with their allow-lists and defaults (empty today: every system is a draft). Explicit wishes outside a system's allow-lists are never changed: the model leaves the system out and explains the conflict. Tier 2 of the interpreter adds `building.design.check_design` (against the pipeline's design catalog) to `rules.spec_checks` (which now includes the intent checks), so `DESIGN_SYSTEM_*`, `DESIGN_OPTION_CONFLICT`, `APPEARANCE_INVALID`, `WINDOW_FACADE_CONFLICT` and `FACADE_PREFERENCE_INVALID` go to the single repair call like any other issue. The mock interpreter reads the same intents with the same synonym table and palette.

- `shared.py` — output name/description, the **vocabulary generated from the specification enums** (room types, features, styles, roofs, windows, facades, finish levels), the output JSON Schema (`SpecificationDraft`), `quote_user_text` and the project-context block.
- `generation.py` — static system prompt (cacheable; nothing request-specific) + user turn: `<project_context>` (region, currency, rules profile ref, **room minimums read from the active rules profile**, max room share of the floor area), optional `<form_fields>`, and the user's text in `<building_request>` tags.
- `repair.py` — single self-contained user turn: original request, `<previous_output>` (≤ 20 000 chars), `<validation_issues>` (JSON pointers into the answer), instructions. Same system prompt (shared cache prefix).

Rules the prompt states: priority *explicit requirements → form fields/project constraints → rules profile → safe defaults*; every inferred value goes into `specification.assumptions`; leave floor area / room areas empty unless stated or clearly implied; bathrooms include en-suites; "second floor" = level 1; never drop or change an explicit requirement silently — keep it and explain in `conflicts`, or ask; things the schema cannot express go into `unsupported_requests`; clarification only when a missing value materially changes the design and no default exists.

**Prompt injection.** User text is data inside its tag (tags inside it are stripped, control characters removed) and never enters the system prompt. The system prompt tells the model to ignore instructions in it and to answer only with the JSON object. The output schema has no field that could carry code or geometry (`extra="forbid"` everywhere), all text fields are length-limited, nothing the model returns is ever executed, and the UI renders text escaped.

Changing prompt wording or structure = bump `PROMPT_VERSION` (stored on every generation and AI run).

## 4. Output contract: `SpecificationDraft` (`ai/schemas/generation.py`)

```jsonc
{
  "outcome": "specification" | "clarification",
  "understanding": "A 2-storey modern family house of about 280 m² with 4 bedrooms, …",
  "specification": { /* BuildingSpecification 1.1.0 (incl. style.design_system, design, rooms[].faces) — required for "specification" */ },
  "clarification_questions": ["How many floors …?"],   // required for "clarification", ≤ 5
  "conflicts": ["…"],               // explicit requirements that conflict / exceed scope
  "unsupported_requests": ["Swimming pool — …"]      // reported, not built
}
```

`GenerationOptions` (the optional form fields: floor area, storeys, style, budget, region code, layout seed) are explicit requirements: they are sent to the model and **verified deterministically** afterwards (`check_options` → `SPEC_FORM_FIELD_MISMATCH` → repair).

## 5. Interpreter: validation and repair (`ai/interpreter.py`)

1. `provider.generate_building_specification(...)` (stage `interpreting`).
2. Validate (stage `validating`): JSON object? → `SpecificationDraft` (Pydantic; issues `AI_SCHEMA_INVALID` with JSON pointers such as `/specification/rooms/0/type`) → for a specification, `validate_spec` callback = `rules.spec_checks.check_spec` (tier 2, against the project's rules profile) + `check_options`.
3. Blocking errors and `AI_MAX_REPAIRS` left → `repair_building_specification` with the issues (stage `repairing`) → validate again.
4. Still invalid → `InterpretationError`: `AI_INVALID_OUTPUT` (no usable object) or `SPEC_INVALID` (schema/rules errors). **Invalid output is never accepted.**
5. Accepted → `Interpretation` with warnings: `AI_REQUIREMENT_CONFLICT`, `AI_UNSUPPORTED_REQUEST`, and `AI_REPAIR_CHANGED` for every key requirement (storeys, area, bedrooms, bathrooms, WCs, garage cars, balconies, terrace) a repair changed — so a "fix" that drops bedrooms is visible.

Every provider call becomes an `AttemptRecord` (task, provider, model, prompt version, status ok/invalid/error, raw + parsed output, issues, tokens, latency), persisted as an `ai_runs` row — also on failure. Normal success = **1 call**; invalid output = **1 + 1 repair**.

## 6. Generation use case (`ai/orchestrator.py`, `ai/service.py`, `ai/router.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/ai/generate-building` | `{project_id?, prompt, options}` → 202 generation record. Auth required; ownership checked (404); prompt 3–4000 chars; 409 if a generation/job is running for the project; 429 over the hourly limit; 503 if the provider is not configured. Without `project_id` a new project is created and named after the interpreted spec. |
| GET | `/api/v1/ai/generations/{id}` | Poll: real stage, status, spec, assumptions, warnings, summary, requested-vs-delivered checks, version id/number, error |
| GET | `/api/v1/projects/{id}/generations` | History (newest first, summaries only) |

`BuildingGenerationService` (background task on the in-process job runner, ADR-010) records its **real stage** on the `ai_generations` row: `queued → interpreting → validating [→ repairing → validating] → layout → checking → saving → done`. After interpretation it calls `generation.pipeline.layout_and_save` — the same step the Phase 2 spec form uses: layout engine in a worker thread (deterministic: spec + seed + rules profile + engine version ⇒ same model), final `validate_model` (errors → `MODEL_INVALID`), rules findings, new version (`source = "ai_generation"`, `prompt`, spec snapshot, seed, rules profile, engine version, report with `generation` provenance: generation id, type, provider, model, prompt version). The service contains no layout logic.

Statuses: `completed` · `needs_clarification` (no version) · `failed` with a distinct code and a user-safe message:

| Code | Where | Message (examples) |
|---|---|---|
| `AI_UNAVAILABLE`, `AI_TIMEOUT`, `AI_NOT_CONFIGURED` | provider | "AI generation is temporarily unavailable…" |
| `AI_INVALID_OUTPUT` | no usable JSON after repair | "The AI answer could not be turned into a valid building specification." |
| `SPEC_INVALID` | schema/rules errors after repair (details = issues) | "The requested building specification could not be validated." |
| `LAYOUT_INFEASIBLE` | layout (details = the engine's reasons) | "The requested requirements could not produce a valid layout." |
| `LAYOUT_INVALID`, `MODEL_INVALID` | layout / final model validation | "The layout engine could not produce a valid building for this request." |
| `DATABASE_ERROR`, `INTERNAL_ERROR`, `JOB_INTERRUPTED` | persistence / crash / restart | no stack traces are returned |

Deviations are never hidden: the completed record lists all warnings (AI conflicts/unsupported/repair changes, spec warnings, layout deviations, rules findings) and `checks` (floors, floor area within the engine's 5 % threshold, bedrooms, bathrooms, WCs, balconies, garage, terrace: requested → delivered).

## 7. Context and tools (preparation for Phase 5)

- `ai/context.py` — `GenerationContext` (used now) and `ProjectContext` (summary, current spec, rooms with short refs `R1…`, selected element digest, version, budget, region/currency/rules). Pure functions; never the full model.
- `ai/tools.py` — read-only, typed, ownership-scoped tools (`get_project`, `get_building_summary`, `get_room`, `get_selected_object`, `get_element`) with Pydantic inputs (`extra="forbid"`) and structured outputs; `load_scope` verifies ownership. Not given to a model in Phase 3. `get_cost_summary` arrives with costing.

## 8. Observability & persistence

- `ai_generations` (history) and `ai_runs` (one row per provider call) — see [database.md](database.md). No secrets are stored.
- One log line per provider call (`ai_run`: task, provider, model, status, code, latency, tokens, provider-reported `cost_usd` when available — logged only, not stored; no billing).
- One structured log line per generation: id, project, provider, model, status, error code, stage, duration, repairs, tokens, warning count, version, prompt length + hash (full prompt only with `AI_LOG_PROMPTS=true`). Provider errors are logged with technical detail server-side; keys, passwords and JWTs are never logged.

## 9. Testing

- All automated tests use `MockAIProvider` or a scripted test double; CI never calls a paid API (`tests/conftest.py` forces `AI_PROVIDER=mock`).
- Unit: prompt construction and injection quoting, mock interpretation (demo prompt, defaults, clarification, conflicts, unsupported, budget/region, form fields), interpreter (valid, non-JSON, unsupported room type, invalid dimensions, missing fields, extra geometry fields, rules errors, repair changes, provider errors, form-field mismatch), Anthropic adapter against a fake SDK client (request shape, parsing, refusal/truncation, error mapping, schema transformation, schema-size fallback: switch, persistence, strict parsing, non-matching errors, interpreter/repair path, no key in logs), provider selection and settings guards, context/tools, requirement checks.
- Integration (real API + PostgreSQL): NL → mock → spec → layout → model → version for the demo prompt and ten other prompts; history; clarification; injection; infeasible requirements; AI outage; repair; permanent invalid output; auth; ownership; validation; rate limit; concurrency; interrupted generations; determinism (same prompt + seed ⇒ same `model_hash`).
- OpenRouter adapter against `httpx.MockTransport` (`tests/ai/test_openrouter_provider.py`): request shape, parsing, usage/cost, refusal/truncation/prose, every HTTP status class, timeout, network error, retries, unexpected bodies, errors in 200 bodies, key redaction, end-to-end through `interpret`.
- Live: `tests/ai/test_live_anthropic.py` / `test_live_openrouter.py` run only with `RUN_LIVE_AI_TESTS=true` and the provider's key (and `OPENROUTER_MODEL`).
- Web: generated validators against captured API responses, prompt form, progress, clarification, failure, summary.

## 10. Known limitations

- The Anthropic provider has been exercised only against a fake SDK client and the opt-in live test; the live test has not been run in this repository yet (no project credentials configured). It now has the same schema-size fallback as OpenRouter (unit-tested with the rejection message Claude returned through OpenRouter); the direct API's exact message has not been observed live.
- In `prompt_schema` mode the output is not grammar-constrained: the model can return invalid JSON or a schema violation, which the interpreter repairs once and otherwise rejects (never accepted).
- The mock interpreter understands common English phrasings only; it is a development tool, not a language model.
- No prompt eval suite yet (the roadmap's ~50-prompt eval is deferred); the mock prompts are covered by parametrized tests.
- Generation runs in-process (ADR-010): a restart fails running generations (`JOB_INTERRUPTED`).
- Rate limiting is per user per hour in the database; there is no token budget/spend tracking (no prices in code).
- Refining an existing design in natural language (modification operations) is Phase 5.
