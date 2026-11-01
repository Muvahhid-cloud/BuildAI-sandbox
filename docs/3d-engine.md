# 3D Engine

Status: **Implemented for Phase 2 (v0.4)**; rendering V1 (§21), furniture and site V2 (§22), architectural design quality V3 (§16.13, §23) · Last updated: 2026-11-01

The "3D engine" is four parts with hard boundaries:

| Part | Location | Input → Output | Status |
|---|---|---|---|
| **Layout engine** | Python `modules/layout` | Spec + RulesProfile + seed → BuildingModel | ☑ Phase 2 (§16) |
| **MEP generator** | Python `modules/mep` | Architectural model → model + MEP elements | Phase 6 |
| **Geometry engine** | TS `apps/web/src/engine` | BuildingModel + EngineConfig → `SceneGraph` (render descriptors) | ☑ Phase 1 |
| **Viewer** | TS `apps/web/src/viewer` (R3F) + `features/editor` | SceneGraph + view state → interactive scene | ☑ Phase 1 |

Positions of everything are decided by the model (the layout engine for generated versions; the hand-authored demo fixture otherwise). Generated models go through the unchanged Phase 1 geometry engine and viewer. The browser only **tessellates** what the model states. There is no hidden render-only representation: every mesh is built from, and points back to, one BuildingModel element.

### Determinism contract

> **Same BuildingModel + same EngineConfig ⇒ identical geometry** (same descriptors, same order, same buffers, same material keys).

- Builders never call `Math.random`/`Date.now` or read mutable globals. Textures, lights and post-processing are applied by the viewer after building and never feed back into geometry.
- Elements are built in **id order**, independent of document order (tested by building a reversed document).
- Walls joins are resolved in id order; polygon orientation is normalized before triangulation.
- `EngineConfig.version` (`engine@2` since V1 visual quality, §21) is part of every geometry cache key; bump it when builder output changes.
- Verified by Vitest: a hash over every descriptor key, material list, matrix and position/normal/uv buffer must be equal across builds (`engine/scene/build-scene.test.ts`).

---

## 1. Coordinate system

| Property | BuildingModel (backend & data) | Three.js world (viewer) |
|---|---|---|
| Handedness | Right-handed | Right-handed |
| Up axis | **+Z** | **+Y** |
| Plan axes | +X = east, +Y = north | +X = east, **−Z** = north |
| Origin | Wall-centerline corner at south-west of the ground floor; Z = 0 at ground-floor finished floor level (FFL) | Same physical point |
| Angles | Radians, counter-clockwise positive seen from above | Radians |

Element `position` is an element-local anchor defined per type ([building-model.md](building-model.md) §3.3). Absolute elevation = `level.elevation + position.z`.

## 2. Architectural units

| Quantity | Unit | Precision (enforced by Pydantic on validation) |
|---|---|---|
| Length | meter | 1 mm |
| Area | m² | 0.01 m² |
| Angle | radian | 1e-6 |

Comparisons use `EPS = 1e-4 m` (Python `primitives.EPS`, TS `engine/model/types.EPS`). The UI formats meters (`12 m`, `0.3 m`), never other units.

## 3. Model ↔ Three.js conversion (the single boundary)

`apps/web/src/engine/math/coords.ts` is the only code that knows both axis conventions:

```ts
export const MODEL_ROOT_ROTATION = [-Math.PI / 2, 0, 0]; // model +Z -> world +Y
export function modelToWorld(p) { return new Vector3(p.x, p.z, -p.y); }
export function worldToModel(v) { return { x: v.x, y: -v.z, z: v.y }; }
```

- `viewer/ModelRoot.tsx` renders **all** building meshes inside `<group rotation={MODEL_ROOT_ROTATION}>`. Descriptor matrices and geometry are in model space.
- World-space things (camera poses, sun, ground, grid, section plane) are computed in model space and converted with `modelToWorld` — camera presets (`engine/scene/camera-presets.ts`), sun direction (`viewer/SceneEnvironment.tsx`), section height (`viewer/SectionPlane.tsx`).
- A unit test asserts `modelToWorld` equals the transform of a group rotated by `MODEL_ROOT_ROTATION`.

## 4. Wall generation (`engine/builders/wall.ts`, `wall-layout.ts`)

Model: axis from `position` along `rotation.z`, `length`, `thickness`, `height`, `alignment`.

```
wall-local frame: u along the axis (0..length), v across (+v = left face = +normal), z up
alignment: center -> v in [-t/2, t/2], left -> [0, t], right -> [-t, 0]
```

1. **Joins** (`computeWallJoins`, pure, per level, id-ordered):
   - *T-junction* (this end lies inside another wall's axis) → trim by half that wall's thickness.
   - *L-corner* (ends meet) → **pinwheel**: the arriving wall ("end") extends by half the other's thickness, the leaving wall ("start") trims by the same amount — corners close with no overlapping volume and no coplanar faces. Both-start/both-end corners: smaller id extends.
   - Collinear continuation → unchanged.
2. **Panel decomposition** (`wallPanels`, no CSG): the face `[u0, u1] × [0, height]` minus hosted openings = full-height panels between openings + a sill panel below and a lintel panel above each opening. Openings are clamped to the wall; overlaps merge.
3. Each panel is a box; faces get materials `±u / ±z → material_id (core)`, `+v → finish_left_id`, `−v → finish_right_id`. The opening reveals therefore show the core (brick, render). A face with a display color (`finish_left_color` / `finish_right_color`, BuildingModel 1.2.0, K3) uses the material key `<finish id>@#rrggbb`: `MaterialCache` creates the library preset of that id with only its color replaced (same roughness/metalness, same material id — appearance, not a new material).
4. All panels of a wall become **one mesh** with one geometry group per material.

Exterior walls are authored counter-clockwise, so their left face is the interior and the right face the facade.

## 5. Opening generation (`engine/builders/openings.ts`)

Doors and windows are in host-wall-local coordinates: `position.x` = offset of the opening's start edge along the axis, `position.z` = sill (0 for doors). Their frame = host wall frame · `T(x, center of thickness, z)` — moving a wall moves its openings.

- The wall leaves the void; the opening fills it. Parts: `body` (frames, leaves, handles, sills) and `glass` (separate mesh: transparent, no shadow casting, rendered after opaque parts).
- **Window**: 60 mm frame profile, `mullions` vertical bars, one glass pane, an exterior sill board on exterior walls.
- **Door**: lining the full wall depth, closed leaf (single/double) with handles on the latch side, or two offset glass panels for sliding doors.
- Builders refuse non-finite or non-positive dimensions (`InvalidElementError`); the schema and API validator reject them earlier.

## 6. Room geometry (`engine/builders/floor.ts` — `buildFloor`)

A room is a **space**. Its floor finish is the boundary (wall centerlines) inset per edge by half the thickness of the wall that `bounds` it along that edge (open-plan edges are not inset), placed 4 mm above the slab. The finish uses `floor_material_id` and is also the room's pick surface. Area/perimeter shown in the UI come from the model, never from meshes.

## 7. Floor slabs (`engine/builders/slab.ts`)

Outline + holes (e.g. the stair void) extruded **downward** from the slab's top face (= FFL) via `MeshBuilder.prism` (earcut triangulation, orientation-normalized).

## 8. Roofs (`engine/builders/roof.ts`)

`z = 0` is the top of the covering at the eaves; `thickness` is vertical.

| Type | Implementation |
|---|---|
| `flat` | Outline prism + parapet boxes along each edge (inside the outline) |
| `gable` | Rectangle; ridge along `ridge_axis` at `(span/2)·tan(pitch)`; two slopes, underside, eave + verge bands; since V3 the gable ends are closed (infill triangle in the supporting wall's finishes, §23.1) |
| `hip` | Rectangle; closed-form skeleton (ridge inset by half the span from each end), four faces, underside, fascia |

The demo uses a 25° hip roof whose underside meets the wall tops at the outer face (computed in the fixture).

## 9. Stairs, railings, furniture

| Element | Implementation |
|---|---|
| `stair` (`stair.ts`) | Side profile (n risers, n−1 treads, sloped soffit parallel to the pitch, waist = riser + 120 mm) extruded across the width |
| `railing` (`railing.ts`) | Posts at ≤ `post_spacing`, top rail following `rise` (sloped for stairs), balusters every 120 mm (`bars`) or a glass panel (`glass`, level only) |
| `furniture` (`furniture/`) | Procedural placeholders per `furniture_kind` (18 kinds) sized from the element's dimensions; shower glass is a separate glass part. Since V2 (§22) the viewer draws a CC0 glTF model for kinds that have one (`assets.ts` → `data/materials/models.json`), fitted to the element's width × depth × height; the placeholder stays the pick proxy and the fallback |

## 10. Object UUID mapping & mesh ↔ model mapping

```ts
interface RenderDescriptor {
  key: string;           // `${elementId}#${part}` — unique and stable
  elementId: string;     // BuildingModel element UUID (1 element -> 1..2 descriptors)
  part: "body" | "glass";
  levelId: string | null;
  layer: Layer;
  geometry: BufferGeometry;  // element-local; shared between identical parts
  geometryKey: string;       // engine version + content hash
  materials: string[];       // material id per geometry group
  matrix: Matrix4;           // element-local -> model space
  castShadow: boolean;
}
```

`SceneGraph` (`engine/scene/build-scene.ts`) holds `descriptors`, `byElement: elementId → descriptors`, model-space `bounds`, `stats`, the `ModelIndex` (`elementsById`, `levelsById`, `hostedOpenings`, `hostOf`, `wallsBounding`, `elementsByLevel`) and the geometry cache.

Rules: meshes carry only `{ elementId, part }` in `userData`; the properties panel reads the element from the index. Clicking a window selects the window (not its wall); clicking a floor finish selects the room. Tests assert every element has ≥ 1 descriptor and every descriptor maps back to an existing element with the same layer/level.

## 11. Object selection flow

```
click on canvas (drag distance ≤ 4 px, so orbiting never selects)
  → R3F raycast; hidden and ghosted meshes have a no-op raycast
  → nearest hit → resolveElementId(object) (walks up userData)       engine/scene/selection.ts
  → useSelectionStore.select(id)                                      single source of selection
  → ElementMesh re-renders only for the old/new selected element: material variant "selected"
    (emissive tint) + a bounding-box outline (elementBounds)          viewer/ModelRoot.tsx
  → PropertiesPanel: describeElement(element, index) → sections      features/editor
    (dimensions with units, material, placement, typed properties, relationships, identity);
    relationship rows are clickable and select their target
click on empty space / Esc / × → select(null)
```

Rooms can also be selected from the room list in the left panel.

## 12. Scene regeneration strategy

- `useBuildingStore.load(json)` = validate (Zod from the generated JSON Schema) → index + integrity checks → `buildScene(index, config, previousScene)`.
- Geometry is cached by **content key** (element fields + everything that influences it: hosted openings, joins, bounding-wall insets, engine version). A rebuild adopts the previous cache, so unchanged elements reuse their `BufferGeometry` (tested: changing one sofa's material rebuilds only the sofa).
- `disposeScene(old, keep=new)` disposes only geometries the new scene no longer uses. Materials live in the shared `MaterialCache` (one instance per id × variant) and are disposed when the editor unmounts.
- React keys are descriptor keys; `ElementMesh` is memoized and receives only `(descriptor, visibility mode, selected)`, so view-state changes re-render only affected meshes. View state (camera, filters, layers, selection of still-existing ids) survives rebuilds.

## 13. Performance

Demo house (measured): 116 elements → 144 meshes, ~7k triangles; validate + index + build ≈ 22 ms in the production build, ≈ 90–120 ms in dev mode. Generated houses (Phase 2, dev mode): 280 m² family house 129 elements → 155 meshes, 13–50 ms; 360 m² three-storey villa 176 elements → 214 meshes, ~35 ms.

| Technique | Status |
|---|---|
| `frameloop="demand"` (renders only on change) + `RenderOnResize` | ☑ |
| One mesh per element part with multi-material groups (not one per face/panel) | ☑ |
| Shared geometry for identical parts (e.g. 6 dining chairs → 1 geometry) | ☑ |
| Shared materials (`MaterialCache`) | ☑ |
| Memoized meshes, granular Zustand selectors | ☑ |
| Explicit disposal of replaced geometry; meshes use `dispose={null}` | ☑ |
| PCF sun shadows (2048², radius 4), disabled while a section cut is active | ☑ |
| Optional post-processing (N8AO half-res, SMAA), contact shadows; shared textures per (file, repeat) | ☑ V1 (§21) |
| InstancedMesh / BatchedMesh, Web Worker builds, LOD, BVH raycasting | Deferred until a model needs it (budget: 3–5k elements) |

---

## 14. Viewer & editor (Phase 1)

```
features/editor/components/
  DemoEditor        loads GET /api/v1/demo/building-model → building store (public, "/")
  ProjectEditor     /projects/[id]: version selector, loads GET …/versions/{vid} → building store;
                    "New design" drawer (features/generation: SpecForm → validate → generate job
                    → progress by real job stage → opens the new version), design report drawer
                    (features/versions/ReportPanel), start view for projects without versions
  BuildingEditor    layout: left panel | viewport | properties; toolbar under the viewport
                    (≥1024 px three columns; narrower screens stack viewport first)
  LeftPanel         project summary · floors (All / Floor 1 / Floor 2) · layers · inspection · rooms
  PropertiesPanel   model-driven properties of the selection
  ViewerToolbar     camera presets, reset, perspective/orthographic, scene stats
viewer/
  BuildingViewer    <Canvas shadows="percentage" frameloop="demand">
  ModelRoot         the model->world group; ElementMesh per descriptor; selection outline
  CameraRig         drei OrbitControls (rotate / zoom / pan), perspective + orthographic cameras,
                    animated presets
  SceneEnvironment  HDRI lighting, soft-shadowed sun, contact shadows, textured ground, sky, grid (§21)
  PostEffects       optional N8AO + SMAA + tone mapping (§21)
  SectionPlane      horizontal clipping plane (renderer clipping planes)
stores/ (Zustand, one concern each)
  project-store · building-store · selection-store · viewer-store (floors, inspection,
  projection, section, camera requests) · layer-store
```

| Feature | Behaviour |
|---|---|
| Rotate / zoom / pan | Left-drag orbit, wheel zoom, right-drag pan (damped) |
| Camera presets | Exterior, Front (street/south), Rear (garden/north), Top, Floor 1, Floor 2, Interior; Reset view = exterior. Presets animate (700 ms) |
| Floor isolation | All / Floor n: levels above hidden, levels below ghosted (12 % opacity, not pickable), roof hidden; choosing a floor frames it |
| Layers | Architecture, Structure (load-bearing facades, slabs, stair), Furniture toggle independently; Plumbing, Electrical, HVAC, Fire safety, Landscaping are defined but *planned* |
| Inspection | Roof, exterior walls (with their doors/windows), furniture, section cut with height slider |
| Interior | Camera at eye height (1.6 m) in the living room with that floor isolated |
| Openings follow hosts | A door/window is hidden whenever its host wall is hidden (layer or facade toggle) |

## 15. Known limitations (Phase 1)

- Shed roofs are not implemented. (Gable-end infill exists since V3, §23.1.)
- Walls are single solids with face finishes; build-up layers (insulation, block, plaster) are not modelled or rendered yet.
- Door leaves are always drawn closed; no swing arcs. Windows have one pane behind the mullions.
- No room labels, ceilings, skirting, stair nosings or stair stringers.
- Selection is single-element; no hover highlight (cursor only), no multi-select or "select parent".
- Section cut is horizontal only, global (also clips grid/ground); no section fill (hatching).
- Walk (first-person) mode and measurement tools are not implemented (Phase 8). The plan (2D) view exists since Phase 3.6 (§19).
- Furniture is procedural placeholder geometry (Phase 1); since V2 most kinds are drawn by CC0 glTF models (§22).
- `ResizeObserver`-driven canvas sizing: in environments that throttle rendering (hidden embedded browser panes) the canvas initialises on the first interaction; normal browser tabs are unaffected.
- `THREE.Clock` deprecation warning comes from React Three Fiber internals.

## 16. Layout engine (spec → model) — ☑ Phase 2

Code: `apps/api/app/modules/layout/` (pure domain module; no I/O, clock or global randomness). Entry point:

```python
generate_layout(spec, rules_profile, *, id_namespace, seed=0, config=DEFAULT_CONFIG,
                previous_ids=None, material_ids=None) -> LayoutResult(model, warnings, notes, metrics)
# raises LayoutError(code="LAYOUT_INFEASIBLE" | "LAYOUT_INVALID", message, issues)
```

Scope v1: rectilinear plans, 1–3 storeys, one rectangular house footprint stacked on every storey, plus an attached single-storey garage (L-shaped ground floor), cantilevered balconies and ground-floor terraces. Every minimum comes from the active `BuildingRulesProfile` ([building-model.md](building-model.md) §10); construction defaults (wall/slab thicknesses, preferred door/window sizes, default room areas, search parameters) live in `LayoutConfig` (`config.py`) and are versioned with `ENGINE_VERSION` (now `layout@1.2.0`; constraint-aware generation §16.7).

### 16.1 Plan scheme

Every storey is a **double-loaded corridor**: a street-side band (south, depth `Ds`), a corridor band (1.2 m) and a garden-side band (north). The **stair core** sits in the street band at the same x on all storeys; on the ground floor it is part of the **entrance hall** (open to the corridor), with the front door in the hall. Every room spans its band from the corridor to the facade, so it is reachable and gets a window — except small service rooms, which are **tucked** against the corridor inside a larger room's column; that room wraps around them on the facade side (L-/T-shaped rooms). En-suites and walk-in closets are tucked into (or placed next to) their bedroom and opened from it.

```
 y=D  +--------+-----------+--------------------+    garden (north): living, dining, kitchen /
      |  ...   |  Living   |  Kitchen & dining  |    master bedroom (+ balcony / terrace door)
      |        +---+       |                    |
 Ds+C +--------+WC +-------+--------------------+
      |               Corridor                  |
 Ds   +-----+--+---------+--------+-------------+    street (south): hall + stair core,
      | Hall|St|  Study  |Laundry | Bedroom ... |    service rooms, other rooms
      |  ⌂  |ai|         |        |             |
 y=0  +-----+rs+---------+--------+-------------+
     x=0                                      x=W      garage annex at x<0 or x>W
```

Stair core: `lanes = storeys − 1`, one straight flight per lane (`design_stair`: risers = ⌈f2f / riser_max⌉, tread from the 2R+T comfort target, all within the rules). Flight 0 rises north and arrives at the corridor; for three storeys flight 1 rises south from the corridor in the second lane and arrives at a landing over the first flight (a switchback without a mid-landing). Upper floors get walled voids over arriving flights and slab holes cut to the inner wall faces. `Ds ≥ half exterior wall + landing_min_depth + run`.

### 16.2 Pipeline

```
1. Program     program.py   spec rooms -> RoomRequests (instances, rule minimums, zones, attached suites);
                            default target areas scaled to fill the requested area (service ±30 %)
2. Levels      planner.py   fixed levels kept; bedrooms up, public rooms down, one bathroom per
                            bedroom floor; greedy balancing of room area vs. level capacity
3. Skeletons   planner.py   footprint W x D per aspect (0.5-1.8) at the requested area, street-band
                            depth options around an even split, core position (5) x hall side (2),
                            compact hall for small floors; plot / max-footprint limits
4. Zoning      planner.py   per level and seeded variant: rooms (with tucked service rooms) assigned
                            to bands by fill ratio + zoning penalties (living to the garden, balcony
                            hosts to their facade, open-plan partners in one band), local search
                            (move / swap / one-for-two / detach a bathroom into an empty strip)
5. Subdivision planner.py   units ordered by adjacency affinity; widths by flex-weighted water filling
                            with rule minimums (width, door frontage, area) on a 5 cm grid
6. Score       planner.py   area error (explicit targets x2, quadratic), room proportions, zoning,
                            unmet adjacency/open plan, footprint aspect, wasted strips, GFA error
7. Regions     regions.py   corridor, hall, stair core (void / staircase / landing), rooms, garage,
                            balconies, terraces; open edges (hall-corridor, open plan, stair arrivals;
                            open-plan pairs across the corridor open onto it)
8. Walls       regions.py   interior walls where two regions meet (maximal runs, vertical runs split at
                            X-crossings); exterior loop per storey; garage walls end at the house face
9. Elements    build.py     doors (front, corridor doors near the core, suites from their bedroom,
                            garage, sliding balcony/garden doors), windows (glazing ratio per style,
                            upper sills >= guard height), slabs (+ stair holes, balcony, terrace),
                            stairs + railings, roofs (flat/gable/hip + flat garage roof), relationships,
                            furniture (furnish.py: per-room templates clear of door zones)
10. Validate   engine.py    model invariants incl. geometric checks (K2.5) + reachability; the best-scoring candidate that validates
                            wins (up to 6 are built)
```

Determinism: the only randomness is `random.Random(f"{seed}:{skeleton}:{variant}")`; all ties break on stable keys (never object identity or hash order — a test runs the engine under two `PYTHONHASHSEED`s). Same spec + seed + profile + config + id namespace ⇒ byte-identical model JSON. Typical runtime: 0.05–1 s for the reference specs.

### 16.3 What the engine reports

- **Deviations** (`LayoutResult.warnings`): explicit room targets off by > 15 %, gross floor area off by > 5 %, unmet `adjacent_to`/`open_to` — never hidden; shown in the version's design report.
- **Notes**: derived floor area, rooms enlarged/reduced to fill the area, empty street-side strips turned into landing space, balconies/terraces moved to another host room.
- **Infeasibility** (`LAYOUT_INFEASIBLE`): the most frequent rejection reasons of all candidates (e.g. "footprint wider than the plot allows", "rooms do not fit the garden-side band at their minimum widths", "3.1 m needs 17 risers …").

### 16.4 Tests

`tests/layout/`: 10 reference specs (`data/fixtures/specs`, incl. the 280 m² 2-storey 4-bed example, a 3-storey villa, bungalows, a narrow plot, no area given) must validate, be fully reachable, have no rules findings, deliver the program (counts, levels, suites, garage/balcony/terrace, GFA ± 3 %) and match their **golden files** (`data/fixtures/golden/*.golden.json`: footprint, rooms + areas, counts, warnings, model sha256; update deliberately with `pnpm golden`). Hypothesis generates random in-scope specs and asserts invariants, reachability, containment and reproducibility. `data/fixtures/generated-house.model.json` is rendered by the web engine tests.

### 16.6 Component types (layout@1.1.0, Phase 3.5 K2)

`generate_layout(..., type_set: TypeSet | None = None)`. The engine never reads the catalog; the generation pipeline passes an approved, rules-checked `TypeSet` (docs/knowledge.md §3.4) or `None`.

- **Design values**: `layout/types.py: config_with_types(config, type_set)` returns the effective `LayoutConfig`: each value a type defines (wall/slab/roof thickness via assemblies, door width/height, garage door width per car, window presets, service/stair windows, stair width, railing heights and post spacing) replaces the default; roles without a type keep `LayoutConfig`. Values the config holds once (door thickness, post spacing, main and garage roof thickness) must agree across types, otherwise `LAYOUT_INVALID`. The geometry code is unchanged.
- **Roles**: every generated wall, slab, roof, stair, railing, door and window has a role (`building/types.py TYPE_ROLES`); doors and windows record theirs where the engine chooses them (e.g. `door.wet_room`, `window.service`, `window.stair`).
- **Attachment**: `build.attach_types` sets `type_ref` and the type's fixed materials, and copies the used types and their assemblies into the model (sorted); rooms and furniture stay untyped. `metadata.generator` names the type pack and mapping.
- **Determinism and geometry**: with the generic types the effective config equals `LayoutConfig` (tested), so every reference spec generates the same geometry fingerprint typed and untyped (`tests/layout/test_types.py`, also under two `PYTHONHASHSEED`s). The web geometry builders are unchanged (`engine@1`); a web test asserts type metadata never changes the scene hash.
- `ENGINE_VERSION` is `layout@1.1.0` (models are BuildingModel 1.1.0). The golden files changed only in `engine_version`, the full-model hash and the new fields; every `geometry_sha256` is identical to the pre-K2 baseline.

### 16.7 Constraint-aware generation (layout@1.2.0, Phase 3.5 K2.5)

The engine prefers generating valid geometry to discovering invalid geometry afterwards. The geometric invariants of [building-model.md](building-model.md) §4.1 act at four points, each deterministic:

```
spec + effective config ─► opening_fit_issues   before the search: the fixed door sizes the building needs fit
                           (layout/constraints)  the storey's walls, else LAYOUT_INFEASIBLE with a suggestion
skeleton ────────────────► flights_fit_lanes     in the seeded search: every flight, centred between the faces of
                           (layout/constraints)  its lane walls, keeps its clearance; impossible skeletons are skipped
                                                 (in the loop, so the seeds of the other skeletons do not shift)
opening placement ───────► WallPlan.place        building/hosting.py: inside the segment, `gap` from other openings,
                                                 clear of wall-junction zones; doors taller than the walls → BuildError
built candidate ─────────► validate_model        every model invariant incl. the geometric checks; errors or
                                                 ROOM_UNREACHABLE reject the candidate; the first valid one wins
```

- **Stair cores on the facade.** A lane is `width + 2·clearance + interior wall` wide — right between interior walls, but a lane on the facade is bounded there by the thicker exterior wall. layout@1.1.0 centred the flight in such a lane regardless, so it cut 5 cm into the exterior wall and ran under the slab edge above (reference specs 05, 06, 09 — and 58 of 130 random specs that generated in a 200-spec probe). `skeletons()` now widens a facade lane by the extra half-thickness (snapped up to the grid) **and grows the footprint by the same amount**, so the rooms keep their widths; the flight is centred between the actual wall faces (`plan.lane_faces`, identical to the lane middle for interior lanes). Gross floor area grows by ≤ 2.1 % in the reference specs (reported like any other deviation when > 5 %). If the plot cannot take the extra width, the skeleton keeps its size and `flights_fit_lanes` rejects it.
- **Openings** are placed with the same interval arithmetic the validator uses (`hosting.free_intervals`, `hosting.junction_zones`), so the engine cannot choose a position the validator would reject. Junction zones are explicit (the door and window margins used to keep openings out of them implicitly — output unchanged).
- **Storey height vs door sizes.** Door heights and thicknesses are fixed (by the component type, or by the engine defaults the generic types mirror), so they are never shrunk. layout@1.1.0 failed with `LAYOUT_INVALID` ("engine bug") for storeys below 2.6 m when a 2.4 m sliding door was needed; now a required door that cannot fit is a user-fixable `LAYOUT_INFEASIBLE` (`TYPE_GEOMETRY_MISMATCH`, path `/targets/floor_to_floor_height_m`, suggestion "raise the floor-to-floor height to at least … m"), and the optional garden door is left out with a note. Fixed-size service and stair windows are skipped where they would pass the wall top.
- **Effect on output.** Only facade-core skeletons changed, so geometry changed only where layout@1.1.0 produced the stair defect: 7 of 10 reference specs keep their `geometry_sha256`; 05, 06 and 09 keep their layout on a 0.1 m (05: 0.2 m, two lanes) wider footprint. ENGINE_VERSION is `layout@1.2.0`.

### 16.8 Design systems and design intent (layout@1.3.0, Phase 3.5 K3)

`generate_layout(..., type_set, design_system: DesignSystemSnapshot | None = None)`. The generation pipeline resolves the spec's design system (approved only; docs/knowledge.md §3.5) into a snapshot plus the type set of its role mapping; the engine never reads the catalog. `building.design.effective_design(spec, system)` gives the `DesignRecord` the model carries (precedence: [building-model.md](building-model.md) §2.3).

```
rooms[].faces ─────────────► zoning wishes          front → street-side (south) band, rear → garden-side
                              (planner, penalty 3.0)  (north) band, before balcony/terrace host wishes;
                                                      unmet → ROOM_FACADE_UNMET warning
design.windows ─────────────► _windows (build.py)    per facade size class (resolve_window_preferences):
                                                      preferred facades are glazed first with the
                                                      emphasis preset (sill/height/mullions/glazing ratio
                                                      of that style or its type), excluded facades get
                                                      standard windows; placed by WallPlan.place (the
                                                      K2.5 interval arithmetic), recorded as size_class
design.facade_color ────────► _walls                 finish_right_color of every exterior wall
                                                      (house + garage); materials unchanged
design system ──────────────► types, finishes,       role-mapping types (attach_types incl. fixed
                              furniture palette      railing kind), dry/wet floor, interior/wet wall
                                                      finishes, furniture material substitution
built candidate ────────────► validate_model         + design_checks: an emphasised window on an
                                                      excluded facade (or an off-system component) is an
                                                      error → the next candidate is tried
```

- **Facade model.** Plan sides S/N/W/E of the rectangular footprint are the front/rear/left/right facades (`building/facades.py PLAN_SIDE`); the model derives the facade of any exterior wall from its outward normal, so nothing directional is stored.
- **When a preferred facade has too little wall.** Every segment of the facade is tried (widths shrink to the free interval, never below the rules' minimum window width). A preferred facade that ends with no emphasised window is reported (`WINDOW_PREFERENCE_UNSATISFIABLE` warning, requested-vs-delivered check "not met") — the emphasis is never moved to an excluded facade.
- **No-intent path unchanged.** Without intent every facade uses `style.window_style` and the old segment order; all ten reference specs keep their pre-K3 geometry fingerprints. ENGINE_VERSION is `layout@1.3.0` (BuildingModel 1.2.0).

### 16.9 Design Intelligence V1 (layout@1.4.0)

`generate_layout(..., patterns: PatternLibrary | None = None)`. The generation pipeline passes the pattern library (docs/knowledge.md §3.6); golden files and tests that pass nothing get no pattern guidance.

```
spec (1.2.0) ──► program: explicit targets carry their permissible range and MUST flag;
                 MUST pairs (adjacent / open / separate)
             ──► select_patterns (layout/patterns.py): triggers read from the spec
                 garden_focus   rooms facing rear | rear window emphasis | terrace | priority
                 narrow_site    footprint limit < 0.9 × side of a square storey | plot w < 0.8 d
                 open_plan      open_kitchen_living | open_to pairs | priority
                 compact        priority | storey area ≤ pattern threshold
                 privacy_zoning separate_from | priority
                 → PatternGuidance (band preference per room type: explicit wishes win, first
                   pattern wins; affinities/separations summed; aspect ranges intersected)
             ──► search (planner.py), scored additionally on
                 area outside the permissible range (8 × relative excess, +4 for a MUST),
                 spec pairs (adjacent 1.5, open 1.5, separate 1.2; MUST 5.0),
                 pattern band preferences, type affinities/separations (× 0.5), aspect range (1.5)
             ──► build + validate the best 6 candidates, evaluate each (building/evaluation.py)
             ──► rank: unmet MUST count, then design score, then plan score, then order
             ──► none meets every MUST? bounded repair: build up to 18 more (score order)
                 until one does; still none → LAYOUT_REQUIREMENTS_UNMET with each unmet MUST
                 (expected vs delivered) — never relaxed
```

`LayoutResult` adds `evaluation`, `patterns` (id, name, source, status, support, reasons) and `candidates` (every valid built candidate: plan score, design score, MUST met, footprint, chosen); `LayoutMetrics` adds `candidates_valid`, `repair_builds`, `design_score`. Notes name each applied pattern with its status. The generation report stores all of it (`versions/schemas.py`).

Determinism is unchanged: patterns are applied in id order, ties break on rounded scores and candidate order, never on object identity (tested under two `PYTHONHASHSEED`s). Patterns only change scores, never the skeleton list, so `sk_index` seeding is untouched.

**Quality benchmark.** `data/fixtures/benchmark/design-benchmark.v1.json` (requests with hard/soft expectations by category, tagged by the set they were added in — 12 in `v1`, 6 in `v1.1` (L), 6 in `v1.2` (L quality) — and reported per set) runs prompt → offline interpreter → spec checks → layout with patterns → checks computed from the model independently of `building/evaluation.py` (`apps/api/evals/design_benchmark.py`, `pnpm benchmark`; regression tests in `tests/evals`). Known gaps are recorded with their reason and must keep failing until fixed.

### 16.10 L-shaped footprints (layout@1.5.0, Design Intelligence V1.1)

A second footprint topology for **single-storey** houses. Code: `layout/plan.py` (Skeleton topology fields), `layout/planner.py` (`l_skeletons`, wing band), `layout/regions.py` (gallery, band rectangles along either axis), `layout/build.py` (`envelope`, wall-based facade segments, slabs, roofs), `layout/topology.py` (selection), `building/evaluation.py measure_footprint`.

**Geometry.** The L is the existing double-loaded *main bar* `[0, W] × [0, D]` plus a *wing* on the garden side at its west or east end:

```
            wing (rooms | gallery)                 y = D + wing_length
          ┌──────────┬────┐
          │  wing    │ g  │   garden (partly enclosed)
          │  rooms   │ a  │
          │ (bedroom │ l  │    ┌── inside corner (Ww, D)
          │  wing)   │ l  │    │
  y = D ──┤          │ e  ├────┴──────────────────────────┐
          │          │ r  │   garden band (day rooms)      │
          │          │ y  ├────────────────────────────────┤ corridor
          │          └────┘                                │
          ├────────────────────────────────────────────────┤
          │ hall │          street band                    │
  y = 0   └────────────────────────────────────────────────┘
          x = 0   Dw   Ww                                  x = W
```

- The wing's room band (`wing_depth`: the garden band's depth, or since layout@1.6.0 the street band's depth for garden-sized splits, §16.11) runs along y from the main corridor to the wing's end, on the wing's **outer** side; the **gallery** (corridor width C) runs on its inner, garden side and continues the main corridor (one L-shaped corridor region). The garden band of the main bar spans only `garden_x` (beside the wing). Rooms in the wing are laid out by the same band machinery as the other bands (`Strip.axis = "y"`, tucks against the gallery).
- **Parameters** (`LayoutConfig`): `l_main_aspects` (main bar W/D), `l_wing_area_shares` (share of the floor area beyond the main bar), `l_band_split_offsets`; limits `l_wing_min_length` (the wing must reach ≥ 3 m beyond the main bar), `l_min_garden_frontage` (≥ 4 m of garden facade beside the wing); scored preference `l_wing_ratio` (wing length / main width 0.4–0.9). The wing goes opposite an attached garage (layout@1.5.0; since 1.6.0 also on the garage's side, §16.11).
- **Envelope** (`build.envelope`): a counter-clockwise loop of 7 exterior walls; the outer side is split where the wing starts so each wall belongs to one volume. Rectangular plans keep their four walls, keys and order (fingerprints of reference specs 01–10 unchanged). Facade segments are computed per exterior wall (each opening has exactly one host); interior walls are derived as before between inside regions.
- **Inside corner.** The main bar's garden wall arrives at the corner and the wing's inner wall leaves it (renderer pinwheel: arriving extends, leaving trims); the partition continuing the wing's inner line inside the house stops at the exterior wall's inner face. The renderer rule (`wall-layout.ts`): exterior walls ignore interior walls at L-corners; interior walls trim there like a T.
- **Slabs and roofs.** Ground slab = union of both volumes. Flat roof: one L-shaped outline. Pitched roof: a main roof and a wing roof (each covering its own walls with the same overhang and eave height; the two overlap without valley geometry — a conceptual model).
- **Terrace** stays within the main bar's garden facade (clear of the wing).

**Selection** (`layout/topology.py`): an explicit `design.footprint_shape` (spec 1.2.0) is a user requirement — `rectangular` → rectangles only; `l_shape` MUST → L only, and if none fits, `LAYOUT_INFEASIBLE` with the reasons and whether a rectangle would fit (never a silent rectangle); `l_shape` SHOULD → both are searched and a valid L that meets every MUST is ranked first, otherwise the rectangle is kept with `LAYOUT_TOPOLOGY_FALLBACK`. Without a request, only the experimental pattern `pattern.l_shaped_garden_wing` (garden focus **and** privacy, one storey, ≥ 110 m²) adds L candidates, which then compete with rectangles on the evaluation only. A garden wish alone never brings an L. L skeletons are enumerated after the rectangular ones, so rectangular seeds never shift. When both topologies are searched, each gets an equal share of the built candidates (L: the best of each distinct footprint first).

**Reporting.** `LayoutResult.topology` / the version report's `topology`: the shape **measured on the validated model** (room corners snapped to the 1 mm grid before the union, so float noise between outlines never counts as corners) (`measure_footprint`: union of ground-floor rooms; 4 corners = rectangular, 6 corners with one inside corner = L), the requested shape and priority, the topologies searched and why, candidates per topology, and why the generated one won (design scores of the best of each). The evaluation checks a requested shape against the measured one.

### 16.11 L layout quality (layout@1.6.0, Design Intelligence V1.2)

The V1.1 L wasted space and missed garden intent: a gallery along the whole wing and a main corridor running to both facades (≈ 24 % circulation), a garden band too shallow and short for the living spaces, kitchen and dining facing each other across the corridor. V1.2 changes the L only; rectangular plans are untouched (fingerprints of reference specs 01–10 unchanged, rectangular seeds unchanged).

- **Wing end room** (`Strip.end_wrap_depth`, `StripLayout.wrap_from`): the last room of the wing takes the gallery's end. The gallery stops a door's reach (`door_reach`: door + 2 × `door_margin`) into that room, whose door sits on that stretch; the room wraps around the gallery's end (an L-shaped room). Its column is sized for the same area. Not for a tucked room, nor where the room would be too narrow (≥ door reach + `remainder_min_depth`).
- **Corridor ends** (`planner.corridor_cuts`, `plan.CorridorCut`): the main corridor's dead ends are given to rooms. *Far end* (opposite the wing): the corridor stops a door's reach into the last garden-side and street-side rooms; the room further below its target area takes the rest, so the two now share a wall. *Near end* (under the wing): the stub beyond the gallery goes to the first street-side room or the wing's first room. Never at the end with the garage door, beside the hall or a tucked room, for an end shorter than `remainder_min_depth`, between rooms the spec keeps apart, or between a bedroom/study and a living space (privacy).
- **Far-end alignment** (`planner.align_far_end`): wished neighbours that landed on opposite sides of the corridor (spec pairs by weight, then the implicit kitchen–dining / dining–living affinity) are moved to the corridor's far end, where the cut joins them — the kitchen can stay on the street side and still meet the dining room on the garden side.
- **Garden-sized splits** (`planner.garden_demands`, `_garden_split`): besides the offset splits, each main bar gets band splits whose garden band holds the rooms that belong on the garden (living spaces and rooms facing the rear or hosting the terrace, plus the dining room with a `garden_connection` priority; then also the dining room): `Dn² + (W − D)·Dn = demand`, `Dn ≤ l_garden_band_max_depth` (6 m), street band ≥ `min_band_depth`; the wing's rooms then take the street band's depth. Appended after all other L skeletons (seeds of the others unchanged).
- **Wing beside a garage**: the wing may also stand on the garage's side (the garage, y ≤ D, and the wing, y ≥ D, never meet); then the far corridor end is free for a join and the near end keeps the garage door.
- **Day rooms out of the bedroom wing**: living, dining and kitchen in the wing cost 1.6 (more than a living room on the street side, 1.5), so the wing's north end is no back door to the garden.
- **Search score (L only)**: `L_CIRCULATION_WEIGHT` (12) × circulation share (`l_circulation_area`: corridor less its cut ends, gallery up to the wrap, hall), since rooms grow when the corridor shrinks and the area terms would otherwise favour a longer corridor.
- **More L footprints evaluated when the user asks for an L** (`l_requested_builds` = 5; rectangular alternatives keep 3). A pattern-suggested L keeps the equal share — it must not win by getting more attempts.

**Evaluation** (`building/evaluation.py`): new criterion `garden_frontage` when the client asked for a garden connection (priority, or a living space facing the rear): the share of the garden facade, measured along the house's exterior walls (garage excluded), that living/dining spaces hold, naming what holds the rest; `garden` names the living spaces that miss the garden. Criteria are the same for both topologies; an L gains nothing for being an L (compactness counts its longer perimeter against it). `ROOM_FACADE_UNMET` is measured on the model's exterior walls (a mid-wing room is not on the garden facade) and names the rooms that hold that facade. `measure_footprint` (and the benchmark) snap room outlines to the 1 mm grid first: outlines are position + offset sums, and float noise (10.299999999999999 vs 10.3) left zero-width slits that made a valid L measure as "other". The evaluation's other measurements are not snapped yet: the same noise can measure walls rooms do share as 0 m (`_Facts.shared`; kitchen–dining in candidates of reference spec 01) and inflate the compactness outline (reference spec 11 reports 1.55× instead of about 1.19×, compactness 0 %). Snapping them changes the chosen candidate of reference specs 01 and 08 (shared edges) and 08 (compactness), so it is left as an open decision rather than changed silently with the L work.

**Measured** (benchmark, offline interpreter, layout@1.5.0 → 1.6.0): circulation of the four V1.1 L requests 22.7–24.2 % → 18.7–20.7 %; their soft expectations 1/4 → 3/4 (left: an explicit 30 m² living room delivered at 27.4 m², inside its ±10 % range, outside ±5 %); reference spec 11: circulation 25.5 % → 21.3 %, living and dining on the garden facade (the living room was on the street side), kitchen, dining and living sharing walls, but its SHOULD room sizes are met less well (area accuracy 0.68 → 0.55). Rectangular plans: unchanged (v1 benchmark set identical). Benchmark set `v1.2` adds six regression requests (all hard expectations hold; soft 8/10).

### 16.12 Footprint shapes and T-shaped footprints (layout@1.7.0, Design Intelligence V1.3)

Trigger: "make me a long L designed house with the yellow walls" produced a yellow **rectangle**. Two causes, both fixed: the model traced the shape as *should* (the prompt allowed *must* only for words like "must/required"), and every L main bar was too shallow for two bands at 115 m² (bars were sized only from fixed width/depth ratios), so the preference fell back silently-but-reported to a rectangle.

**Shape intent** (`building/footprint.py`) keeps four questions apart:

| | where | what |
|---|---|---|
| requested | `design.footprint_shape` (spec 1.2.0, values `rectangular`, `l_shape`, `t_shape`, `u_shape`, `courtyard`) | recorded even when it cannot be built |
| priority | the `/design/footprint_shape` requirement trace | `shape_priority(quote)`: an explicit request is MUST, softened wording ("if possible", "ideally", "… is fine too") SHOULD |
| supported | `CAPABILITIES` | generator id, storey limit, limitation text |
| feasible | the layout engine | `LAYOUT_INFEASIBLE` with reasons / `LAYOUT_TOPOLOGY_FALLBACK` |

One vocabulary (`SHAPE_WORDS`: "L-shaped", "L shape", "L designed", "an L house", "L-plan", "horseshoe", "atrium" …; never an L-shaped sofa or kitchen) serves the offline interpreter; the AI prompt (building-generation@5) lists the enum, the capabilities (generated from `CAPABILITIES`) and the priority rule, and `normalize_shape_requirement` applies `shape_priority` to any model's answer before validation (note `AI_SHAPE_PRIORITY`). A required shape without a generator (or beyond its storey limit) is a spec error `SPEC_FOOTPRINT_UNSUPPORTED` that is **not repairable** (`ai/interpreter.py USER_LIMITS`: a repair could only drop or soften it) — the generation fails with `SPEC_UNSUPPORTED` and the reason; the engine refuses it too (`LAYOUT_SHAPE_UNSUPPORTED`). A preferred unsupported shape gives a rectangle with `LAYOUT_TOPOLOGY_FALLBACK` and `topology.limitation`.

| shape | generator | storeys |
|---|---|---|
| rectangular | `rect` | 1–3 |
| L-shaped | `l` (§16.10/16.11) | 1 |
| T-shaped | `t` (below) | 1 |
| U-shaped, courtyard | none yet — refused with the reason | — |

**Depth bars** (L and T): main bars whose depth comes from the bands (2 × `min_band_depth` + C + `l_depth_steps`) and width from the area (`l_depth_bar_shares`). They are a *fallback family*: `search` tries them for a wing topology only when its ratio bars give no feasible layout, so every established L result is unchanged (reference spec 11 identical). The reported request now gives a 10.2 × 9.0 m L (114.75 m², yellow) — as stored (should: L design score 0.95 vs 0.67 for the best rectangle) and as normalized (must).

**T topology** (`Skeleton.topology = "t"`, `wing_x0`): the main bar plus one wing from the middle of its garden facade (`wing_x0` centred), its rooms on the `wing_side` half, the gallery beside them; garden bands `N` and `N2` on both sides (`Skeleton.garden_ranges`), each ≥ `t_min_side_frontage`; main-bar ratios `t_main_aspects` (longer than an L's: the wing takes the middle). Envelope: 8 walls `S, E, N:E, wing:E, wing:N, wing:W, N:W, W`, two inside corners (same renderer join rule as the L); slabs and roofs as for the L (flat: one 8-cornered outline; pitched: main + wing roof). Corridor dead ends are cut at both main-bar ends; the wing's last room takes the gallery's end. The part of the wing band inside the main bar has no outside wall: a habitable wing room must reach `t_min_wing_facade` beyond the garden facade (`_t_wing_rooms_lit`), and a service unit is put first in the wing (`service_first_in_t_wing`, pulled from another band if the wing has none). `measure_footprint` classifies 8 corners / 2 inside as `t_shape` (inside corners on one line, the stem between them), `u_shape` (adjacent inside corners) or `other`, and one enclosed hole as `courtyard`. Reference spec 12 (`12-t-shaped-bungalow-170.spec.json`, golden + `generated-t-house.model.json`, web 3D-engine test).

Benchmark set `v1.3` (8 requests): rectangular, the reported yellow L (exact words) and its paraphrase, a T villa, U and courtyard (refused; their geometry recorded as known gaps), an L preference, and the 12 m plot that used to be infeasible. The v1 courtyard case now expects an honest refusal; the v1.1 infeasible-plot case uses a 9.3 m plot (12 m now fits an L).

### 16.13 Architectural design quality (layout@1.8.0, V3)

BuildingModel 1.3.0. Details and rationale: §23. In the engine:

- **Roof coverings** per roof type (`LayoutConfig.roof_materials`): flat roofs (incl. garage roofs) `roof_membrane`, pitched `roof`. The roof type itself still comes from `style.roof` (or the design system default) — never random.
- **Facade finishes** (`facade_finishes`, `facade_zoning`, `build.facade_zones`): the wall core keeps `facade_materials[style.facade_material]` (the benchmark checks it); the right-face finish is the facade's look — timber reads as `cladding_timber`, and per architectural style (an approved design system's first style tag first) a **plinth** finish on the ground storey of multi-storey houses and an **accent** finish on the garage volume. No zoning when a facade colour applies (it covers the whole facade) or where a zone equals the main finish. Reported as a design-report note ("Facade zoning (contemporary): …").
- **Entrance canopy** (`entrance_canopy`, `canopy_materials`, `build._canopies`): a `slab_kind: canopy` slab per entrance door, `clearance` above the door head, `depth` out from the outer face, `side` beyond each jamb but stopping 5 cm short of any window whose head it would cut; skipped if it would not fit under the next level or would enter another wall. Untyped (`element_role` → None). Validated by `slab.canopy` (building-model.md §4.1); canopies are not floor slabs for `slab.no_overlap`, `wall.on_slab` or stair checks.
- **Window axes** (`_windows` → `WallPlan.place(center=…)`): on upper storeys a window is centred on the axis of a window below on the same facade line when one fits its room's facade segment (reusing a slightly wider window's width, or narrowing to ≥ 70 % and ≥ the rules' minimum width; the remaining glazing goes to the room's next window). Ground-storey placement is unchanged. Upper exterior windows on an axis below, reference specs 01 and 04–09: 33/84 before, 41/84 after.

Golden files: every reference spec changes (a canopy each; garage/flat roof coverings; zoning; axes) — rooms, areas, counts and warnings unchanged except one window fewer in spec 05 (an aligned, narrower window met the room's glazing without its second window).

### 16.5 Limitations (layout@1.0.0)

- One plan type (double-loaded corridor, street on the south) plus, since layout@1.5.0, a single-storey L (§16.10) and since 1.7.0 a single-storey T (§16.12); no U-shapes or courtyards (refused with the reason), no sloped sites, no basements.
- Straight flights only; the 3-storey core is a conceptual switchback (the pocket under the second flight belongs to the staircase room). Storey height is limited to one flight (≤ 16 risers → ≤ 3.04 m with the generic profile).
- Rooms only span a full band or are tucked against the corridor; small houses (< ~60 m² per storey) lose a large share to hall, core and corridor.
- Windows are sized by glazing ratio per facade segment (K3 adds per-facade size classes, not views/orientation to the sun); no skylights; no guards for low upper-floor sills (sills are raised to the guard height instead). Rooms can face the front or rear only (bands), not left/right.
- Furniture is basic and skipped when it does not fit (e.g. shallow balconies).
- Gable roofs inherit the Phase 1 renderer limitation (no gable-end infill).

## 17. MEP generator (schematic) — Phase 6

Rule-based after layout: plumbing (fixtures from wet-room templates, stack, orthogonal drains at 1–2 %, supplies), electrical (board, outlets ≤ 3.6 m apart, lights, switches at the latch side, circuits), HVAC (split units or ducted trunk + branches). Orthogonal A* routing on a 0.1 m grid, deterministic tie-breaking. Labelled **schematic, not for construction**.

## 18. Infrastructure visualization — Phase 6

- Discipline palette: cold water `#2f80ed`, hot water `#eb5757`, drain `#8d6e63`, vent `#9e9e9e`, power `#f2c94c`, lighting `#f2994a`, supply air `#56ccf2`, return air `#bb6bd9`, refrigerant `#27ae60`.
- Any MEP layer on → architecture switches to x-ray (transparent, `depthWrite=false`, not pickable) — the ghost material variant already provides this.
- "Isolate system" highlights `part_of_system` members; "trace" walks `connected_to` edges to the source.

## 19. Plan drawings — Phase 3.6 D1

Floor plans are a second rendering of the BuildingModel, next to the 3D scene. Like meshes they are
**derived**: never stored, never edited, rebuilt from the model on every change. One pure builder
and one SVG renderer serve the on-screen plan and every download, so screen, SVG, PNG and PDF
cannot disagree.

```
engine/drawing/primitives.ts   DrawItem (poly / circle / text), DrawGroup {elementId, role}, pens
engine/drawing/plan.ts         buildPlanDrawing(index, levelId, {scale, furniture, dimensions})
engine/drawing/symbols.ts      wall frames, doors, windows, stairs, furniture symbols, room outlines
engine/drawing/dimensions.ts   exterior dimension chains
engine/drawing/plan-math.ts    frames, arcs, hatch clipping, label placement
engine/drawing/svg.ts          PlanDrawing -> SVG (presentation attributes only, paper mm)
engine/drawing/sheet.ts        A3 sheet: frame, title, plan, north arrow, scale bar, title block
features/drawing/              PlanView (interactive), DrawingDownloads, export.ts (files)
```

### 19.1 Rules

- Every group maps to at most one model element (`elementId`); only dimension chains have none.
  The interactive view selects that element (same selection store as the 3D view and the
  properties panel).
- Coordinates are model plan coordinates (meters, +Y north = up the sheet); pen widths and text
  sizes are **paper millimeters** at the drawing scale. The renderer maps 1 m to 1000/scale mm.
- Deterministic: elements in id order, fixed grids for the label search, numbers printed at
  0.01 mm. The engine never reads the clock: the sheet date is passed in by the UI.
- Room names and areas come from the model (`dimensions.area`), never measured from the drawing.

### 19.2 What is drawn (per level, paint order)

1. Balcony slabs (outline) and slab voids (dashed).
2. Rooms: invisible pointer target; terraces and balconies hatched; boundary edges without a wall
   dashed (open plan) or solid (outdoor rooms).
3. Furniture symbols (from the element's own width, depth and rotation; follows the Furniture
   layer), stairs (treads and walking line: "up" from the first riser on the lower level, "down" on
   the upper level, seen through the void), railings.
4. Cut walls as solid poché: the 3D wall joins (`computeWallJoins`) and panel rule (`wallPanels`)
   at plan level, so every hosted opening leaves a gap of exactly its width.
5. Openings in the gaps. Windows: wall faces, jambs and a double glazing line. Doors: jambs, the
   leaf at 90° and its swing arc; double doors two leaves; sliding doors two offset panels; garage
   doors the panel and its travel dashed. Every opening is shown as cut, whatever its sill height.
   **Door direction convention:** the model stores the hinge side (`swing` left = hinge at the
   start edge, right = at the end edge, as the 3D handle placement implies) but not the opening
   direction. The drawing opens a door into the room it `connects` to, otherwise to the host
   wall's left face (the interior of counter-clockwise exterior walls).
6. Room labels: name (bold) over area ("14.3 m²", one decimal). The block goes where it fits inside
   the room, clear of furniture, door swings and stairs, horizontal before vertical, shrinking to
   60 % before it falls back to the room's label point.
7. Dimension chains (§19.3).

### 19.3 Dimensions

Per facade side (S, E, N, W), outside the building, in millimeters with 45° ticks: (1) openings
and footprint corners of that side, (2) the footprint corners when the footprint steps (L, T),
(3) the overall dimension. Corners are the positions of the perpendicular outer wall faces (wall
face ends would be off by the corner joins). Text that does not fit between its ticks moves to the
other side of the line.

### 19.4 Sheet

A3 landscape with a 20 mm binding margin (5 mm elsewhere). The plan is built at the first
standard scale at which it fits (`PLAN_SCALES`: 1:100, 1:200, 1:250, 1:500; text is fitted for
that scale) and centered under its title ("FLOOR 1 PLAN 1:100"). Bottom strip: north arrow (+Y),
scale bar, the single-source disclaimer, and a generic title block (not a regional stamp form):
"Conceptual design — not for construction", project, version, drawing, scale, indoor room area of
the level (room areas without terraces and balconies), date, sheet n / N.

### 19.5 Viewer and downloads

The toolbar switches **3D model / Floor plan** (the choice survives loading another version); in
plan mode it shows the floors and the downloads. The plan zooms with the wheel around the pointer,
pans by dragging and selects on click; the selection is highlighted with CSS over the same SVG.
Downloads: **PDF** (vector, one A3 page per level; jsPDF + svg2pdf.js, loaded on demand),
**SVG** (the A3 sheet of the level on screen) and **PNG** (that sheet at 150 dpi). Files are named
`<project>-<drawing>.<ext>`, keeping letters of any script.

### 19.6 Tests

`engine/drawing/plan.test.ts` runs every fixture (demo, generated 2-storey, L, T): deterministic
output, every room labelled with its model area, every element of the level drawn and every group
mapped to an element, wall gaps equal to opening widths, A3 fit at a standard scale, door
direction, footprint dimensions (17400 × 16800 for the L fixture), stairs on both levels, hatch
clipping and label placement. `features/drawing/components/PlanView.test.tsx` covers the view,
the selection highlight, the furniture layer, the download buttons and file names.

### 19.7 Limitations (D1)

- Read-only: editing on the plan (typed operations) is step D3.
- PDF text uses the standard Helvetica font (WinAnsi): Latin text and "m²" print, Cyrillic or
  Kazakh text (e.g. a project name) does not. SVG and PNG are not affected. Fix: embed a Unicode
  font in the PDF.
- No coordination axes or SPDS conventions (axis bubbles, level marks, section marks); the
  `spds@1` drawing profile is not consumed (its knowledge is unapproved).
- No overhead lines (roof eaves, upper-floor projections) and no wall hatching by material.
- In very small rooms (a 1 × 3 m WC) the label can overlap fixtures when nothing fits.

## 20. Plan editing — Phase 3.6 D2

The plan view edits the BuildingModel through typed operations (docs/building-model.md §5.1); the
API applies and validates them, the client renders what the API returns.

```
features/editing/api.ts     POST /projects/{id}/versions/{vid}/edits/preview | /edits
features/editing/store.ts   session: base version, operations, cursor (undo/redo), messages
engine/drawing/wall-edit.ts gesture helpers: movable walls, normal, 5 cm snap, compass labels
features/drawing/components PlanView (drag + live preview), PlanEditBar (undo/redo/save, moves)
```

- **Session.** Opened for the version shown in the project editor (not on the demo page). The
  operation list is kept in the tab; `cursor` operations are applied; undo/redo move the cursor and
  re-request the preview (undo to 0 shows the base model without a request). A new operation after
  an undo drops the redo branch. "Save version" posts the applied operations; the new version
  (source `manual`) opens and a new session starts on it. Unsaved edits are guarded on version
  switch and on leaving the page.
- **Gesture.** Select a wall (D2.5: exterior walls too, see below), then drag it (or use ↑↓/←→, Shift ×5, or the distance
  field and compass buttons). The drag is projected on the wall normal and snapped to 5 cm. Each
  new snapped position is checked by the server (debounced 60 ms, latest wins, stale answers
  dropped); a valid answer replaces the drawing with the returned model (areas, dimensions, joined
  walls, step walls), and an outline shows the dragged position — blue checking, green valid, red
  refused with the reason. Release applies only a valid position (reusing the matching check).
- **One model.** The applied model is loaded into the building store, so the plan, the properties
  panel, the 3D view and every download (§19) show the same edited model. Edits keep the plan's
  zoom and pan. Downloads made with unsaved edits say so in the title block
  (`v3 · … + 2 unsaved changes`).
- **Which version opens.** The editor opens the version chosen in this tab, else the version of
  the AI generation in the `?generation=` link, else the project's latest version. As soon as
  another version than the linked generation's is open (saved edits, the version menu, history, a
  new design) the page drops `?generation=` from the URL (`router.replace`), so a reload opens the
  latest version instead of bringing the generation's older model back (regression test:
  `features/editor/components/ProjectEditor.test.tsx`).
- **Tests.** `wall-edit.test.ts` (directions, snapping, outline), `features/editing/store.test.ts`
  (apply/refuse/undo/redo/redo-branch/check/discard/save against a mocked API),
  `PlanEditBar.test.tsx` (controls, keyboard, refusal display); API: `tests/building/test_operations.py`
  (incl. a Hypothesis property: every move is refused or consistent — area conserved, openings in
  place, other levels untouched) and `tests/test_editing_api.py`.
- **Room resizing (D2.2).** Selecting a room in an editing session shows a handle on every side
  (`engine/drawing/room-edit.ts roomSides`, the same classification as the server): blue = movable
  (interior walls over its whole length), grey = exterior / open / partly a wall, with the reason in
  the edit bar. Clicking a handle chooses the side; dragging it previews `resize_room` (outline of
  the room with the side moved, the moved side drawn thick; the status gives the room's new area
  and extent from the server's model). The edit bar offers Enlarge / Shrink by a distance; arrows
  towards / away from the side's direction nudge it. After a resize the chosen side is found again
  by geometry (`relocateSide`, side numbers change when an outline is simplified); undo, redo and
  discard clear the choice.
- **Doors and windows (D2.3).** `engine/drawing/opening-edit.ts` (pure: wall under a point,
  5 cm snap of the start edge, outline, wall left on each side, slide directions, sizes of a new
  opening copied from the model's first opening of that kind). Openings get an invisible pointer
  target over their span in the interactive plan only (`plan.ts`, added after extents and label
  obstacles, so drawings and downloads are unchanged). Drag a selected door or window along its
  wall, or onto another wall of the level (the dragged wall wins near corners): every snapped
  position is checked (`move_opening`), the status gives the wall and the wall left on each side,
  red with the reason when refused. The edit bar gives its size and wall, a Position field (m from
  the wall start), ← → slides (arrow keys, Shift ×5) and Remove (Delete). "+ Door" / "+ Window"
  open the add panel (kind, width, height, sill); hovering a wall shows the checked outline, a click
  places it (`add_opening`) and selects the new opening; Esc or Cancel stops. Tests:
  `opening-edit.test.ts`, `PlanView.test.tsx` (drag along and onto a wall), `PlanEditBar.test.tsx`,
  `ProjectEditor.test.tsx` (move, add by clicking, remove, undo/redo, refusal, discard, save,
  reload; plan wall gaps, 3D meshes and download sheets checked against the stored model); API:
  `tests/building/test_opening_operations.py` (incl. a Hypothesis property: every opening move is
  refused or consistent) and `tests/test_editing_api.py`.
- **Opening sizes, walls and rooms (D2.4).** While a version is open for editing, the properties
  panel shows an *Edit* section for the selected element (`features/editing/components/
  ElementEditSection.tsx`): a door or window's Width / Height (/ Sill), an interior wall's
  "Remove wall…" and "Remove & merge rooms…" (two steps: the second shows what will happen — rooms
  opened or merged with the merged area, doors removed with the wall — and asks to confirm), a
  room's Name and Room type (only types `set_room_type` supports; staircase / garage / outdoor rooms
  say why not). Every prepared change is checked live (`use-draft-check.ts`: debounced, latest
  wins) and published as the session's `draft`, so the plan draws the model the server returned
  for it (a refused opening size is drawn as a red outline in its wall); the verdict, reasons and
  warnings (e.g. `EDIT_PROGRAM_CHANGED`) are shown beside the fields, and Apply / Confirm reuses
  the checked answer. On the plan a selected door or window has a grip at each end: dragging one
  resizes it along its wall (5 cm snap, the other end stays), checked live like a move
  (`resize_opening` with the new start offset and width). The controls work in the 3D view too;
  undo / redo / discard / save stay in the plan's edit bar. Tests: `ElementEditSection.test.tsx`,
  `PlanView.test.tsx` (grips, draft preview), `store.test.ts`, `edited-model.test.ts` (plan,
  sheets and 3D of an edited model); API: `test_resize_opening.py`,
  `test_wall_removal_and_rooms.py` (Hypothesis properties for resizes and wall removals),
  `test_editing_api.py`.
- **Adding walls (D2.4).** "+ Wall" in the edit bar opens the wall panel (direction north–south /
  east–west, a door in the new wall with its width, the new room's type). Hovering a room draws the
  wall across it through the snapped point (`engine/drawing/wall-add.ts`: room under the pointer,
  5 cm snap, the line across the arm that holds the point), checked live (`add_wall`) green or red
  with the reason; a click places it and selects the new room, so it can be renamed and typed in
  the properties panel. Esc or Cancel stops. Tests: `wall-add.test.ts`, `PlanView.test.tsx`,
  `PlanEditBar.test.tsx`; API: `test_wall_addition.py` (Hypothesis: every new wall is refused or
  consistent).
- **Envelope editing (D2.5).** Exterior walls are dragged like interior ones (`isMovableWall`:
  every wall but partitions; `isFacade`): the server moves the whole facade on every storey with
  the floor slabs, the roof eaves/verge/parapet line, balconies, terraces and the canopy
  (docs/building-model.md §5.6), so the live preview is the server's model — the new footprint and
  room areas on the plan — and, while a facade is selected or a room's facade side is chosen, the
  roof's eaves outline is drawn dashed over the plan from the same preview model
  (`wall-edit.ts roofOutlines`; edit overlay only, not part of drawings or downloads). Refusals
  (a garage front in line, a wing joined to the facade, the stair opening cut, a roof that cannot
  follow, a room under the profile minimum) are shown red with the server's reason. A room's facade
  side is resizable (`RoomSide.resizable`); a balcony or terrace at the facade it hangs on, and a
  side along several walls including a facade, stay grey with the reason. The properties panel
  shows, for any wall, **Thickness** (an exterior wall: the whole facade; limits from the rules
  profile's `walls` section), **Finish** (face: facade / inside / both for exterior walls, left /
  right / both otherwise; materials from the library's wall-finish categories) and, for walls that
  carry nothing, **Height**; each is checked live and published as the draft, with Apply. The 3D
  view and every download render the applied model like any other edit. Tests:
  `wall-edit.test.ts`, `room-edit.test.ts`, `PlanView.test.tsx` (facade drag, roof outline),
  `PlanEditBar.test.tsx`, `ElementEditSection.test.tsx`; API: `test_envelope_editing.py`,
  `test_editing_api.py`. Not yet: facades a garage or wing continues or joins (L/T inner corners),
  balconied facades' thickness, curved or diagonal walls, moving several facades at once.
- **Limits (D2.1).** Only `move_wall` on interior walls (D2.5: and facades); no snapping to other walls; the preview is
  a server round trip per 5 cm step (fine locally; port the applier to TS if it needs to be faster,
  architecture.md §5.2); drafts are not persisted server-side.

## 21. Rendering & visual quality — V1 step 1 (2026-10-31)

Scope: how the viewer *looks*. Nothing here changes the BuildingModel, the layout engine, golden
files, the API or the 2D plan drawings (they use `engine/drawing`, not the 3D materials). The
determinism contract is unchanged: builders still take only (element, ctx); textures and lights
are applied by the viewer and `MaterialCache` after geometry is built.

### 21.1 Pipeline

```
Canvas (frameloop="demand", PCF shadows, ACES Filmic tone mapping, exposure RENDER.exposure)
 ├─ SceneEnvironment   local HDRI (drei <Environment files>, image-based light + reflections only;
 │                     error boundary → hemisphere light if the file cannot load)
 │                     sun: directional light, 2048² PCF shadow map, shadow radius 4 (soft edges),
 │                     switched off while a section cut is active
 │                     contact shadows under the building (drei ContactShadows, off when sectioned)
 │                     site ground: grass disc, library material `site_grass`, UVs in meters
 │                     sky: neutral vertex-colour gradient dome (not tone mapped) + distance fog
 │                     reference grid (viewer-store `showGrid`, toolbar "Grid", default off)
 ├─ ModelRoot          building meshes (unchanged), materials from MaterialCache
 ├─ PostEffects        viewer-store `effects` (toolbar "Effects", default on):
 │                     EffectComposer → N8AO (half resolution, medium quality) → SMAA → ACES
 │                     Filmic ToneMapping effect (the composer disables renderer tone mapping
 │                     while mounted). Off = plain renderer with MSAA and the same tone mapping.
 └─ MaterialTextures   invalidates the on-demand canvas when a texture finishes loading
```

All look-development numbers (HDRI file, intensities, exposure, sky colours, AO and contact-shadow
parameters) live in one file, `viewer/render-settings.ts`.

### 21.2 Materials and textures

- `data/materials/library.json` stays the only material source. A preset may carry
  `textures: { albedo, normal, roughness, tile_size_m: [u, v], tint? }` (paths relative to
  `data/materials`), `shading: "glass"` and `env_intensity`. `tile_size_m` is the asset's
  published real-world size; the measured repeat (≈ 70 mm brick courses, 300 mm floor tiles,
  136 mm slate courses, 212 mm boards) is recorded in ASSETS.md. Every asset is recorded in
  `data/materials/ASSETS.md` (CC0 only: ambientCG, Poly Haven); a test keeps the library and
  ASSETS.md in sync and checks that every slot marked present ships its files.
- `MaterialCache` gets an injected `TextureSource` (the engine does no I/O; `viewer/textures.ts`
  installs the browser loader, tests use fakes). One texture per (file, repeat) is shared by all
  materials and variants; `repeat = 1 / tile_size_m`; albedo is sRGB, normal/roughness linear;
  anisotropy 8. Ghost (isolated-floor) variants are never textured.
- **Fallback:** the flat library `color` is used until a map has loaded and stays if it never
  does (missing file, empty slot). With an albedo map the colour becomes `textures.tint`
  (default white); a K3 display colour (`id@#rrggbb`) multiplies the map instead.
- `scripts/sync-materials.mjs` (run by the web `dev` and `build` scripts) copies
  `data/materials/{textures,hdri}` to `apps/web/public/materials/` (git-ignored) and writes
  `manifest.json`; the browser requests only files listed there, so empty slots cost no request.
- **Glass** (`shading: "glass"`): `MeshPhysicalMaterial`, transparent (opacity 0.3), roughness
  0.05, IOR 1.5, clear coat, environment reflections ×1.6, library tint. No transmission pass
  (keeps the cost of a transparent standard material).

### 21.3 UVs (meters)

`MeshBuilder` writes planar UVs in meters (1 UV unit = 1 m) in the element's local frame, so a
texture's `tile_size_m` is its real size on every element. Horizontal faces (|n.z| > 0.9999) use
the plan axes; every other face gets **u level along the face and v up the face** — brick courses
run level on walls, and roof tile rows run parallel to the eave on every roof slope (before
engine@2, slopes shallower than ~25.8°, i.e. |n.z| > 0.9, used the plan axes). The site ground uses the same convention
(`engine/scene/site.ts`). Tests: `mesh-builder.test.ts` (UV distances equal edge lengths under
rotation; slope axes), `site.test.ts`.

### 21.4 Window detail (engine@2)

Windows add a glazing bead (25 mm, shallower than the frame) around every pane and reveal
linings (12 mm) on jambs, head and sill between the frame and each wall face, in the host wall's
face finishes (left face → interior lining, right face → exterior lining, display colours
included). Reveals therefore read as plaster / render instead of the raw wall core. All parts stay
in the window's `body` descriptor, so selection and the mesh ↔ element mapping are unchanged.
`EngineConfig.version` is `engine@2` (UVs of sloped faces and window geometry changed).

### 21.5 Performance

Effects on: one extra depth/normal pass for N8AO at half resolution, SMAA, contact shadows
(one depth render from below + blur per frame) — only on demand frames (camera moves,
changes). Shadows stay PCF 2048². "Effects" turns post-processing off on slow devices.

### 21.6 Limitations (V1 step 1)

- Assets (2026-11-01): nine 1K CC0 texture sets and the 1K Poly Haven "Potsdamer Platz" `.hdr`,
  all from Poly Haven (≈ 17 MB, `data/materials/ASSETS.md`). ambientCG's download CDN is not
  reachable from the build environment, so none of its sets is used. Painted interior plaster has
  relief maps only (flat paint colour); grass and concrete use tints to correct the assets'
  colour cast.
- UVs start at each element's local origin: textures are continuous along a wall but not across
  wall corners or between elements.
- No transmission/refraction in glass, no screen-space reflections, no bloom; interior views get
  sky light through the openings only via the HDRI (no light probes).
- `three` removed `PCFSoftShadowMap`; soft shadow edges come from the PCF shadow radius.

## 22. Furniture models and site — V2 (2026-11-01)

Scope: the viewer only. The BuildingModel schema, layout output, golden files, API and the 2D
plan drawings and downloads are unchanged. `EngineConfig.version` is `engine@3` (window frames
moved, below).

### 22.1 Window reveals (V1 review fix)

Windows in exterior walls are set 50 mm behind the outer face (`openings.ts windowFrameV`), not on
the wall centre line: the interior reveal (jambs, head, sill) is deep and lined with the host's
interior finish, the exterior reveal shallow and lined with the facade finish. Before, half of
every reveal was the exterior (brick) reveal, seen through the glass from inside. Interior-wall
windows stay centred. Test: `builders.test.ts` (every exterior-wall window of the demo and the
generated house: four lining boxes per side, right finish, interior reveal the deep one).

### 22.2 Ceilings (V1 review question)

The Interior preset isolates its floor (§14), which hides the slab above: the sky there is
intended, not a bug. With all floors shown, the slab underside is drawn in the slab's material;
rooms carry `ceiling_assembly_ref`, but nothing assigns ceilings yet (building-model.md §3), so no
ceiling finish is invented. A soft hemisphere "bounce" light (`RENDER.bounce`) keeps soffits and
eaves from going black.

### 22.3 Furniture models

```
data/materials/models.json   id, file (models/<id>.glb), use (furniture|tree|bush), kinds,
                             yaw_deg (front -> glTF +Z), bounds (glTF scene box, Y-up)
engine/materials/models.ts   schema; furnitureModel(kind, asset_id); fitToDimensions(); fitToHeight()
engine/builders/furniture/assets.ts  furnitureSource(): registered asset > manifest model > procedural
viewer/ModelRoot.tsx         FurnitureModel: invisible placeholder proxy + ModelInstance(fit matrix)
viewer/ModelInstance.tsx     GLTFLoader + three's MeshoptDecoder (local, no CDN), Suspense/error
                             boundary -> placeholder fallback
```

- **The BuildingModel is the source of truth:** `fitToDimensions` maps the model's bounds exactly
  onto the element's `width × depth × height` (non-uniform scale) in the furniture frame (origin =
  base centre, width x, depth y, front −y, Z-up). glTF Y-up → Z-up is a rotation (never mirrored).
- The procedural placeholder is still built for every piece: it is the invisible pick proxy
  (selection, outline, bounds) and the fallback while a model loads, if its file is not served or
  fails, and for ghosted (isolated-floor) furniture. Kinds without a model (bed, wardrobe, TV unit,
  kitchen units, fridge, sanitary ware — `ASSETS.md` TODO) keep the placeholder.
- Models are requested only when `public/materials/manifest.json` lists them (`viewer/served-assets.ts`).
- **Materials (recorded exception, CLAUDE.md):** furniture and vegetation models carry their own
  embedded CC0 PBR materials. Building elements still take materials only from `library.json`
  via `MaterialCache`; the furniture element's `material_id` stays model data (placeholder,
  properties panel).
- Model meshes are not pickable and carry no `elementId`; the proxy carries `{ elementId, part }`.
  Foliage that is alpha-blended in the source is switched to alpha-test (sorting, shadows).

### 22.4 Site

`engine/scene/site.ts planSite(index, bounds)` (pure, model space, deterministic) →
`SitePlan { streetY, strips, plants, fence }`, drawn by `viewer/SiteLayer.tsx` under the same
coords.ts root rotation as the building ("Site" toolbar toggle, default on). Never part of the
BuildingModel, never pickable.

| Item | Rule |
|---|---|
| Street | `streetY = bounds.min.y − 7 m` (south) |
| Path | from the centre of the `entrance` door on the facade face to the street; straight for a street-side door, out 1.5 m then south for a side door, around the nearer end for a garden-side door; width max(1.2 m, door + 0.4 m); library `site_paving` (UVs in meters) |
| Driveway | the same route from each `garage` door, width door + 1.6 m |
| Trees | four fixed slots off the building corners (> 3.5 m from every facade), skipped when within 2.4 m of a strip; height 4.2–5.6 m and rotation from `hashFraction(slot)` (FNV-1a, no randomness) |
| Shrubs | a row 1 m in front of the street facade every 2.4 m, skipped near strips |
| Fence | 0.9 m timber (`wood`) on the street edge, open where a strip reaches it |

Tests (`site.test.ts`, demo + generated rectangular/L/T houses): identical plan and mesh across
builds and reversed element order; path starts at the entrance door and ends at the street; one
driveway per garage door; plants outside the building and clear of strips, trees clear of the
facades; fence gaps; paving UVs in meters. `models.test.ts`: every GLB self-contained (no
external URIs), meshopt-compressed, recorded in ASSETS.md, < 40 MB in total; exact fit to element
dimensions; axis conversion.

### 22.5 Performance

Furniture models are 0.2–22k triangles each (one shared geometry per file, clones per instance);
trees are simplified to ~40k triangles (from ~2M) and shrubs to ~11k; all textures 512 px WebP;
3.1 MB of models in total. Models load lazily after the building is shown (placeholders first).
"Site" and the Furniture layer can be switched off.

### 22.6 Limitations (V2)

- No suitable CC0 model on Poly Haven for beds, wardrobes, TV units (with screen), kitchen units,
  fridges or sanitary ware; those stay boxes. Non-uniform fitting stretches a model when the
  element's proportions differ a lot from the model's.
- Site placement is generic (street assumed south, no plot boundary from the spec, no terrain).
- Trees are heavily simplified (thinner crowns than the originals).
- No ceilings until the model assigns ceiling assemblies.

## 23. Architectural design quality — V3 (2026-11-01)

Generated houses get roofs, facades and entrances that read as designed rather than as boxes.
Model and layout parts: §16.13 and building-model.md (schema 1.3.0). Renderer parts (engine@4):

### 23.1 Roofs

- **Gable-end infill** (`roof.ts gableEnds`): the triangle between the gable wall's top and the
  roof underside, at the wall's outer face (the verge overhangs it by `overhang`), as thick as
  the wall, in the finishes of the roof's supporting walls (`roofEnclosure`: exterior walls with
  a `supports` relationship to the roof, lowest id). The model's walls stop at the eaves line;
  like wall joins, the infill is derived, not stored.
- **Parapets** of flat roofs carry the facade finish of the supporting walls and a `roof_trim`
  coping (overhanging both faces 3 cm); flat-roof edges and soffits are `roof_trim`.
- **Fascia, verge and soffit** of pitched roofs: `roof_trim` (anthracite metal); the covering
  keeps the roof's material (`roof`, flat roofs `roof_membrane`, §16.13).
- In the plan (§19) roofs are not drawn (above the cut plane); the entrance canopy is (below).

### 23.2 Facades and entrance

- Facade zoning and window axes are model data (§16.13): every wall face shows its
  `finish_right_id`, window reveals line with it (§22.1), gable infill and parapets continue it.
- The entrance canopy is an ordinary slab to the renderer (prism from its top face down) and is
  drawn **dashed** on its level's plan as an overhead element (`plan.ts`).

### 23.3 Design systems

Design systems (K3) are editorial drafts, and generation only uses approved ones, so today the
architectural style of the spec drives zoning and canopy material. When a system is approved
and selected, its first style tag takes over (tested with an approved copy of the catalog).
Design-system records do not carry zoning yet (next step: a `facade.zones` field in a new pack
version, docs/knowledge.md §3.5).

### 23.4 Tests

`layout/test_architecture_quality.py` (zoning by style and by design system, colour disables
zoning, timber cladding on a timber core, roof coverings, one valid canopy per reference house,
a misplaced canopy is reported), `building/test_migrations.py` (1.2.0 → 1.3.0), web
`builders/roof.test.ts` (gable infill, parapet coping, determinism) and
`scene/canopy.test.ts` (canopy above the door head, dashed on the plan).

### 23.5 Limitations (V3)

- Window axes align only where an upper room's facade segment contains an axis of the storey
  below; a full facade grid needs the planner to coordinate room widths across storeys.
- One canopy shape (flat, rectangular); no recessed porch (it would change the room plan).
- Zoning is per architectural style in `LayoutConfig`; design systems do not define it yet.
- Gable infill takes one wall's finishes for both gable ends.
