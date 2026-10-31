"""Pattern selection: which layout patterns apply to a specification, and what they ask of the
candidate search (Design Intelligence V1, docs/3d-engine.md §16.8).

Deterministic. Triggers are read from the spec (never from free text), the applicable patterns
are those of the library whose triggers are present and that the engine can realise, in id
order. Their recipes merge into one `PatternGuidance` the planner scores with:

    band preference per room type   explicit spec wishes (rooms[].faces, balcony / terrace
                                    hosts) always win; among patterns the first one wins
    affinities / separations         summed per room-type pair
    footprint aspect                 intersection of the ranges; the first range if they
                                     do not overlap (reported)

Patterns are soft heuristics: nothing here makes a candidate infeasible.
"""

import math
from dataclasses import dataclass, field

from app.modules.building.enums import RoomType
from app.modules.building.patterns import (
    EngineSupport,
    LayoutPattern,
    PatternLibrary,
    PatternTrigger,
)
from app.modules.building.specification import (
    BuildingSpecification,
    DesignPriority,
    FacadeSide,
    SpecRoomType,
)

# A footprint limit narrower than this share of the side of a square storey forces a deep plan
# (classification heuristic, not a dimensional rule of the design).
NARROW_SHARE_OF_SQUARE = 0.9
BAND_OF_SIDE = {"garden": "north", "street": "south", "wing": "wing"}
TOPOLOGY_OF_RECIPE = {"l_shape": "l"}


@dataclass(frozen=True)
class AppliedPattern:
    """A pattern that steered the search, why, and how far it is trusted."""

    id: str
    name: str
    source: str
    status: str
    engine_support: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PatternGuidance:
    applied: tuple[AppliedPattern, ...] = ()
    band: dict[RoomType, tuple[str, float]] = field(default_factory=dict)  # -> (band, weight)
    affinities: dict[frozenset[RoomType], float] = field(default_factory=dict)
    separations: dict[frozenset[RoomType], float] = field(default_factory=dict)
    aspect: tuple[float, float] | None = None
    notes: tuple[str, ...] = ()
    # Extra footprint topologies to search ("l"), with the patterns that asked for them.
    topologies: tuple[str, ...] = ()
    topology_sources: tuple[str, ...] = ()

    def band_penalty(self, room_type: RoomType, band: str) -> float:
        want = self.band.get(room_type)
        if want is None or want[0] == band:
            return 0.0
        return want[1]

    def affinity(self, a: RoomType, b: RoomType) -> float:
        return self.affinities.get(frozenset({a, b}), 0.0)

    def separation(self, a: RoomType, b: RoomType) -> float:
        return self.separations.get(frozenset({a, b}), 0.0)


NO_GUIDANCE = PatternGuidance()


def detect_triggers(
    spec: BuildingSpecification,
    floor_area_per_storey: float,
    max_width: float | None,
    max_depth: float | None,
) -> dict[PatternTrigger, str]:
    """Spec conditions present -> the reason in words (shown in the report)."""
    found: dict[PatternTrigger, str] = {}
    priorities = set(spec.design.priorities)
    rear_rooms = [r.key for r in spec.rooms if r.faces == FacadeSide.REAR]
    windows = spec.design.windows
    if rear_rooms:
        found[PatternTrigger.GARDEN_FOCUS] = f"rooms facing the garden: {', '.join(rear_rooms)}"
    elif windows is not None and FacadeSide.REAR in windows.preferred_facades:
        found[PatternTrigger.GARDEN_FOCUS] = f"{windows.emphasis.value} windows on the rear"
    elif spec.features.terrace is not None:
        found[PatternTrigger.GARDEN_FOCUS] = "garden terrace"
    elif DesignPriority.GARDEN_CONNECTION in priorities:
        found[PatternTrigger.GARDEN_FOCUS] = "garden connection is a priority"
    square_side = math.sqrt(floor_area_per_storey)
    if max_width is not None and max_width < NARROW_SHARE_OF_SQUARE * square_side:
        found[PatternTrigger.NARROW_SITE] = (
            f"footprint limited to {max_width:.1f} m wide for {floor_area_per_storey:.0f} m² "
            "per storey"
        )
    elif max_width is not None and max_depth is not None and max_width < 0.8 * max_depth:
        found[PatternTrigger.NARROW_SITE] = "buildable area is much deeper than wide"
    open_rooms = [r.key for r in spec.rooms if r.open_to]
    if any(r.type == SpecRoomType.OPEN_KITCHEN_LIVING for r in spec.rooms):
        found[PatternTrigger.OPEN_PLAN] = "open kitchen-living space"
    elif open_rooms:
        found[PatternTrigger.OPEN_PLAN] = f"open-plan rooms: {', '.join(open_rooms)}"
    elif DesignPriority.OPEN_PLAN in priorities:
        found[PatternTrigger.OPEN_PLAN] = "open plan is a priority"
    if DesignPriority.COMPACTNESS in priorities:
        found[PatternTrigger.COMPACT_PROGRAM] = "compactness is a priority"
    separated = [r.key for r in spec.rooms if r.separate_from]
    if separated:
        found[PatternTrigger.PRIVACY_ZONING] = f"rooms kept apart: {', '.join(separated)}"
    elif DesignPriority.PRIVACY in priorities:
        found[PatternTrigger.PRIVACY_ZONING] = "privacy is a priority"
    return found


def _reasons(
    pattern: LayoutPattern,
    triggers: dict[PatternTrigger, str],
    storeys: int,
    floor_area_per_storey: float,
) -> list[str]:
    app = pattern.applicability
    if storeys not in app.storeys:
        return []
    if any(t not in triggers for t in app.required_triggers):
        return []
    if (
        app.min_floor_area_per_storey_m2 is not None
        and floor_area_per_storey < app.min_floor_area_per_storey_m2
    ):
        return []
    reasons = [triggers[t] for t in app.triggers if t in triggers]
    if reasons:
        reasons += [triggers[t] for t in app.required_triggers if triggers[t] not in reasons]
    limit = app.max_floor_area_per_storey_m2
    if (
        PatternTrigger.COMPACT_PROGRAM in app.triggers
        and PatternTrigger.COMPACT_PROGRAM not in triggers
        and limit is not None
        and floor_area_per_storey <= limit
    ):
        reasons.append(f"{floor_area_per_storey:.0f} m² per storey (compact programme)")
    return reasons


def select_patterns(
    library: PatternLibrary | None,
    spec: BuildingSpecification,
    floor_area_per_storey: float,
    max_width: float | None,
    max_depth: float | None,
) -> PatternGuidance:
    if library is None or not library.patterns:
        return NO_GUIDANCE
    triggers = detect_triggers(spec, floor_area_per_storey, max_width, max_depth)
    applied: list[AppliedPattern] = []
    band: dict[RoomType, tuple[str, float]] = {}
    affinities: dict[frozenset[RoomType], float] = {}
    separations: dict[frozenset[RoomType], float] = {}
    aspect: tuple[float, float] | None = None
    notes: list[str] = []
    topologies: list[str] = []
    topology_sources: list[str] = []
    for pattern in sorted(library.patterns, key=lambda p: p.id):
        if pattern.engine_support == EngineSupport.NONE:
            continue
        reasons = _reasons(pattern, triggers, spec.targets.storeys, floor_area_per_storey)
        if not reasons:
            continue
        applied.append(
            AppliedPattern(
                id=pattern.id,
                name=pattern.name,
                source=pattern.source,
                status=pattern.status,
                engine_support=pattern.engine_support.value,
                reasons=tuple(reasons),
            )
        )
        recipe = pattern.recipe
        if recipe.topology is not None:
            topo = TOPOLOGY_OF_RECIPE[recipe.topology]
            if topo not in topologies:
                topologies.append(topo)
            topology_sources.append(pattern.id)
        for pref in recipe.band_preferences:
            for t in pref.room_types:
                band.setdefault(t, (BAND_OF_SIDE[pref.side], pref.weight))
        for pair in recipe.affinities:
            k = frozenset({pair.a, pair.b})
            affinities[k] = affinities.get(k, 0.0) + pair.weight
        for pair in recipe.separations:
            k = frozenset({pair.a, pair.b})
            separations[k] = separations.get(k, 0.0) + pair.weight
        if recipe.footprint_aspect is not None:
            low, high = recipe.footprint_aspect
            if aspect is None:
                aspect = (low, high)
            elif max(aspect[0], low) <= min(aspect[1], high):
                aspect = (max(aspect[0], low), min(aspect[1], high))
            else:
                notes.append(
                    f"{pattern.name}: its footprint proportions conflict with an earlier "
                    "pattern; the earlier one was kept"
                )
    return PatternGuidance(
        applied=tuple(applied),
        band=band,
        affinities=affinities,
        separations=separations,
        aspect=aspect,
        notes=tuple(notes),
        topologies=tuple(topologies),
        topology_sources=tuple(topology_sources),
    )
