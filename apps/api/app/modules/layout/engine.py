"""Layout engine entry point: BuildingSpecification + rules profile + seed -> BuildingModel.

Pure and deterministic (CLAUDE.md rule 5): same spec, profile, seed, config and id namespace
give a byte-identical model. No I/O, no clock, no global randomness — the only randomness is a
`random.Random` seeded from `seed` inside the candidate search.

Pipeline (docs/3d-engine.md §16): program -> opening fit (K2.5) -> levels -> skeletons
(footprint, bands, core) -> geometric skeleton constraints -> per-level zoning and subdivision
(seeded variants) -> scoring -> build the best candidates -> validate (model invariants incl.
geometric checks and reachability) -> evaluate every valid one against the spec (MUST
requirements first, then the soft design score; building/evaluation.py) -> bounded repair:
build further candidates when none meets every MUST requirement -> best candidate wins, or
LAYOUT_REQUIREMENTS_UNMET (a MUST requirement is never relaxed).

Layout patterns (Design Intelligence V1, layout/patterns.py) that apply to the spec steer the
search as soft preferences and are reported with their review status.
"""

import math
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace

from app.modules.building.design import (
    DesignSystemSnapshot,
    effective_design,
    resolve_facade_preferences,
)
from app.modules.building.elements import Room
from app.modules.building.enums import RoomType, Zone
from app.modules.building.evaluation import DesignEvaluation, evaluate_design
from app.modules.building.footprint import MEASURED_LABELS, capability
from app.modules.building.issues import Issue, pointer
from app.modules.building.model import BuildingModel
from app.modules.building.patterns import PatternLibrary
from app.modules.building.specification import BuildingSpecification, FacadeSide, FootprintShape
from app.modules.building.summary import summarize
from app.modules.building.types import TypeSet
from app.modules.building.validation import errors, validate_model
from app.modules.layout.build import BuildError, build_model, facade_zones
from app.modules.layout.config import DEFAULT_CONFIG, LayoutConfig
from app.modules.layout.constraints import opening_fit_issues
from app.modules.layout.patterns import AppliedPattern, select_patterns
from app.modules.layout.plan import Candidate, StairDesign, snap
from app.modules.layout.planner import (
    WING_SKELETONS,
    PlanningError,
    SearchInput,
    assign_levels,
    design_stair,
    rebay,
    search,
    unmet_pairs,
)
from app.modules.layout.program import Program, expand_program
from app.modules.layout.regions import build_regions
from app.modules.layout.topology import (
    MEASURED,
    SHAPE_NAMES,
    TopologyChoice,
    choose_topologies,
)
from app.modules.layout.types import TypeSetError, config_with_types
from app.modules.rules.profile import BuildingRulesProfile

GFA_WARNING_THRESHOLD = 0.05
# Plan bands of the double-loaded layout that reach a facade (street = south, garden = north).
BAND_OF_FACADE = {FacadeSide.FRONT: "south", FacadeSide.REAR: "north"}


class LayoutError(Exception):
    """Generation failed. `code` is LAYOUT_INFEASIBLE (the spec cannot be laid out: tier-3
    feasibility, user-fixable) or LAYOUT_INVALID (an engine bug: no candidate validated)."""

    def __init__(self, code: str, message: str, issues: list[Issue]) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.issues = issues


@dataclass(frozen=True)
class LayoutMetrics:
    engine_version: str
    seed: int
    candidates_evaluated: int
    candidates_built: int
    score: float
    footprint_width_m: float
    footprint_depth_m: float
    gross_floor_area_m2: float
    target_gross_floor_area_m2: float
    candidates_valid: int = 0  # built candidates that passed model validation
    repair_builds: int = 0  # extra candidates built because none met every MUST requirement
    design_score: float | None = None  # soft evaluation score of the chosen candidate


@dataclass(frozen=True)
class CandidateSummary:
    """A valid candidate that was built and evaluated (shown so the choice is explainable)."""

    order: int
    plan_score: float
    design_score: float
    must_met: bool
    footprint_m: tuple[float, float]
    chosen: bool


@dataclass(frozen=True)
class TopologyReport:
    """Which footprint topology was generated and why (V1.1). `generated` is measured on the
    validated model (building/evaluation.py measure_footprint), never taken from the plan."""

    generated: str  # measured: "rectangular" | "l_shape" | "t_shape" | ... | "other"
    requested: str | None
    mandatory: bool
    searched: tuple[str, ...]  # "rect" / "l" / "t"
    reason: str  # why these topologies were searched
    explanation: str  # why the generated one was chosen
    candidates: dict[str, int]  # feasible candidates per searched topology
    built_valid: dict[str, int]  # validated, evaluated candidates per topology
    # Why the requested shape cannot be generated at all (no generator / storey limit), V1.3.
    limitation: str | None = None


@dataclass(frozen=True)
class LayoutResult:
    model: BuildingModel
    warnings: list[Issue]
    notes: list[str] = field(default_factory=list)
    metrics: LayoutMetrics | None = None
    evaluation: DesignEvaluation | None = None
    patterns: tuple[AppliedPattern, ...] = ()
    candidates: tuple[CandidateSummary, ...] = ()
    topology: TopologyReport | None = None


def _circulation(
    gfa: float, storeys: int, stair: StairDesign | None, config: LayoutConfig
) -> float:
    """Estimated circulation area (corridors, stair core, entrance hall) for a house of `gfa`."""
    width = math.sqrt(gfa / storeys * 1.1)
    area = storeys * config.corridor_width * width + config.entrance_hall_width * 5.0
    if stair is not None:
        area += storeys * (storeys - 1) * stair.lane_width * 5.0
    return area


def _scale_default_areas(program: Program, capacity: float) -> float:
    """Scale rooms without an explicit target so the program fills the requested area.

    Service rooms (bathrooms, storage, ...) change size only a little; living spaces and
    bedrooms take the rest. Returns the factor applied to the living spaces.
    """
    explicit = sum(r.target_area for r in program.rooms if r.explicit_target)
    defaulted = [r for r in program.rooms if not r.explicit_target]
    total = sum(r.target_area for r in defaulted)
    if total <= 0:
        return 1.0
    overall = (capacity - explicit) / total
    service = [r for r in defaulted if r.tuckable]
    living = [r for r in defaulted if not r.tuckable]
    service_factor = min(1.3, max(0.75, overall))
    rest = capacity - explicit - service_factor * sum(r.target_area for r in service)
    living_total = sum(r.target_area for r in living)
    factor = min(2.0, max(0.75, rest / living_total)) if living_total > 0 else service_factor
    for r in service:
        r.target_area = max(r.min_area, r.target_area * service_factor)
    for r in living:
        r.target_area = max(r.min_area, r.target_area * factor)
    factors = ([factor] if living else []) + ([service_factor] if service else [])
    return max(factors, key=lambda f: abs(f - 1)) if factors else 1.0


def generate_layout(
    spec: BuildingSpecification,
    profile: BuildingRulesProfile,
    *,
    id_namespace: uuid.UUID,
    seed: int = 0,
    config: LayoutConfig = DEFAULT_CONFIG,
    previous_ids: Mapping[str, uuid.UUID] | None = None,
    material_ids: Iterable[str] | None = None,
    type_set: TypeSet | None = None,
    design_system: DesignSystemSnapshot | None = None,
    patterns: PatternLibrary | None = None,
) -> LayoutResult:
    """`design_system` (K3) is an approved snapshot resolved by the generation pipeline; its
    type set is passed as `type_set`. Precedence and effective values: building/design.py.
    `patterns` is the layout-pattern library (soft heuristics; None = no pattern guidance)."""
    notes: list[str] = []
    design = effective_design(spec, design_system)
    try:
        # Types replace the matching design defaults; geometry code reads the config as before.
        config = config_with_types(config, type_set)
    except TypeSetError as exc:
        raise LayoutError("LAYOUT_INVALID", f"The type set cannot be used: {exc}", []) from exc
    program = expand_program(spec, profile, config)
    # Fixed door sizes that cannot fit the storey's walls make every candidate invalid: say so
    # up front, as a user-fixable infeasibility (K2.5, layout/constraints.py).
    misfits = opening_fit_issues(spec, program, profile, config, type_set)
    if misfits:
        raise LayoutError(
            "LAYOUT_INFEASIBLE", "The doors of this building do not fit its walls", misfits
        )
    storeys = spec.targets.storeys
    try:
        stair = (
            design_stair(spec.targets.floor_to_floor_height_m, profile, config)
            if storeys > 1
            else None
        )
    except PlanningError as exc:
        raise _infeasible(exc) from exc

    gfa = spec.targets.gross_floor_area_m2
    if gfa is None:
        rooms_area = sum(r.target_area for r in program.rooms)
        gfa = snap(
            rooms_area
            + _circulation(rooms_area / (1 - config.circulation_share), storeys, stair, config),
            5.0,
        )
        notes.append(
            f"No floor area was given; {gfa:.0f} m² was derived from the room program "
            "(rooms plus entrance hall, corridors and stairs)"
        )
    floor_area = gfa / storeys

    # Estimated room capacity of the whole house (footprint minus corridor, core, hall).
    factor = _scale_default_areas(program, gfa - _circulation(gfa, storeys, stair, config))
    if factor > 1.25:
        notes.append(
            f"Rooms without a requested size were enlarged by up to {factor - 1:.0%} to use the "
            "requested floor area"
        )
    elif factor < 0.9:
        notes.append(
            f"Rooms without a requested size were reduced by about {1 - factor:.0%} to fit the "
            "requested floor area"
        )

    site = spec.site
    max_w = spec.targets.max_footprint_width_m
    max_d = spec.targets.max_footprint_depth_m
    if site is not None and site.plot_width_m is not None:
        buildable = site.plot_width_m - 2 * site.setback_side_m
        max_w = buildable if max_w is None else min(max_w, buildable)
    if site is not None and site.plot_depth_m is not None:
        buildable = site.plot_depth_m - site.setback_front_m - site.setback_rear_m
        max_d = buildable if max_d is None else min(max_d, buildable)
    garage = spec.features.garage
    garage_w = (
        garage.cars * config.garage_width_per_car + config.garage_extra_width if garage else 0.0
    )

    # Rooms the user wants on a facade (rooms[].faces, K3) must reach it: front = the street
    # side band (south), rear = the garden side band (north). Explicit wishes come first.
    wishes: dict[str, str] = {}
    for room_key, facing in resolve_facade_preferences(spec).items():
        band = BAND_OF_FACADE.get(facing)
        if band is not None:
            for inst in program.instances(room_key):
                wishes.setdefault(inst.key, band)
    # Rooms that host a balcony or terrace must reach that facade.
    hosts: list[tuple[str | None, str]] = [
        (b.attached_to, "north" if b.side == "garden" else "south") for b in spec.features.balconies
    ]
    if spec.features.terrace is not None:
        hosts.append((spec.features.terrace.attached_to, "north"))
    for key, side in hosts:
        instances = program.instances(key) if key else []
        if instances:
            wishes.setdefault(instances[0].key, side)

    guidance = select_patterns(patterns, spec, floor_area, max_w, max_d)
    for applied in guidance.applied:
        notes.append(
            f"Layout pattern \u201c{applied.name}\u201d ({applied.status}, experimental heuristic) "
            f"applied because of: {'; '.join(applied.reasons)}"
        )
    notes.extend(guidance.notes)
    choice = choose_topologies(spec, guidance)
    if choice.mandatory and choice.unsupported is not None:
        # A required shape the engine has no generator for: say so, never build another one.
        raise LayoutError(
            "LAYOUT_SHAPE_UNSUPPORTED",
            f"The required footprint shape cannot be generated: {choice.unsupported}",
            [
                Issue(
                    severity="error",
                    code="LAYOUT_SHAPE_UNSUPPORTED",
                    path="/design/footprint_shape",
                    message=choice.reason,
                    suggestion="Ask for one of: "
                    + ", ".join(SHAPE_NAMES.values())
                    + ", or make the shape a preference.",
                )
            ],
        )

    try:
        levels = assign_levels(program, storeys, floor_area, stair, config)
    except PlanningError as exc:
        raise _infeasible(exc) from exc
    inp = SearchInput(
        spec=spec,
        program=program,
        levels=levels,
        stair=stair,
        floor_area_per_storey=floor_area,
        max_width=max_w,
        max_depth=max_d,
        garage_width=garage_w,
        garage_depth=config.garage_min_depth,
        landing_depth=profile.stairs.landing_min_depth_m,
        wishes=wishes,
        guidance=guidance,
        topologies=choice.topologies,
    )
    try:
        candidates = search(inp, config, seed)
    except PlanningError as exc:
        raise _topology_infeasible(exc, choice, inp, config, seed) from exc
    by_topology = {t: sum(c.skeleton.topology == t for c in candidates) for t in choice.topologies}

    failures: list[str] = []
    materials = list(material_ids) if material_ids is not None else None
    valid: list[_Built] = []

    def build(cand: Candidate) -> None:
        try:
            plan = build_regions(cand, program, spec, stair, config)
            model = build_model(
                plan,
                spec,
                profile,
                config,
                seed=seed,
                id_namespace=id_namespace,
                previous_ids=previous_ids,
                type_set=type_set,
                design=design,
            )
        except BuildError as exc:
            failures.append(str(exc))
            return
        issues = validate_model(model, material_ids=materials)
        blocking = errors(issues) + [i for i in issues if i.code == "ROOM_UNREACHABLE"]
        if blocking:
            failures.append("; ".join(f"{i.code}: {i.message}" for i in blocking[:3]))
            return
        valid.append(_Built(cand, plan.notes, model, issues, evaluate_design(spec, model)))

    # Build and evaluate the best candidates (an equal share of each searched topology, so a
    # topology is never dropped on plan score alone); if none meets every MUST requirement, a
    # bounded repair pass builds further candidates (in score order) until one does.
    first = _first_builds(
        candidates,
        choice.topologies,
        config.candidates_to_build,
        l_share=config.l_requested_builds if _wants_wing(choice) else None,
    )
    for cand in first:
        build(cand)
    repair_builds = 0
    chosen_orders = {c.order for c in first}
    rest = [c for c in candidates if c.order not in chosen_orders]
    if valid and not any(b.evaluation.hard_ok for b in valid):
        for cand in rest[: config.repair_candidates_to_build]:
            repair_builds += 1
            before = len(valid)
            build(cand)
            if len(valid) > before and valid[-1].evaluation.hard_ok:
                break
    built = len(first) + repair_builds
    if not valid:
        raise LayoutError(
            "LAYOUT_INVALID",
            "The layout engine could not produce a valid model for this specification",
            [
                Issue(severity="error", code="LAYOUT_INVALID", path="", message=f)
                for f in failures[:5]
            ],
        )
    preferred = choice.target if _wants_wing(choice) else None
    best = min(valid, key=lambda b: _rank(b, preferred))
    if not best.evaluation.hard_ok:
        raise LayoutError(
            "LAYOUT_REQUIREMENTS_UNMET",
            "No layout meets every mandatory requirement; none of them was relaxed",
            [
                Issue(
                    severity="error",
                    code="LAYOUT_REQUIREMENTS_UNMET",
                    path=check.path,
                    message=f"{check.label}: expected {check.expected}, best layout gives "
                    f"{check.delivered}",
                    suggestion="Make it a preference, or change the other requirements that "
                    "compete for the same space.",
                )
                for check in best.evaluation.unmet_must
            ],
        )
    if config.facade_bays:
        best = _on_bays(best, inp, config, build, valid, program, spec, gfa)
    cand, model = best.candidate, best.model
    topology = _topology_report(choice, best, valid, by_topology, inp, config)
    notes.append(f"Footprint: {topology.generated.replace('_', '-')} — {topology.explanation}")
    system = design.design_system if design is not None else None
    color = design.facade_color if design is not None else None
    zones = facade_zones(
        spec, system, config, spec.targets.storeys, color.hex if color is not None else None
    )
    has_garage = any(
        isinstance(el, Room) and el.properties.room_type == RoomType.GARAGE for el in model.elements
    )
    zoning_note = zones.describe(has_garage)
    if zoning_note:
        notes.append(zoning_note)
    warnings = _deviations(cand, program, spec, gfa, best.evaluation)
    if choice.requested is not None and topology.generated != choice.requested:
        wanted = capability(FootprintShape(choice.requested)).an_label
        warnings.append(
            Issue(
                severity="warning",
                code="LAYOUT_TOPOLOGY_FALLBACK",
                path="/design/footprint_shape",
                message=f"{wanted} footprint was requested; a "
                f"{MEASURED_LABELS.get(topology.generated, topology.generated)} one was "
                f"generated: {topology.explanation}",
            )
        )
    warnings += _orientation(model, program, spec)
    warnings += [i for i in best.issues if i.severity == "warning"]
    return LayoutResult(
        model=model,
        warnings=warnings,
        notes=notes + best.plan_notes,
        metrics=LayoutMetrics(
            engine_version=config.engine_version,
            seed=seed,
            candidates_evaluated=len(candidates),
            candidates_built=built,
            score=round(cand.score, 6),
            footprint_width_m=cand.skeleton.W,
            footprint_depth_m=cand.skeleton.D,
            gross_floor_area_m2=round(cand.skeleton.footprint_area * storeys, 2),
            target_gross_floor_area_m2=round(gfa, 2),
            candidates_valid=len(valid),
            repair_builds=repair_builds,
            design_score=best.evaluation.score,
        ),
        evaluation=best.evaluation,
        patterns=guidance.applied,
        topology=topology,
        candidates=tuple(
            CandidateSummary(
                order=b.candidate.order,
                plan_score=round(b.candidate.score, 6),
                design_score=b.evaluation.score,
                must_met=b.evaluation.hard_ok,
                footprint_m=(b.candidate.skeleton.W, b.candidate.skeleton.D),
                chosen=b is best,
            )
            for b in sorted(valid, key=lambda b: _rank(b, preferred))
        ),
    )


@dataclass(frozen=True)
class _Built:
    candidate: Candidate
    plan_notes: list[str]
    model: BuildingModel
    issues: list[Issue]
    evaluation: DesignEvaluation


def _on_bays(
    best: _Built,
    inp: SearchInput,
    config: LayoutConfig,
    build: Callable[[Candidate], None],
    valid: list[_Built],
    program: Program,
    spec: BuildingSpecification,
    gfa: float,
) -> _Built:
    """V5: the chosen design with its rooms on whole facade bays where they fit, kept only if
    it is valid, meets every MUST the original meets, scores at least as well on the design
    evaluation and adds no deviation from the requested areas; otherwise the original."""
    snapped = rebay(best.candidate, inp, config)
    if snapped is None:
        return best
    before = len(valid)
    build(snapped)
    if len(valid) == before:
        return best
    alt = valid.pop()
    if (
        len(alt.evaluation.unmet_must) <= len(best.evaluation.unmet_must)
        and round(alt.evaluation.score, 4) >= round(best.evaluation.score, 4)
        and len(_deviations(alt.candidate, program, spec, gfa, alt.evaluation))
        <= len(_deviations(best.candidate, program, spec, gfa, best.evaluation))
    ):
        # The variant takes the original's place among the built candidates (reports).
        valid[next(i for i, b in enumerate(valid) if b is best)] = alt
        return alt
    return best


def _rank(b: _Built, preferred: str | None = None) -> tuple[int, int, float, float, int]:
    """MUST requirements first, then the requested footprint topology (an explicit request,
    even as a preference, wins whenever a valid candidate of that topology meets every MUST),
    then the design score, then the plan score (deterministic: rounded scores and the
    candidate order break ties, never object identity)."""
    return (
        len(b.evaluation.unmet_must),
        int(preferred is not None and b.candidate.skeleton.topology != preferred),
        -round(b.evaluation.score, 4),
        round(b.candidate.score, 9),
        b.candidate.order,
    )


def _wants_wing(choice: TopologyChoice) -> bool:
    """The user asked for a generated non-rectangular topology (L or T)."""
    return (
        choice.requested is not None
        and choice.unsupported is None
        and choice.target not in (None, "rect")
    )


def _first_builds(
    candidates: list[Candidate],
    topologies: tuple[str, ...],
    n: int,
    *,
    l_share: int | None = None,
) -> list[Candidate]:
    """The candidates to build and evaluate first (deterministic, in score order).

    Rectangular: the best `n` (unchanged since layout@1.4.0). L: the best candidate of each
    distinct L footprint (main bar, band split, wing length and depth) first, so the evaluation
    compares genuinely different L shapes rather than near-copies of one. With both topologies, each
    gets an equal share; a topology with too few candidates leaves its share to the other.
    `l_share` (an L the user asked for, V1.2): the L's share, so the requested shape is laid out
    from more distinct L footprints; the rectangular share stays as it was. A pattern-suggested
    L keeps the equal share: it must not win by getting more attempts."""
    share = n if len(topologies) <= 1 else max(1, n // len(topologies))
    picked: list[Candidate] = []
    for t in topologies:
        if t != "rect" and l_share is not None:
            share = max(share, l_share)
        of_t = [c for c in candidates if c.skeleton.topology == t]
        if t != "rect":
            seen: set[tuple[float, ...]] = set()
            distinct = []
            for c in of_t:
                sk = c.skeleton
                key = (sk.W, sk.D, sk.Ds, sk.wing_length, sk.wing_depth, sk.wing_x0)
                if key not in seen:
                    seen.add(key)
                    distinct.append(c)
            orders = {c.order for c in distinct}
            of_t = distinct + [c for c in of_t if c.order not in orders]
        picked += of_t[:share]
    orders = {c.order for c in picked}
    total = n if l_share is None else max(n, len(picked))
    picked += [c for c in candidates if c.order not in orders][: max(0, total - len(picked))]
    return sorted(picked, key=lambda c: (round(c.score, 9), c.order))


def _topology_report(
    choice: TopologyChoice,
    best: "_Built",
    valid: list["_Built"],
    by_topology: dict[str, int],
    inp: SearchInput,
    config: LayoutConfig,
) -> TopologyReport:
    footprint = best.evaluation.footprint
    generated = footprint.shape if footprint is not None else "other"
    built = {t: sum(b.candidate.skeleton.topology == t for b in valid) for t in choice.topologies}
    if len(choice.topologies) == 1:
        explanation = choice.reason
    else:
        scores = {
            t: max(
                (b.evaluation.score for b in valid if b.candidate.skeleton.topology == t),
                default=None,
            )
            for t in choice.topologies
        }
        parts = [
            f"best {SHAPE_NAMES[t]} design score {s:.2f}"
            if s is not None
            else f"no valid {SHAPE_NAMES[t]} layout"
            for t, s in scores.items()
        ]
        target = choice.target if _wants_wing(choice) else None
        if target is not None:
            name = SHAPE_NAMES[target]
            decision = (
                f"the requested {name} footprint was generated"
                if generated == MEASURED[target]
                else f"no valid {name} layout met every mandatory requirement, so the "
                "rectangular alternative was kept"
            )
        else:
            decision = f"the {MEASURED_LABELS.get(generated, generated)} design scored higher"
        explanation = f"{choice.reason}; {', '.join(parts)}; {decision}"
        for t in choice.topologies:
            if t == "rect" or by_topology.get(t, 0) > 0:
                continue
            reasons: list[str] = []
            WING_SKELETONS[t](inp, config, reasons, "ratio")
            WING_SKELETONS[t](inp, config, reasons, "depth")
            why = sorted(set(reasons), key=lambda r: (-reasons.count(r), r))[:2]
            explanation += f"; no {SHAPE_NAMES[t]} layout fits" + (
                f" ({'; '.join(why)})" if why else ""
            )
    return TopologyReport(
        generated=generated,
        requested=choice.requested,
        mandatory=choice.mandatory,
        searched=choice.topologies,
        reason=choice.reason,
        explanation=explanation,
        candidates=dict(by_topology),
        built_valid=built,
        limitation=choice.unsupported,
    )


def _topology_infeasible(
    exc: PlanningError,
    choice: TopologyChoice,
    inp: SearchInput,
    config: LayoutConfig,
    seed: int,
) -> LayoutError:
    """A required L or T that does not fit is reported as such, with whether a rectangle
    would (never a silent rectangle)."""
    error = _infeasible(exc)
    if len(choice.topologies) != 1 or choice.topologies[0] == "rect":
        return error
    name = SHAPE_NAMES[choice.topologies[0]]
    try:
        rect_fits = bool(search(replace(inp, topologies=("rect",)), config, seed))
    except PlanningError:
        rect_fits = False
    error.message = f"No {name} layout fits this specification"
    error.issues.insert(
        0,
        Issue(
            severity="error",
            code="LAYOUT_INFEASIBLE",
            path="/design/footprint_shape",
            message=f"The required {name} footprint cannot be laid out: "
            + "; ".join(exc.reasons[:3]),
            suggestion=f"A rectangular footprint would fit: make the {name} shape a preference "
            "or drop it."
            if rect_fits
            else "Change the floor area, the plot or the room programme.",
        ),
    )
    return error


def _infeasible(exc: PlanningError) -> LayoutError:
    return LayoutError(
        "LAYOUT_INFEASIBLE",
        str(exc),
        [
            Issue(severity="error", code="LAYOUT_INFEASIBLE", path="", message=reason)
            for reason in exc.reasons
        ]
        or [Issue(severity="error", code="LAYOUT_INFEASIBLE", path="", message=str(exc))],
    )


def _orientation(
    model: BuildingModel, program: Program, spec: BuildingSpecification
) -> list[Issue]:
    """ROOM_FACADE_UNMET for a room that does not reach the facade it should face, measured
    on the model's exterior walls (an L wing's side walls are not the garden facade). The
    message names the rooms that hold that facade: the actual limitation."""
    out: list[Issue] = []
    rooms = {el.semantic_key: el for el in model.elements if isinstance(el, Room)}
    on_facade = summarize(model).rooms_on_facade
    for key, side in resolve_facade_preferences(spec).items():
        for inst in program.instances(key):
            room = rooms.get(f"room:{inst.key}")
            if room is None or side not in BAND_OF_FACADE:
                continue
            holders = on_facade.get(side.value, [])
            if room.semantic_key not in holders:
                names = sorted(
                    rooms[k].name
                    for k in holders
                    if k in rooms
                    and rooms[k].properties.zone != Zone.EXTERIOR
                    and rooms[k].properties.room_type != RoomType.GARAGE
                )
                out.append(
                    Issue(
                        severity="warning",
                        code="ROOM_FACADE_UNMET",
                        path=pointer("rooms", inst.spec_index, "faces"),
                        message=f"{inst.name} could not be placed on the {side.value} facade"
                        + (f" (it is taken by {', '.join(names)})" if names else ""),
                    )
                )
    return out


def _deviations(
    cand: Candidate,
    program: Program,
    spec: BuildingSpecification,
    gfa: float,
    evaluation: DesignEvaluation,
) -> list[Issue]:
    """Where the result departs from what was asked (never hidden from the user)."""
    out: list[Issue] = []
    for r in program.rooms:
        if not r.explicit_target or r.area_low is None or r.area_high is None:
            continue
        actual = cand.areas.get(r.key, 0.0)
        if not r.area_low - 1e-6 <= actual <= r.area_high + 1e-6:
            out.append(
                Issue(
                    severity="warning",
                    code="LAYOUT_AREA_DEVIATION",
                    path=pointer("rooms", r.spec_index, "target_area_m2"),
                    message=f"{r.name}: {actual:.1f} m² instead of the requested "
                    f"{r.target_area:.1f} m² (accepted {r.area_low:.1f}-{r.area_high:.1f} m²)",
                )
            )
    for check in evaluation.requirements:
        if check.kind == "separate" and not check.met:
            out.append(
                Issue(
                    severity="warning",
                    code="LAYOUT_SEPARATION",
                    path=check.path,
                    message=f"{check.label}: {check.delivered}",
                )
            )
    actual_gfa = cand.skeleton.footprint_area * spec.targets.storeys
    if (
        spec.targets.gross_floor_area_m2 is not None
        and abs(actual_gfa - gfa) / gfa > GFA_WARNING_THRESHOLD
    ):
        out.append(
            Issue(
                severity="warning",
                code="LAYOUT_GFA_DEVIATION",
                path="/targets/gross_floor_area_m2",
                message=f"Gross floor area is {actual_gfa:.0f} m² instead of {gfa:.0f} m²",
            )
        )
    for kind, a, b in unmet_pairs(cand.levels, program):
        idx = program.instances(a)[0].spec_index if program.instances(a) else 0
        out.append(
            Issue(
                severity="warning",
                code="LAYOUT_ADJACENCY",
                path=pointer("rooms", idx),
                message=f"{a} could not be placed {'next' if kind == 'adjacent' else 'open'} "
                f"to {b}",
            )
        )
    return out
