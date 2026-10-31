"""Steps 2-5 and 10 — levels, footprint, stair core, zoning, subdivision, candidate scoring.

The plan is a double-loaded corridor on every level: a street-side band (south), a corridor
band and a garden-side band (north), stacked identically on all storeys. The stair core sits in
the south band; on the ground floor it is part of the entrance hall. Every room spans its band
from the corridor to the facade (so it is reachable and gets daylight), except small service
rooms, which may be "tucked" against the corridor inside a larger room's column; that room then
wraps around them (L-shape) on the facade side.

The search enumerates skeletons (footprint proportions, band depth, core position) and, per
seeded variant, assigns rooms to bands and orders them. Candidates are scored on area error,
proportions and adjacency; the best ones go on to be built and validated.
"""

import itertools
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.modules.building.enums import RoomType
from app.modules.building.specification import BuildingSpecification, DesignPriority
from app.modules.layout.config import LayoutConfig
from app.modules.layout.constraints import flights_fit_lanes
from app.modules.layout.patterns import NO_GUIDANCE, PatternGuidance
from app.modules.layout.plan import (
    Candidate,
    Column,
    CorridorCut,
    LevelLayout,
    Skeleton,
    StairDesign,
    Strip,
    StripLayout,
    rnd,
    snap,
    snap_down,
    snap_up,
)
from app.modules.layout.program import PRIVATE, PUBLIC, TUCKABLE, WET, Program, RoomRequest
from app.modules.rules.profile import BuildingRulesProfile

EPS = 1e-6
UPSTAIRS_OK = frozenset(
    {
        RoomType.BEDROOM,
        RoomType.BATHROOM,
        RoomType.STUDY,
        RoomType.STORAGE,
        RoomType.LAUNDRY,
        RoomType.EN_SUITE,
        RoomType.WALK_IN_CLOSET,
    }
)
# Affinity of small service rooms for the room they are tucked into.
TUCK_AFFINITY: dict[RoomType, dict[RoomType, float]] = {
    RoomType.WC: {
        RoomType.LIVING: 3,
        RoomType.DINING: 3,
        RoomType.OPEN_KITCHEN_LIVING: 3,
        RoomType.KITCHEN: 2,
        RoomType.STUDY: 2,
        RoomType.BEDROOM: 1,
    },
    RoomType.BATHROOM: {
        RoomType.BEDROOM: 3,
        RoomType.STUDY: 2,
        RoomType.LIVING: 1,
        RoomType.DINING: 1,
        RoomType.OPEN_KITCHEN_LIVING: 1,
        RoomType.KITCHEN: 0.5,
    },
    RoomType.STORAGE: {RoomType.KITCHEN: 3, RoomType.OPEN_KITCHEN_LIVING: 3},
    RoomType.LAUNDRY: {RoomType.KITCHEN: 3, RoomType.OPEN_KITCHEN_LIVING: 3},
    RoomType.UTILITY: {RoomType.KITCHEN: 3, RoomType.OPEN_KITCHEN_LIVING: 3},
}
# Pairs that like to be neighbours even when the spec does not say so.
IMPLICIT_AFFINITY: dict[frozenset[RoomType], float] = {
    frozenset({RoomType.KITCHEN, RoomType.DINING}): 1.5,
    frozenset({RoomType.DINING, RoomType.LIVING}): 1.5,
    frozenset({RoomType.KITCHEN, RoomType.LIVING}): 1.0,
}
HABITABLE_TYPES = PUBLIC | PRIVATE
WING_DAY_PENALTY = 1.6  # living/dining/kitchen in an L's bedroom wing (band preference)
# Rooms an L's garden band is sized for first (garden_demands).
GARDEN_LIVING = frozenset({RoomType.LIVING, RoomType.OPEN_KITCHEN_LIVING})
ASPECT_LIMIT = {"habitable": 2.2, "service": 3.2}
# Search weights of spec pairs (penalty when missed). MUST pairs are also hard checks after the
# build (building/evaluation.py); the high weight steers the search towards meeting them.
PAIR_WEIGHT = {"adjacent": 1.5, "open": 1.5, "separate": 1.2}
MUST_PAIR_WEIGHT = 5.0
# Explicit room targets: extra penalty per unit of relative deviation outside the permissible
# range (and a flat one for a MUST target), on top of the general area term.
AREA_RANGE_WEIGHT = 8.0
AREA_MUST_PENALTY = 4.0
# Pattern guidance (soft): footprint proportions outside the preferred range, missed type
# affinities, type separations broken.
PATTERN_ASPECT_WEIGHT = 1.5
PATTERN_PAIR_SCALE = 0.5
L_WING_RATIO_WEIGHT = 3.0  # per unit of wing length / main width outside config.l_wing_ratio
# L plans (V1.2): per unit of circulation share (corridor, gallery, hall / footprint). Rooms
# grow when the corridor shrinks (the floor area is fixed), which the area terms would
# otherwise count against the shorter corridor.
L_CIRCULATION_WEIGHT = 12.0


class PlanningError(Exception):
    """No feasible plan. `reasons` explain why (tier-3 feasibility)."""

    def __init__(self, message: str, reasons: list[str]) -> None:
        super().__init__(message)
        self.reasons = reasons


# --- stair ------------------------------------------------------------------------------------


def design_stair(
    floor_to_floor: float, profile: BuildingRulesProfile, config: LayoutConfig
) -> StairDesign:
    s = profile.stairs
    risers = math.ceil(floor_to_floor / s.riser_m.max - 1e-9)
    if risers > s.max_risers_per_flight:
        raise PlanningError(
            "The storey height is too large for a straight flight",
            [
                f"{floor_to_floor} m needs {risers} risers of at most {s.riser_m.max} m; one "
                f"flight allows {s.max_risers_per_flight}"
            ],
        )
    riser = floor_to_floor / risers
    tread = round(config.stair_comfort_target - 2 * riser, 3)
    tread = min(max(tread, s.tread_m.min), s.tread_m.max)
    comfort = 2 * riser + tread
    if comfort < s.comfort_rule.min:
        tread = min(s.tread_m.max, round(s.comfort_rule.min - 2 * riser + 0.0005, 3))
    elif comfort > s.comfort_rule.max:
        tread = max(s.tread_m.min, round(s.comfort_rule.max - 2 * riser - 0.0005, 3))
    width = max(config.stair_width, s.min_width_m)
    lane = snap_up(width + 2 * config.stair_clearance + config.interior_wall_thickness, config.grid)
    return StairDesign(
        risers=risers,
        riser=riser,
        tread=tread,
        run=rnd((risers - 1) * tread),
        width=width,
        lane_width=lane,
    )


# --- levels -----------------------------------------------------------------------------------


def _capacities(
    floor_area: float, storeys: int, stair: StairDesign | None, config: LayoutConfig
) -> list[float]:
    """Room area available per level (footprint minus corridor, core and entrance hall)."""
    width = math.sqrt(floor_area * 1.3)
    depth_south = 5.0
    corridor = config.corridor_width * width
    core = (storeys - 1) * (stair.lane_width if stair else 0) * depth_south
    hall = config.entrance_hall_width * depth_south
    return [
        max(1.0, floor_area - corridor - core - (hall if level == 0 else 0))
        for level in range(storeys)
    ]


def assign_levels(
    program: Program,
    storeys: int,
    floor_area: float,
    stair: StairDesign | None,
    config: LayoutConfig,
) -> dict[str, int]:
    rooms = program.by_key()
    levels: dict[str, int] = {}
    if storeys == 1:
        return dict.fromkeys(rooms, 0)
    capacity = _capacities(floor_area, storeys, stair, config)
    upper = list(range(1, storeys))

    def load(level: int) -> float:
        return sum(rooms[k].target_area for k, lv in levels.items() if lv == level)

    primaries = [r for r in program.rooms if r.serves is None]
    for r in primaries:
        if r.level is not None:
            levels[r.key] = r.level
    # Bedrooms upstairs, largest first, each to the upper level with the most free capacity.
    bedrooms = sorted(
        (r for r in primaries if r.type == RoomType.BEDROOM and r.key not in levels),
        key=lambda r: (-r.target_area, r.key),
    )
    for r in bedrooms:
        levels[r.key] = max(upper, key=lambda lv: (capacity[lv] - load(lv), -lv))
    # One bathroom per level that has bedrooms, then the ground floor, then upstairs again.
    bathrooms = sorted(
        (r for r in primaries if r.type == RoomType.BATHROOM and r.key not in levels),
        key=lambda r: r.key,
    )
    bedroom_levels = sorted(
        {levels[r.key] for r in primaries if r.type == RoomType.BEDROOM}, reverse=True
    )
    wanted = [lv for lv in bedroom_levels if lv > 0] + [0]
    for i, r in enumerate(bathrooms):
        levels[r.key] = wanted[i] if i < len(wanted) else max(upper, key=load)
    for r in primaries:
        if r.key not in levels:
            levels[r.key] = 0

    def sync_attached() -> None:
        for r in program.rooms:
            if r.serves is not None:
                levels[r.key] = levels[r.serves]

    sync_attached()

    def unit_area(r: RoomRequest) -> float:
        return r.target_area + sum(rooms[a].target_area for a in r.attached)

    def movable(r: RoomRequest, to: int) -> bool:
        if r.level is not None or r.serves is not None:
            return False
        if to > 0 and r.type not in UPSTAIRS_OK:
            return False
        if r.type == RoomType.BATHROOM:  # keep a bathroom on every level with bedrooms
            here = levels[r.key]
            baths_here = [
                b for b in primaries if b.type == RoomType.BATHROOM and levels[b.key] == here
            ]
            has_bedroom = any(
                b.type == RoomType.BEDROOM and levels[b.key] == here for b in primaries
            )
            if has_bedroom and len(baths_here) <= 1:
                return False
        return True

    for _ in range(60):
        ratios = [load(lv) / capacity[lv] for lv in range(storeys)]
        spread = sum((x - 1) ** 2 for x in ratios)
        best: tuple[float, str, int] | None = None
        for r in sorted(primaries, key=lambda r: r.key):
            src = levels[r.key]
            for dst in range(storeys):
                if dst == src or not movable(r, dst):
                    continue
                a = unit_area(r)
                new = list(ratios)
                new[src] = (load(src) - a) / capacity[src]
                new[dst] = (load(dst) + a) / capacity[dst]
                # Never empty an upper level.
                if src > 0 and not any(levels[o.key] == src for o in primaries if o.key != r.key):
                    continue
                score = sum((x - 1) ** 2 for x in new)
                if score < spread - 0.005 and (best is None or score < best[0]):
                    best = (score, r.key, dst)
        if best is None:
            break
        levels[best[1]] = best[2]
        sync_attached()

    for lv in upper:
        if not any(levels[r.key] == lv for r in primaries):
            raise PlanningError(
                "An upper floor would have no rooms",
                [f"No room can be placed on floor {lv + 1}; add rooms or reduce the storeys"],
            )
    return levels


# --- units --------------------------------------------------------------------------------------


@dataclass
class Unit:
    primary: RoomRequest
    attached: list[RoomRequest] = field(default_factory=list)

    @property
    def area(self) -> float:
        return self.primary.target_area + sum(a.target_area for a in self.attached)

    @property
    def rooms(self) -> list[RoomRequest]:
        return [self.primary, *self.attached]


def form_units(level_rooms: list[RoomRequest], config: LayoutConfig) -> list[Unit]:
    """Group each small service room with the room it will be tucked into."""
    units: dict[str, Unit] = {}
    small: list[RoomRequest] = []
    for r in level_rooms:
        if r.serves is not None:
            continue
        # Would be a skinny column at full band depth (~4.2 m or more): tuck it instead.
        if r.tuckable and r.target_area < config.tuck_widths[r.type] * 4.2:
            small.append(r)
            continue
        units[r.key] = Unit(r)
    for r in level_rooms:
        if r.serves is not None and r.serves in units:
            units[r.serves].attached.append(r)
        elif r.serves is not None:  # bedroom missing on this level: stand alone
            units[r.key] = Unit(r)
    for s in sorted(small, key=lambda r: (-r.target_area, r.key)):
        table = TUCK_AFFINITY.get(s.type, {})
        hosts = [
            u for u in units.values() if u.primary.type not in TUCKABLE and len(u.attached) < 2
        ]
        if not hosts:
            units[s.key] = Unit(s)
            continue
        host = max(
            hosts,
            key=lambda u: (table.get(u.primary.type, 0.5), u.primary.target_area, u.primary.key),
        )
        host.attached.append(s)
    return sorted(units.values(), key=lambda u: u.primary.key)


# --- strips -----------------------------------------------------------------------------------


def level_strips(sk: Skeleton, level: int) -> list[Strip]:
    y_s1 = sk.Ds
    y_n0 = rnd(sk.Ds + sk.C)
    if level == 0:
        g0, g1 = sk.group_x0, sk.group_x1
    else:
        g0, g1 = (sk.core_x0, sk.core_x1) if sk.lanes > 0 else (0.0, 0.0)
    names: tuple[Literal["N", "N2"], ...] = ("N", "N2")
    strips = [
        Strip(name, n0, n1, y_n0, sk.D, "north")
        for name, (n0, n1) in zip(names, sk.garden_ranges, strict=False)
    ]
    if sk.has_wing:  # the wing's rooms run along y from the corridor to the wing's end
        w0, w1 = sk.wing_rooms_x
        strips.append(
            Strip(
                "WG",
                w0,
                w1,
                y_n0,
                sk.depth_total,
                "wing",
                axis="y",
                corridor_low=sk.wing_side == "east",  # the gallery on the rooms' other side
                end_wrap_depth=sk.C,  # the room at the wing's end may take the gallery's end
            )
        )
    if sk.lanes == 0 and level > 0:  # (1-storey houses have no upper levels)
        return strips
    if g1 - g0 < EPS:  # no core, no hall: one south strip
        strips.append(Strip("SL", 0.0, sk.W, 0.0, y_s1, "south", corridor_low=False))
        return strips
    strips.append(Strip("SL", 0.0, g0, 0.0, y_s1, "south", corridor_low=False))
    strips.append(Strip("SR", g1, sk.W, 0.0, y_s1, "south", corridor_low=False))
    return strips


def _strip_pref(
    unit: Unit,
    strip: Strip,
    level: int,
    wishes: dict[str, str],
    guidance: PatternGuidance = NO_GUIDANCE,
) -> float:
    """Penalty for placing `unit` in `strip` (zoning). `wishes`: room key -> facade side it
    must reach (rooms[].faces, balcony / terrace hosts); explicit wishes win over pattern
    band preferences, which add to the generic type preferences."""
    t = unit.primary.type
    wish = wishes.get(unit.primary.key)
    if wish is not None and wish != strip.side:
        # An unmet facade wish adds to (never replaces) the room type's own band preference,
        # so a living room missing the garden costs more than a dining room missing it.
        return 3.0 + _type_pref(t, strip, level)
    pattern = guidance.band_penalty(t, strip.side) if wish is None else 0.0
    return pattern + _type_pref(t, strip, level)


def _type_pref(t: RoomType, strip: Strip, level: int) -> float:
    if strip.side == "wing":  # the L's wing: a private wing (bedrooms, study, their baths)
        if t in PRIVATE or t in TUCKABLE:
            return 0.0
        # Day rooms belong in the main bar: in the bedroom wing they cost more than a living
        # room on the street side (V1.2), so the wing's north end is no back door to the garden.
        return WING_DAY_PENALTY if t in PUBLIC else 0.8
    if strip.side == "north":
        if t in TUCKABLE:
            return 0.35
        return 0.0
    if level == 0 and t in {RoomType.LIVING, RoomType.OPEN_KITCHEN_LIVING}:
        return 1.5
    if level == 0 and t in PUBLIC:
        return 0.3
    if t == RoomType.BEDROOM:
        return 0.1
    return 0.0


def _min_len(unit: Unit, config: LayoutConfig) -> float:
    """Lower bound of a unit's width (attached rooms as narrow full-depth columns)."""
    return frontage(unit.primary, config) + sum(frontage(a, config) for a in unit.attached)


@dataclass(frozen=True)
class Zoning:
    """Placement wishes that come from the spec rather than from room types."""

    wishes: dict[str, str]  # room key -> facade side ("north"/"south") it must reach
    pairs: list[tuple[frozenset[str], frozenset[str], float]]  # room-key groups + weight
    # Room-key groups that must not share a wall (spec separate_from) + weight.
    apart: list[tuple[frozenset[str], frozenset[str], float]] = field(default_factory=list)
    guidance: PatternGuidance = NO_GUIDANCE

    @staticmethod
    def of(
        program: Program, wishes: dict[str, str], guidance: PatternGuidance = NO_GUIDANCE
    ) -> "Zoning":
        def groups(
            kind: str, pairs: list[tuple[str, str]]
        ) -> list[tuple[frozenset[str], frozenset[str], float]]:
            return [
                (
                    frozenset(r.key for r in program.instances(a)),
                    frozenset(r.key for r in program.instances(b)),
                    pair_weight(program, kind, a, b),
                )
                for a, b in pairs
            ]

        return Zoning(
            wishes,
            groups("adjacent", program.adjacency) + groups("open", program.open_plan),
            groups("separate", program.separate),
            guidance,
        )


def pair_weight(program: Program, kind: str, a: str, b: str) -> float:
    """Search weight of a spec pair: MUST pairs weigh far more than preferences."""
    lo, hi = sorted((a, b))
    if (kind, lo, hi) in program.must_pairs:
        return MUST_PAIR_WEIGHT
    return PAIR_WEIGHT[kind]


def assign_strips(
    units: list[Unit],
    strips: list[Strip],
    level: int,
    rng: random.Random,
    config: LayoutConfig,
    zoning: Zoning,
) -> dict[str, list[Unit]] | None:
    live = [s for s in strips if s.length > EPS]
    if not live:
        return None
    units = [Unit(u.primary, list(u.attached)) for u in units]  # moves below may detach rooms
    cap = {s.name: s.length * s.depth for s in live}
    wishes = zoning.wishes

    def cost(assign: dict[str, list[Unit]]) -> float:
        total = 0.0
        strip_of: dict[str, str] = {}
        for s in live:
            us = assign[s.name]
            if not us:
                total += 3.0 + s.length * 0.4
                continue
            load = sum(u.area for u in us)
            total += 4 * (load / cap[s.name] - 1) ** 2
            if sum(_min_len(u, config) for u in us) > s.length + EPS:
                total += 25
            for u in us:
                if u.primary.min_width > s.depth + EPS:
                    total += 25
                total += _strip_pref(u, s, level, wishes, zoning.guidance)
                for r in u.rooms:
                    strip_of[r.key] = s.name
        for a, b, weight in zoning.pairs:  # wanted neighbours must share a band
            sa = {strip_of[k] for k in a if k in strip_of}
            sb = {strip_of[k] for k in b if k in strip_of}
            if sa and sb and not sa & sb:
                total += weight
        for a, b, weight in zoning.apart:  # rooms kept apart are safest in different bands
            sa = {strip_of[k] for k in a if k in strip_of}
            sb = {strip_of[k] for k in b if k in strip_of}
            if sa & sb:
                total += 0.5 * weight
        return total

    # Largest first, with seeded noise so variants explore different assignments.
    keyed = sorted(units, key=lambda u: u.primary.key)
    noise = {u.primary.key: rng.uniform(-4.0, 4.0) for u in keyed}
    order = sorted(keyed, key=lambda u: (-u.area + noise[u.primary.key], u.primary.key))
    assign: dict[str, list[Unit]] = {s.name: [] for s in live}
    strip_by_name: dict[str, Strip] = {s.name: s for s in live}

    def fits(n: str, u: Unit) -> bool:
        s = strip_by_name[n]
        used = sum(_min_len(x, config) for x in assign[n])
        return used + _min_len(u, config) <= s.length + EPS and u.primary.min_width <= s.depth + EPS

    for u in order:
        best_name = min(
            (s.name for s in live),
            key=lambda n: (
                not fits(n, u),
                (sum(x.area for x in assign[n]) + u.area) / cap[n]
                + _strip_pref(u, strip_by_name[n], level, wishes, zoning.guidance),
                n,
            ),
        )
        assign[best_name].append(u)

    current = cost(assign)
    names = [s.name for s in live]

    def exchange(src: str, dst: str, out: list[Unit], back: list[Unit]) -> bool:
        """Move `out` src -> dst and `back` dst -> src; keep the change if the cost drops."""
        nonlocal current
        for u in out:
            assign[src].remove(u)
            assign[dst].append(u)
        for u in back:
            assign[dst].remove(u)
            assign[src].append(u)
        c = cost(assign)
        if c < current - 1e-9:
            current = c
            return True
        for u in out:
            assign[dst].remove(u)
            assign[src].append(u)
        for u in back:
            assign[src].remove(u)
            assign[dst].append(u)
        return False

    def improve() -> bool:
        """First-improvement local search: move one, swap one for one, swap one for two."""
        for src, dst in itertools.permutations(names, 2):
            if any(exchange(src, dst, [u], []) for u in list(assign[src])):
                return True
        for a, b in itertools.combinations(names, 2):
            pairs = itertools.product(list(assign[a]), list(assign[b]))
            if any(exchange(a, b, [ua], [ub]) for ua, ub in pairs):
                return True
        for a, b in itertools.permutations(names, 2):  # e.g. bedroom + bath for two bedrooms
            for ua in list(assign[a]):
                twos = itertools.combinations(list(assign[b]), 2)
                if any(exchange(a, b, [ua], [x, y]) for x, y in twos):
                    return True
        return False

    for _ in range(40):
        if not improve():
            break

    # A street-side strip left empty can take a service room detached from its host unit
    # (e.g. a bathroom that would otherwise be tucked into a bedroom).
    for empty in live:
        if assign[empty.name]:
            continue
        best: tuple[float, Unit, RoomRequest] | None = None
        for other in live:
            for host_unit in assign[other.name]:
                for service in list(host_unit.attached):
                    if service.serves is not None or frontage(service, config) > empty.length + EPS:
                        continue
                    host_unit.attached.remove(service)
                    assign[empty.name].append(Unit(service))
                    c = cost(assign)
                    assign[empty.name].pop()
                    host_unit.attached.append(service)
                    if c < current - 1e-9 and (best is None or c < best[0]):
                        best = (c, host_unit, service)
        if best is not None:
            current, chosen_host, chosen = best
            chosen_host.attached.remove(chosen)
            assign[empty.name].append(Unit(chosen))
    for s in strips:
        assign.setdefault(s.name, [])
    return assign


def _affinity(a: Unit, b: Unit, program: Program, guidance: PatternGuidance = NO_GUIDANCE) -> float:
    keys_a = {r.spec_key for r in a.rooms}
    keys_b = {r.spec_key for r in b.rooms}

    def links(x: str, y: str) -> bool:
        return (x in keys_a and y in keys_b) or (y in keys_a and x in keys_b)

    score = 0.0
    for x, y in program.adjacency:
        if links(x, y):
            score += 6 if pair_weight(program, "adjacent", x, y) == MUST_PAIR_WEIGHT else 2
    for x, y in program.open_plan:
        if links(x, y):
            score += 4
    for x, y in program.separate:
        if links(x, y):
            score -= 6 if pair_weight(program, "separate", x, y) == MUST_PAIR_WEIGHT else 3
    ta, tb = a.primary.type, b.primary.type
    score += IMPLICIT_AFFINITY.get(frozenset({ta, tb}), 0)
    score += guidance.affinity(ta, tb) - guidance.separation(ta, tb)
    return score


def order_units(
    units: list[Unit],
    program: Program,
    rng: random.Random,
    guidance: PatternGuidance = NO_GUIDANCE,
) -> list[Unit]:
    if len(units) <= 1:
        return list(units)

    def aff(x: Unit, y: Unit) -> float:
        return _affinity(x, y, program, guidance)

    pool = sorted(units, key=lambda u: u.primary.key)
    rng.shuffle(pool)
    totals = {u.primary.key: sum(aff(u, v) for v in pool if v is not u) for u in pool}
    start = max(pool, key=lambda u: totals[u.primary.key])
    chain = [start]
    pool.remove(start)
    while pool:
        best = max(pool, key=lambda u: max(aff(u, chain[0]), aff(u, chain[-1])))
        pool.remove(best)
        if aff(best, chain[0]) > aff(best, chain[-1]):
            chain.insert(0, best)
        else:
            chain.append(best)
    if rng.random() < 0.5:
        chain.reverse()
    return chain


# --- widths -----------------------------------------------------------------------------------


@dataclass
class _Part:
    column: Column
    natural: float
    minimum: float
    fixed: bool
    flex: float = 1.0  # share of surplus/deficit width it takes (service rooms stay near size)
    area: tuple[float, float] = (0.0, 0.0)  # (target, minimum) area the column must hold


def _grid_units(v: float, grid: float) -> int:
    return round(v / grid)


def door_reach(room: RoomRequest, config: LayoutConfig) -> float:
    """Corridor contact a room needs for its door: the door plus a margin on each side (where
    a corridor ends inside a room's width, V1.2)."""
    door = config.wet_room_door if room.type in WET else config.interior_door
    return snap_up(door[0] + 2 * config.door_margin, config.grid)


def frontage(room: RoomRequest, config: LayoutConfig) -> float:
    """Minimum width of a room's corridor side: its door plus a margin on each side."""
    door = config.wet_room_door if room.type in WET else config.interior_door
    return max(room.min_width, door[0] + 2 * config.door_margin)


def layout_strip(strip: Strip, units: list[Unit], config: LayoutConfig) -> StripLayout | None:
    """Columns with widths for `units` in order, filling the strip exactly. None = infeasible.

    Attached service rooms are tucked against the corridor where possible; if the strip is too
    short for that, they become narrow full-depth columns next to their room instead. Where the
    band allows it (the L wing), its last room wraps across the end of the corridor beside it
    whenever it is wide enough to (V1.2): less corridor for the same rooms."""
    wraps = (True, False) if strip.end_wrap_depth > EPS else (False,)
    for allow_tucks in (True, False):
        for wrap in wraps:
            lay = _layout_strip(strip, units, config, allow_tucks=allow_tucks, wrap=wrap)
            if lay is not None:
                return lay
    return None


def _layout_strip(
    strip: Strip, units: list[Unit], config: LayoutConfig, *, allow_tucks: bool, wrap: bool
) -> StripLayout | None:
    d = strip.depth
    g = config.grid
    parts: list[_Part] = []
    for i_unit, u in enumerate(units):
        prim = u.primary
        if prim.min_width > d + EPS:
            return None
        tucks: list[Column] = []
        fulls: list[RoomRequest] = []
        for a in u.attached:
            width = max(config.tuck_widths.get(a.type, a.min_width), a.min_width)
            width = snap_up(width, g)
            depth = snap_up(max(a.target_area / width, a.min_width), g)
            if allow_tucks and len(tucks) < 2 and d - depth >= config.remainder_min_depth - EPS:
                tucks.append(Column("tuck", a, width, depth, owner=prim))
            else:
                fulls.append(a)
        remainder = sum(t.width * (d - t.depth) for t in tucks)
        main_natural = max((prim.target_area - remainder) / d, 0.0)
        main = _Part(
            Column("main", prim, 0.0, d),
            main_natural,
            max(frontage(prim, config), (prim.min_area - remainder) / d),  # rules minimum area
            False,
            0.2 if prim.tuckable else 1.0,
            (prim.target_area - remainder, prim.min_area - remainder),
        )
        seq: list[_Part] = []
        # Tucks flank the room; when the band's last room wraps, both go before it (the room
        # still wraps round them on the facade side) so the band does not end in a tuck.
        before = 2 if wrap and i_unit == len(units) - 1 else 1
        for t in tucks[:before]:
            seq.append(_Part(t, t.width, t.width, True))
        seq.append(main)
        for t in tucks[before:]:
            seq.append(_Part(t, t.width, t.width, True))
        for a in fulls:
            if a.min_width > d + EPS:
                return None
            seq.append(
                _Part(
                    Column("full", a, 0.0, d),
                    a.target_area / d,
                    max(frontage(a, config), a.min_area / d),
                    False,
                    0.2,
                    (a.target_area, a.min_area),
                )
            )
        parts.extend(seq)

    wrap_from = 0.0
    if wrap:
        # The band's last room wraps across the corridor beside the band's end: the corridor
        # stops a door's reach (door_reach) into the room, and the room takes the rest of
        # the corridor's width there. Same area in a shorter column. A tucked room cannot.
        last = parts[-1] if parts else None
        if last is None or last.fixed:
            return None
        room, e = last.column.room, strip.end_wrap_depth
        wrap_from = door_reach(room, config)
        target, minimum = last.area
        last.natural = max((target + wrap_from * e) / (d + e), 0.0)
        last.minimum = max(
            frontage(room, config),
            wrap_from + config.remainder_min_depth,
            (minimum + wrap_from * e) / (d + e),
        )

    total_units = _grid_units(strip.length, g)
    fixed = sum(_grid_units(p.natural, g) for p in parts if p.fixed)
    # Parts are identified by their position in the strip (never by object identity: that
    # would make tie-breaking depend on memory addresses and break determinism).
    scalable = [i for i, p in enumerate(parts) if not p.fixed]
    if not scalable:
        return None
    min_units = {i: math.ceil(parts[i].minimum / g - 1e-9) for i in scalable}
    available = total_units - fixed
    if sum(min_units.values()) > available:
        return None
    # Distribute surplus/deficit by flex weight, honouring minimums (water-filling), then round
    # to integer grid units. Natural widths are converted to grid units first.
    widths: dict[int, float] = {}
    free = list(scalable)
    budget = float(available)
    while free:
        nat = sum(parts[i].natural / g for i in free)
        weight = sum(parts[i].natural / g * parts[i].flex for i in free)
        delta = budget - nat
        trial = {
            i: (
                parts[i].natural / g + delta * (parts[i].natural / g * parts[i].flex) / weight
                if weight > EPS
                else budget / len(free)
            )
            for i in free
        }
        clamped = [i for i in free if trial[i] < min_units[i]]
        if not clamped:
            widths.update(trial)
            break
        for i in clamped:
            widths[i] = float(min_units[i])
            budget -= min_units[i]
            free.remove(i)
    ints = {i: max(min_units[i], math.floor(v + 1e-9)) for i, v in widths.items()}
    diff = available - sum(ints.values())
    ranked = sorted(scalable, key=lambda i: (-(widths[i] - math.floor(widths[i])), i))
    step = 0
    while diff > 0 and ranked:
        ints[ranked[step % len(ranked)]] += 1
        diff -= 1
        step += 1
    while diff < 0:
        i = max(scalable, key=lambda i: (ints[i] - min_units[i], -i))
        if ints[i] <= min_units[i]:
            return None
        ints[i] -= 1
        diff += 1
    columns = []
    for i, p in enumerate(parts):
        if not p.fixed:
            p.column.width = rnd(ints[i] * g)
        columns.append(p.column)
    return StripLayout(strip, columns, wrap_from)


def strip_areas(layout: StripLayout) -> dict[str, float]:
    areas: dict[str, float] = {}
    d = layout.strip.depth
    for c in layout.columns:
        if c.kind == "tuck" and c.owner is not None:
            areas[c.room.key] = c.width * c.depth
            areas[c.owner.key] = areas.get(c.owner.key, 0.0) + c.width * (d - c.depth)
        else:
            areas[c.room.key] = areas.get(c.room.key, 0.0) + c.width * d
    if layout.wrap_from > 0.0:  # the last room's part across the corridor's end
        last = layout.columns[-1]
        extra = (last.width - layout.wrap_from) * layout.strip.end_wrap_depth
        areas[last.room.key] = areas.get(last.room.key, 0.0) + extra
    return areas


# --- scoring ----------------------------------------------------------------------------------


def _aspect_penalty(layout: StripLayout) -> float:
    d = layout.strip.depth
    penalty = 0.0
    widths: dict[str, float] = {}
    for c in layout.columns:
        if c.kind == "tuck":
            owner = c.owner.key if c.owner else c.room.key
            widths[owner] = widths.get(owner, 0.0) + c.width
            dims = (c.width, c.depth)
            limit = ASPECT_LIMIT["service"]
            penalty += max(0.0, max(dims) / min(dims) - limit)
        else:
            widths[c.room.key] = widths.get(c.room.key, 0.0) + c.width
    wrapped = layout.columns[-1].room.key if layout.wrap_from > 0.0 else None
    for c in layout.columns:
        if c.kind == "tuck":
            continue
        w = widths[c.room.key]
        depth = d + layout.strip.end_wrap_depth if c.room.key == wrapped else d
        ratio = max(w, depth) / max(min(w, depth), EPS)
        limit = ASPECT_LIMIT["service" if c.room.tuckable else "habitable"]
        penalty += max(0.0, ratio - limit)
    return penalty


CROSS_CORRIDOR_MIN = 1.5


def _neighbours(layouts: Sequence[StripLayout]) -> tuple[set[frozenset[str]], set[frozenset[str]]]:
    """Room pairs next to each other in a band, and pairs facing each other across the
    corridor (overlapping by at least CROSS_CORRIDOR_MIN)."""
    pairs: set[frozenset[str]] = set()
    spans: list[tuple[str, str, float, float]] = []  # side, key, x0, x1 (corridor-facing part)
    for lay in layouts:
        owners = [c.owner.key if c.kind == "tuck" and c.owner else c.room.key for c in lay.columns]
        keys = [c.room.key for c in lay.columns]
        for i in range(len(keys) - 1):
            pairs.add(frozenset({keys[i], keys[i + 1]}))
            pairs.add(frozenset({owners[i], owners[i + 1]}))
        x = lay.strip.x0
        for c in lay.columns:
            if c.kind != "tuck":
                spans.append((lay.strip.side, c.room.key, x, x + c.width))
            x += c.width
    across: set[frozenset[str]] = set()
    for side_a, ka, a0, a1 in spans:
        for side_b, kb, b0, b1 in spans:
            if (
                side_a == "south"
                and side_b == "north"
                and min(a1, b1) - max(a0, b0) >= (CROSS_CORRIDOR_MIN - 1e-6)
            ):
                across.add(frozenset({ka, kb}))
    return pairs, across


def _level_neighbours(lvl: LevelLayout) -> tuple[set[frozenset[str]], set[frozenset[str]]]:
    """_neighbours of a level, plus the rooms joined where a corridor dead end was cut."""
    pairs, across = _neighbours(lvl.strips)
    return pairs | {frozenset(cut.joins) for cut in lvl.cuts}, across


def unmet_pairs(levels: Sequence[LevelLayout], program: Program) -> list[tuple[str, str, str]]:
    """(kind, a, b) for wished pairs the plan does not satisfy; kind is "adjacent"/"open"."""
    pairs: set[frozenset[str]] = set()
    across: set[frozenset[str]] = set()
    for lvl in levels:
        level_pairs, level_across = _level_neighbours(lvl)
        pairs |= level_pairs
        across |= level_across
    out = []
    for kind, wanted in (("adjacent", program.adjacency), ("open", program.open_plan)):
        ok_pairs = pairs | across if kind == "open" else pairs
        for a, b in wanted:
            if not any(
                frozenset({x.key, y.key}) in ok_pairs
                for x in program.instances(a)
                for y in program.instances(b)
            ):
                out.append((kind, a, b))
    return out


def _separation_penalty(levels: Sequence[LevelLayout], program: Program, zoning: Zoning) -> float:
    """Spec separations broken (neighbours in a band), and pattern type pairs: separations
    broken and affinities missed (per level, only where both room types are on the level)."""
    guidance = zoning.guidance
    penalty = 0.0
    rooms = program.by_key()
    for lvl in levels:
        pairs, _ = _level_neighbours(lvl)
        for a, b, weight in zoning.apart:
            if any(frozenset({x, y}) in pairs for x in sorted(a) for y in sorted(b)):
                penalty += weight
        if not guidance.affinities and not guidance.separations:
            continue
        on_level = {c.room.key for lay in lvl.strips for c in lay.columns}
        types = {rooms[k].type for k in on_level if k in rooms}
        met: set[frozenset[RoomType]] = set()
        for pair in pairs:
            ks = sorted(k for k in pair if k in rooms)
            if len(ks) == 2:
                ta, tb = rooms[ks[0]].type, rooms[ks[1]].type
                met.add(frozenset({ta, tb}))
                penalty += PATTERN_PAIR_SCALE * guidance.separation(ta, tb)
        for pair_types, weight in guidance.affinities.items():
            if len(pair_types) == 2 and pair_types <= types and pair_types not in met:
                penalty += PATTERN_PAIR_SCALE * weight
    return penalty


def score_candidate(
    levels: list[LevelLayout],
    program: Program,
    sk: Skeleton,
    target_floor_area: float,
    zoning: Zoning,
    wing_ratio: tuple[float, float] | None = None,
) -> tuple[float, dict[str, float]]:
    areas: dict[str, float] = {}
    penalty = 0.0
    for lvl in levels:
        for lay in lvl.strips:
            areas.update(strip_areas(lay))
            penalty += 0.4 * _aspect_penalty(lay)
            for c in lay.columns:
                if c.kind != "tuck":
                    penalty += _strip_pref(
                        Unit(c.room), lay.strip, lvl.index, zoning.wishes, zoning.guidance
                    )
        # Street-side strips left empty become landing/hall space: wasted area.
        penalty += sum(1.0 + 0.1 * s.length * s.depth for s in lvl.merged_strips)
        for cut in lvl.cuts:
            areas[cut.owner] = areas.get(cut.owner, 0.0) + cut.length * sk.C
    for r in program.rooms:
        actual = areas.get(r.key, 0.0)
        weight = 2.0 if r.explicit_target else 1.0
        deviation = abs(actual - r.target_area) / r.target_area
        # Quadratic term: spread unavoidable surplus over many rooms, not into one.
        penalty += weight * (deviation + 1.5 * deviation**2)
        if actual + 1e-6 < r.min_area:
            penalty += 5
        if r.area_low is not None and r.area_high is not None:
            outside = max(r.area_low - actual, actual - r.area_high, 0.0) / r.target_area
            if outside > 1e-6:
                penalty += AREA_RANGE_WEIGHT * outside + (AREA_MUST_PENALTY if r.area_must else 0)
    for kind, a, b in unmet_pairs(levels, program):
        penalty += pair_weight(program, kind, a, b)
    penalty += _separation_penalty(levels, program, zoning)
    aspect = sk.W / sk.D
    penalty += 0.5 * max(0.0, aspect - 2.0) + 0.8 * max(0.0, 1 / aspect - 1.1)
    if zoning.guidance.aspect is not None:
        low, high = zoning.guidance.aspect
        penalty += PATTERN_ASPECT_WEIGHT * max(0.0, low - aspect, aspect - high)
    if sk.has_wing and wing_ratio is not None:  # wing length relative to the main bar
        low, high = wing_ratio
        ratio = sk.wing_length / sk.W
        penalty += L_WING_RATIO_WEIGHT * max(0.0, low - ratio, ratio - high)
    if sk.has_wing:  # corridor + gallery share of the floor area (varies a lot between shapes)
        penalty += L_CIRCULATION_WEIGHT * l_circulation_area(sk, levels[0]) / sk.footprint_area
    gfa = sk.footprint_area * sk.storeys
    penalty += 6 * abs(gfa - target_floor_area) / target_floor_area
    return penalty, areas


# --- L plans: corridor ends (V1.2) --------------------------------------------------------------


def l_circulation_area(sk: Skeleton, level: LevelLayout) -> float:
    """Ground-floor circulation of an L plan: main corridor less its cut ends, the gallery up
    to where the wing's last room takes it over, the entrance hall and empty street strips."""
    corridor = (sk.W - sum(c.length for c in level.cuts)) * sk.C
    wing = next((lay for lay in level.strips if lay.strip.side == "wing"), None)
    if wing is not None:
        corridor += max(0.0, wing.corridor_end - (sk.Ds + sk.C)) * sk.C
    hall = (sk.group_x1 - sk.group_x0) * sk.Ds
    return corridor + hall + sum(s.length * s.depth for s in level.merged_strips)


def _spans(lay: StripLayout) -> list[tuple[Column, float, float]]:
    """Columns of a band along x with their x-range."""
    out = []
    x = lay.strip.x0
    for c in lay.columns:
        out.append((c, x, rnd(x + c.width)))
        x = rnd(x + c.width)
    return out


def _cut_owner(a: RoomRequest, b: RoomRequest, areas: dict[str, float]) -> RoomRequest:
    """The room that takes a corridor end: the one further below its target area (ties: `a`)."""

    def deficit(r: RoomRequest) -> float:
        return (r.target_area - areas.get(r.key, 0.0)) / r.target_area

    return b if deficit(b) > deficit(a) + 1e-9 else a


def _joinable(a: RoomRequest, b: RoomRequest, zoning: Zoning) -> bool:
    """Whether two rooms may come to share a wall where a corridor end is cut: never rooms the
    spec keeps apart, never a bedroom or study with a living space (privacy)."""
    for ga, gb, _ in zoning.apart:
        if (a.key in ga and b.key in gb) or (a.key in gb and b.key in ga):
            return False
    types = {a.type, b.type}
    return not (types & PRIVATE and types & PUBLIC)


def service_first_in_t_wing(sk: Skeleton, ordered: dict[str, list[Unit]]) -> None:
    """A T's wing band starts inside the main bar, where a room has no outside wall
    (_t_wing_rooms_lit): put a service room there - the first unit that is a service room or
    starts with a tucked one (a bedroom with its bathroom against the gallery); when the wing
    has none, the first such unit of the other bands (by name) moves into the wing.
    Deterministic."""
    if sk.topology != "t" or "WG" not in ordered:
        return
    units = ordered["WG"]

    def service(u: Unit) -> bool:
        return u.primary.tuckable or bool(u.attached)

    first = next((u for u in units if service(u)), None)
    if first is None:
        for name in sorted(n for n in ordered if n != "WG"):
            first = next((u for u in ordered[name] if service(u)), None)
            if first is not None and len(ordered[name]) > 1:
                ordered[name].remove(first)
                break
            first = None
        if first is None:
            return
    else:
        units.remove(first)
    units.insert(0, first)


def _t_wing_rooms_lit(sk: Skeleton, layouts: list[StripLayout], config: LayoutConfig) -> bool:
    """A T's wing starts inside the main bar (from the corridor to the garden facade, between
    the two garden bands): a room there has no outside wall. Habitable rooms of the wing band
    must reach at least t_min_wing_facade beyond the garden facade (to the wing's own walls);
    service rooms may stay inside. (An L's wing band lies on the main bar's outer wall.)"""
    if sk.topology != "t":
        return True
    wing = next((lay for lay in layouts if lay.strip.side == "wing"), None)
    if wing is None:
        return True
    y = wing.strip.start
    for col in wing.columns:
        y1 = y + col.width
        if (
            col.kind != "tuck"
            and col.room.type in HABITABLE_TYPES
            and y1 < sk.D + config.t_min_wing_facade - EPS
        ):
            return False
        y = y1
    return True


def corridor_cuts(
    sk: Skeleton, layouts: list[StripLayout], zoning: Zoning, config: LayoutConfig
) -> list[CorridorCut]:
    """Dead ends of an L's or T's main corridor given to the rooms beside them (V1.2).

    Far end (an L: opposite the wing; a T: both ends): the corridor stops a door's reach
    (door_reach) into the last garden-side and street-side rooms; one of them takes the rest
    of the corridor's width, so the two share a wall there (e.g. kitchen and dining). Near
    end (under an L's wing): the stub beyond the gallery stops a door's reach into the first
    street-side room; that room or the
    wing's first room takes the stub. The taker is the room further below its target area.
    Kept: a corridor end with the garage door, beside the hall or beside a tucked room; ends
    shorter than remainder_min_depth; joins _joinable forbids."""
    if not sk.has_wing:
        return []
    g, minimum = config.grid, config.remainder_min_depth
    north = [sp for lay in layouts if lay.strip.side == "north" for sp in _spans(lay)]
    south = [sp for lay in layouts if lay.strip.side == "south" for sp in _spans(lay)]
    wing = next((lay for lay in layouts if lay.strip.side == "wing"), None)
    areas: dict[str, float] = {}
    for lay in layouts:
        areas.update(strip_areas(lay))
    far_east = sk.wing_side == "west"

    def at(
        spans: list[tuple[Column, float, float]], x: float
    ) -> tuple[Column, float, float] | None:
        hit = [sp for sp in spans if abs((sp[2] if x > 0 else sp[1]) - x) < EPS]
        return hit[0] if hit and hit[0][0].kind != "tuck" else None

    cuts: list[CorridorCut] = []
    for east in [far_east] if sk.is_l else [False, True]:  # a T: both ends are far ends
        far_x = sk.W if east else 0.0
        garage_far = sk.garage_side == ("east" if east else "west")
        n_end, s_end = at(north, far_x), at(south, far_x)
        if garage_far or n_end is None or s_end is None:
            continue
        (cn, n0, n1), (cs, s0, s1) = n_end, s_end
        fn, fs = door_reach(cn.room, config), door_reach(cs.room, config)
        if east:
            x0, x1 = snap_up(max(n0 + fn, s0 + fs), g), sk.W
        else:
            x0, x1 = 0.0, snap_down(min(n1 - fn, s1 - fs), g)
        if x1 - x0 >= minimum - EPS and _joinable(cn.room, cs.room, zoning):
            owner = _cut_owner(cn.room, cs.room, areas)
            cuts.append(CorridorCut(x0, x1, owner.key, (cn.room.key, cs.room.key)))
    if not sk.is_l:  # (the T's wing stands in the middle: no stub beyond its gallery)
        return cuts
    first = wing.columns[0] if wing is not None and wing.columns else None
    near_x = 0.0 if far_east else sk.W
    s_near = at(south, near_x)
    garage_near = sk.garage_side == ("west" if far_east else "east")
    if not garage_near and first is not None and first.kind != "tuck" and s_near is not None:
        cs, s0, s1 = s_near
        fs = door_reach(cs.room, config)
        if far_east:
            x0, x1 = 0.0, snap_down(min(sk.wing_depth, s1 - fs), g)
        else:
            x0, x1 = snap_up(max(sk.W - sk.wing_depth, s0 + fs), g), sk.W
        if x1 - x0 >= minimum - EPS and _joinable(cs.room, first.room, zoning):
            owner = _cut_owner(cs.room, first.room, areas)
            cuts.append(CorridorCut(rnd(x0), rnd(x1), owner.key, (cs.room.key, first.room.key)))
    return cuts


def align_far_end(
    sk: Skeleton,
    ordered: dict[str, list[Unit]],
    strips: list[Strip],
    program: Program,
    zoning: Zoning,
) -> None:
    """L and T plans (V1.2): when wished neighbours ended up on opposite sides of the main
    corridor (one garden-side, one street-side), put both at the corridor's far end (an L:
    opposite the wing; a T: its east end), where corridor_cuts joins the last rooms of the two
    bands. Spec pairs first (by weight), then the implicit kitchen-dining / dining-living
    affinity. Deterministic; changes order only."""
    if not sk.has_wing:
        return
    far_east = sk.wing_side == "west" if sk.is_l else True
    far_x = sk.W if far_east else 0.0
    by_name: dict[str, Strip] = {s.name: s for s in strips}

    def at_far_end(side: str) -> str | None:
        return next(
            (
                n
                for n in ordered
                if by_name[n].side == side
                and abs((by_name[n].x1 if far_east else by_name[n].x0) - far_x) < EPS
            ),
            None,
        )

    north_name, south_name = at_far_end("north"), at_far_end("south")
    if north_name is None or south_name is None:
        return
    rooms = program.by_key()
    wanted: list[tuple[float, frozenset[str], frozenset[str]]] = [
        (w, a, b) for a, b, w in zoning.pairs
    ]
    for pair, weight in IMPLICIT_AFFINITY.items():
        types = sorted(pair)
        if len(types) == 2:
            ka = frozenset(k for k, r in rooms.items() if r.type == types[0])
            kb = frozenset(k for k, r in rooms.items() if r.type == types[1])
            wanted.append((weight * 0.5, ka, kb))
    wanted.sort(key=lambda t: (-t[0], sorted(t[1]), sorted(t[2])))

    def unit_of(name: str, keys: frozenset[str]) -> Unit | None:
        return next((u for u in ordered[name] if u.primary.key in keys), None)

    for _, a, b in wanted:
        for ka, kb in ((a, b), (b, a)):
            un, us = unit_of(north_name, ka), unit_of(south_name, kb)
            if un is None or us is None:
                continue
            for name, unit in ((north_name, un), (south_name, us)):
                ordered[name].remove(unit)
                if far_east:
                    ordered[name].append(unit)
                else:
                    ordered[name].insert(0, unit)
            return


# --- search -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchInput:
    spec: BuildingSpecification
    program: Program
    levels: dict[str, int]
    stair: StairDesign | None
    floor_area_per_storey: float
    max_width: float | None
    max_depth: float | None
    garage_width: float
    garage_depth: float
    landing_depth: float
    wishes: dict[str, str]  # room key -> facade side it must reach
    guidance: PatternGuidance = NO_GUIDANCE  # applicable layout patterns (soft)
    # Footprint topologies to search (layout/topology.py): "rect" and/or "l".
    topologies: tuple[str, ...] = ("rect",)


def skeletons(inp: SearchInput, config: LayoutConfig, reasons: list[str]) -> list[Skeleton]:
    spec = inp.spec
    storeys = spec.targets.storeys
    g = config.grid
    area = inp.floor_area_per_storey
    lanes = storeys - 1
    lane_w = inp.stair.lane_width if inp.stair else 0.0
    core_w = lanes * lane_w
    hall_widths = [config.entrance_hall_width]
    if area < 90:  # small floor plates: a compact hall leaves room for a street-side room
        hall_widths.append(config.compact_hall_width)
    t_ext = config.exterior_wall_thickness
    ds_min = config.min_band_depth
    if inp.stair is not None:
        ds_min = max(
            ds_min,
            snap_up(t_ext / 2 + inp.stair.run + inp.landing_depth, g),
        )
    out: list[Skeleton] = []
    seen: set[tuple[float, ...]] = set()
    for aspect, scale in itertools.product(config.footprint_aspects, config.footprint_area_scales):
        width = snap(math.sqrt(area * scale * aspect), g)
        depth = snap(area * scale / width, g)
        if inp.max_width is not None and width + inp.garage_width > inp.max_width + EPS:
            reasons.append("footprint wider than the plot allows")
            continue
        if inp.max_depth is not None and depth > inp.max_depth + EPS:
            reasons.append("footprint deeper than the plot allows")
            continue
        corridor = config.corridor_width
        balanced = (depth - corridor) / 2
        options = sorted(
            {max(ds_min, snap(balanced + off, g)) for off in config.band_split_offsets}
        )
        for ds, hall_w in itertools.product(options, hall_widths):
            if depth - ds - corridor < config.min_band_depth - EPS:
                reasons.append("footprint too shallow for two room bands and a corridor")
                continue
            group = hall_w + core_w
            if group > width - EPS:
                reasons.append("footprint too narrow for the entrance hall and stair core")
                continue
            for frac in config.core_positions:
                sides: tuple[Literal["west", "east"], ...] = ("west", "east")
                for hall_side in sides:
                    if lanes == 0 and hall_side == "east":
                        continue
                    lane, w_eff = lane_w, width
                    gx0, hall, core_x0 = _place_group(
                        width, hall_w, lanes, lane, frac, hall_side, g
                    )
                    key = (width, depth, ds, gx0, hall_w, 0.0 if hall_side == "west" else 1.0)
                    if key in seen:
                        continue
                    seen.add(key)
                    if lanes and (core_x0 < EPS or core_x0 + lanes * lane > width - EPS):
                        # The core is on the facade, so that side of its lanes is the (thicker)
                        # exterior wall. Widen the lanes, and the footprint by as much, so every
                        # flight keeps its clearance and the rooms keep their width (K2.5). If
                        # the plot does not allow it, the skeleton stays as it is and the search
                        # rejects it (flights_fit_lanes); it is never dropped here, which would
                        # shift the seeds of the skeletons after it.
                        wide = snap_up(lane_w + (t_ext - config.interior_wall_thickness) / 2, g)
                        grown = rnd(width + lanes * (wide - lane_w))
                        if inp.max_width is None or grown + inp.garage_width <= inp.max_width + EPS:
                            lane, w_eff = wide, grown
                            gx0, hall, core_x0 = _place_group(
                                w_eff, hall_w, lanes, lane, frac, hall_side, g
                            )
                    garage_side: Literal["west", "east"] | None = None
                    if spec.features.garage is not None:
                        middle = gx0 + (hall_w + lanes * lane) / 2
                        garage_side = "west" if middle <= w_eff / 2 else "east"
                    out.append(
                        Skeleton(
                            W=w_eff,
                            D=depth,
                            Ds=ds,
                            C=corridor,
                            storeys=storeys,
                            core_x0=core_x0,
                            lanes=lanes,
                            lane_width=lane,
                            hall_x0=hall[0],
                            hall_x1=hall[1],
                            hall_side=hall_side,
                            garage_side=garage_side,
                        )
                    )
    return out


def garden_demands(inp: SearchInput) -> list[float]:
    """Room area an L's garden band should hold (V1.2, docs/3d-engine.md §16.10), smallest
    first: the living spaces and the rooms the user wants on the garden facade (rooms[].faces,
    terrace hosts), with the dining room when a garden connection is a priority; then also the
    dining room. The kitchen is not counted: it can meet the dining room where the corridor
    ends (corridor_cuts), so it need not take garden frontage."""
    rooms = inp.program.rooms
    core = {r.key for r in rooms if r.type in GARDEN_LIVING or inp.wishes.get(r.key) == "north"}
    if DesignPriority.GARDEN_CONNECTION in inp.spec.design.priorities:
        core |= {r.key for r in rooms if r.type == RoomType.DINING}
    tiers = [core, core | {r.key for r in rooms if r.type == RoomType.DINING}]
    demands = {rnd(sum(r.target_area for r in rooms if r.key in tier)) for tier in tiers if tier}
    return sorted(demands)


def _garden_split(
    width: float, depth: float, demand: float, config: LayoutConfig
) -> tuple[float, float] | None:
    """(street band depth, wing room depth) of an L whose garden band holds `demand`.

    The wing's rooms are as deep as the street band (both hold bedrooms), so a garden band of
    depth Dn has W - (D - Dn) of facade: Dn^2 + (W - D) Dn = demand. Dn stays between
    min_band_depth and l_garden_band_max_depth and leaves the street band min_band_depth."""
    g, corridor = config.grid, config.corridor_width
    root = (-(width - depth) + math.sqrt((width - depth) ** 2 + 4 * demand)) / 2
    high = min(config.l_garden_band_max_depth, depth - corridor - config.min_band_depth)
    dn = min(snap_up(root, g), snap(high, g))
    if dn < config.min_band_depth - EPS:
        return None
    ds = rnd(depth - corridor - dn)
    return ds, ds


BarFamily = Literal["ratio", "depth"]


def l_skeletons(
    inp: SearchInput, config: LayoutConfig, reasons: list[str], family: BarFamily = "ratio"
) -> list[Skeleton]:
    """L-shaped single-storey skeletons (docs/3d-engine.md §16.10): the wing at a main-bar end."""
    return _wing_skeletons(inp, config, reasons, "l", family)


def t_skeletons(
    inp: SearchInput, config: LayoutConfig, reasons: list[str], family: BarFamily = "ratio"
) -> list[Skeleton]:
    """T-shaped single-storey skeletons (docs/3d-engine.md §16.12): the wing (the T's stem)
    from the middle of the main bar's garden facade, garden bands on both sides of it."""
    return _wing_skeletons(inp, config, reasons, "t", family)


def _wing_skeletons(
    inp: SearchInput,
    config: LayoutConfig,
    reasons: list[str],
    topology: Literal["l", "t"],
    family: BarFamily = "ratio",
) -> list[Skeleton]:
    """Skeletons of a main bar plus one wing (L or T), single storey.

    Main bar: the double-loaded rectangle W x D (street band, corridor, garden band) holding
    `1 - share` of the floor area. Wing: `share` of the floor area beyond the main bar's
    garden facade - L: at its west or east end, rooms on the outer side; T: centred, rooms on
    its west or east half - a band of rooms (`wing_depth`) beside a gallery corridor (C) that
    continues the main corridor.

    Main bars, by `family`: "ratio" bars (config.l_main_aspects x l_wing_area_shares), or
    (V1.3) "depth" bars - the main bar's depth taken from the bands it must hold
    (2 x min_band_depth + C, plus config.l_depth_steps) and its width from the area (shares
    config.l_depth_bar_shares), for small or long houses whose ratio bars are too shallow or
    too wide. search() uses the depth family only for a topology the ratio family gives no
    feasible layout for, so established results never change. Band splits per bar:
    config.l_band_split_offsets around an even
    split (wing rooms as deep as the garden band), then (V1.2) splits sized so the garden band
    holds the rooms that belong on the garden side (garden_demands; wing rooms as deep as the
    street band). Limits: l_wing_min_length (the wing must reach beyond the main bar),
    l_min_garden_frontage (L: garden facade beside the wing) / t_min_side_frontage (T: on each
    side of the wing)."""
    spec = inp.spec
    label = "an L-shaped" if topology == "l" else "a T-shaped"
    if spec.targets.storeys != 1:
        reasons.append(f"{label} footprint is only generated for single-storey houses")
        return []
    g, area, corridor = config.grid, inp.floor_area_per_storey, config.corridor_width
    hall_widths = [config.entrance_hall_width]
    if area < 90:
        hall_widths.append(config.compact_hall_width)
    out: list[Skeleton] = []
    seen: set[tuple[object, ...]] = set()
    demands = garden_demands(inp)

    def fits_plot(width: float) -> bool:
        if inp.max_width is not None and width + inp.garage_width > inp.max_width + EPS:
            reasons.append(f"{label} footprint is wider than the plot allows")
            return False
        return True

    ratio_bars: list[tuple[float, float, float]] = []
    aspects = config.l_main_aspects if topology == "l" else config.t_main_aspects
    for aspect, share in itertools.product(aspects, config.l_wing_area_shares):
        main_area = area * (1 - share)
        width = snap(math.sqrt(main_area * aspect), g)
        depth = snap(main_area / width, g)
        if fits_plot(width):
            ratio_bars.append((width, depth, share))
    depth_bars: list[tuple[float, float, float]] = []
    shallowest = 2 * config.min_band_depth + corridor
    for step, share in itertools.product(config.l_depth_steps, config.l_depth_bar_shares):
        depth = snap_up(shallowest + step, g)
        width = snap(area * (1 - share) / depth, g)
        if width < depth - EPS:
            continue  # not a bar any more
        if (width, depth, share) not in ratio_bars and fits_plot(width):
            depth_bars.append((width, depth, share))

    def offset_splits(width: float, depth: float) -> list[tuple[float, float]]:
        balanced = (depth - corridor) / 2
        splits = []
        for off in config.l_band_split_offsets:
            ds = max(config.min_band_depth, snap(balanced + off, g))
            splits.append((ds, rnd(depth - ds - corridor)))  # wing as deep as the garden band
        return splits

    def garden_splits(width: float, depth: float) -> list[tuple[float, float]]:
        splits = [_garden_split(width, depth, d, config) for d in demands]
        return [s for s in splits if s is not None]

    for bars in [ratio_bars] if family == "ratio" else [depth_bars]:
        for make_splits in (offset_splits, garden_splits):
            for width, depth, share in bars:
                for ds, wing_depth in make_splits(width, depth):
                    if min(wing_depth, rnd(depth - ds - corridor)) < config.min_band_depth - EPS:
                        reasons.append(f"{label} footprint is too shallow for two bands")
                        continue
                    wing_width = rnd(wing_depth + corridor)
                    wing_length = snap(area * share / wing_width, g)
                    if wing_length < config.l_wing_min_length - EPS:
                        reasons.append(
                            f"{label} footprint's wing would not reach beyond the main bar"
                        )
                        continue
                    wing_x0 = 0.0
                    if topology == "l":
                        if width - wing_width < config.l_min_garden_frontage - EPS:
                            reasons.append(
                                f"{label} footprint's wing would leave too little garden facade"
                            )
                            continue
                    else:
                        wing_x0 = snap((width - wing_width) / 2, g)
                        side_min = min(wing_x0, width - wing_x0 - wing_width)
                        if side_min < config.t_min_side_frontage - EPS:
                            reasons.append(
                                f"{label} footprint's wing would leave too little garden facade "
                                "on one side"
                            )
                            continue
                    if inp.max_depth is not None and depth + wing_length > inp.max_depth + EPS:
                        reasons.append(f"{label} footprint is deeper than the plot allows")
                        continue
                    for hall_w, frac in itertools.product(hall_widths, config.core_positions):
                        if hall_w > width - EPS:
                            continue
                        gx0, hall, core_x0 = _place_group(width, hall_w, 0, 0.0, frac, "west", g)
                        garage_side: Literal["west", "east"] | None = None
                        if spec.features.garage is not None:
                            garage_side = "west" if gx0 + hall_w / 2 <= width / 2 else "east"
                        # L: the wing on either side of the garage (they never meet: the garage
                        # ends before the garden facade), opposite it first (V1.1). T: the
                        # side of the stem its rooms take.
                        sides: tuple[Literal["west", "east"], ...] = (
                            ("east", "west") if garage_side == "west" else ("west", "east")
                        )
                        for side in sides:
                            key = (
                                width,
                                depth,
                                ds,
                                gx0,
                                hall_w,
                                side,
                                wing_length,
                                wing_depth,
                                wing_x0,
                            )
                            if key in seen:
                                continue
                            seen.add(key)
                            out.append(
                                Skeleton(
                                    W=width,
                                    D=depth,
                                    Ds=ds,
                                    C=corridor,
                                    storeys=1,
                                    core_x0=core_x0,
                                    lanes=0,
                                    lane_width=0.0,
                                    hall_x0=hall[0],
                                    hall_x1=hall[1],
                                    hall_side="west",
                                    garage_side=garage_side,
                                    topology=topology,
                                    wing_side=side,
                                    wing_depth=wing_depth,
                                    wing_length=wing_length,
                                    wing_x0=wing_x0,
                                )
                            )
    return out


WING_SKELETONS = {"l": l_skeletons, "t": t_skeletons}


def _place_group(
    width: float,
    hall_w: float,
    lanes: int,
    lane_w: float,
    frac: float,
    hall_side: Literal["west", "east"],
    grid: float,
) -> tuple[float, tuple[float, float], float]:
    """Start of the hall + core group, the hall part and the core start at one position."""
    core_w = lanes * lane_w
    gx0 = snap(frac * (width - hall_w - core_w), grid)
    if hall_side == "west":
        return gx0, (gx0, rnd(gx0 + hall_w)), rnd(gx0 + hall_w)
    return gx0, (rnd(gx0 + core_w), rnd(gx0 + core_w + hall_w)), gx0


def search(inp: SearchInput, config: LayoutConfig, seed: int) -> list[Candidate]:
    """All feasible candidates, best first (deterministic for a given seed)."""
    reasons: list[str] = []
    # Rectangular skeletons first, L skeletons after them: adding the L topology never shifts
    # the seeds (sk_index) of the rectangular candidates.
    sks = skeletons(inp, config, reasons) if "rect" in inp.topologies else []
    for topology in ("l", "t"):  # wing topologies after the rectangles, L before T
        if topology in inp.topologies:
            sks += WING_SKELETONS[topology](inp, config, reasons)
    storeys = inp.spec.targets.storeys
    by_level: list[list[RoomRequest]] = [[] for _ in range(storeys)]
    for r in inp.program.rooms:
        by_level[inp.levels[r.key]].append(r)
    units_by_level = [form_units(rooms, config) for rooms in by_level]
    target = inp.floor_area_per_storey * storeys
    zoning = Zoning.of(inp.program, inp.wishes, inp.guidance)

    candidates: list[Candidate] = []

    def expand(sk_index: int, sk: Skeleton) -> None:
        """The seeded variants of one skeleton that lay out feasibly -> candidates."""
        if inp.stair is not None and not flights_fit_lanes(sk, inp.stair, config):
            # Skipped here, not in skeletons(): sk_index keeps seeding the same variants.
            reasons.append("the stair core against the facade leaves no room for the flight")
            return
        for variant in range(config.variants_per_skeleton):
            # Seeded, local PRNG: the only source of variation (determinism, not security).
            rng = random.Random(f"{seed}:{sk_index}:{variant}")  # noqa: S311
            levels: list[LevelLayout] = []
            ok = True
            for lv in range(storeys):
                strips = level_strips(sk, lv)
                assign = assign_strips(units_by_level[lv], strips, lv, rng, config, zoning)
                if assign is None:
                    ok = False
                    reasons.append(f"floor {lv + 1}: no room bands")
                    break
                layouts: list[StripLayout] = []
                merged: list[Strip] = []
                ordered: dict[str, list[Unit]] = {
                    s.name: order_units(assign[s.name], inp.program, rng, inp.guidance)
                    for s in strips
                    if s.length >= EPS and assign.get(s.name)
                }
                align_far_end(sk, ordered, strips, inp.program, zoning)
                service_first_in_t_wing(sk, ordered)
                for s in strips:
                    if s.length < EPS:
                        continue
                    units = assign.get(s.name, [])
                    if not units:
                        if s.side in ("north", "wing"):
                            ok = False
                            reasons.append(f"floor {lv + 1}: garden-side band left empty")
                            break
                        merged.append(s)
                        continue
                    lay = layout_strip(s, ordered[s.name], config)
                    if lay is None:
                        ok = False
                        band = {"north": "garden-side", "south": "street-side"}.get(s.side, "wing")
                        reasons.append(
                            f"floor {lv + 1}: rooms do not fit the {band} band at their "
                            "minimum widths"
                        )
                        break
                    layouts.append(lay)
                if not ok:
                    break
                if not _t_wing_rooms_lit(sk, layouts, config):
                    ok = False
                    reasons.append(
                        f"floor {lv + 1}: a room in the T's wing would have no outside wall"
                    )
                    break
                cuts = corridor_cuts(sk, layouts, zoning, config)
                levels.append(LevelLayout(lv, layouts, merged, cuts))
            if not ok:
                continue
            score, areas = score_candidate(
                levels, inp.program, sk, target, zoning, config.l_wing_ratio
            )
            candidates.append(Candidate(len(candidates), sk, levels, score, areas))

    for sk_index, sk in enumerate(sks):
        expand(sk_index, sk)
    # V1.3: a wing topology the ratio bars give no feasible layout for (small or long houses,
    # narrow plots) is tried again on depth bars, seeded after everything else.
    next_index = len(sks)
    for topology in ("l", "t"):
        if topology not in inp.topologies:
            continue
        if any(c.skeleton.topology == topology for c in candidates):
            continue
        for sk in WING_SKELETONS[topology](inp, config, reasons, "depth"):
            expand(next_index, sk)
            next_index += 1
    if not candidates:
        summary = sorted(set(reasons), key=lambda r: (-reasons.count(r), r))[:4]
        raise PlanningError("No feasible layout for this specification", summary)
    candidates.sort(key=lambda c: (round(c.score, 9), c.order))
    return candidates
