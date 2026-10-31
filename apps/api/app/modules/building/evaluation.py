"""Design evaluation: how well a generated BuildingModel answers its specification
(Design Intelligence V1, docs/3d-engine.md §16.8).

Read from the built model's geometry (never from the plan the engine intended), so the layout
engine can rank the candidates it built and the report can explain the result:

    requirements   every checkable requirement of the spec (building/intent.py) with its
                   priority, origin and the user's words: met or not, expected vs delivered.
                   MUST requirements are hard: a candidate that misses one is rejected.
    criteria       soft scores in [0, 1] with weights and an explanation each. Weights of the
                   criteria the client prioritised (design.priorities) are raised.

What it does NOT evaluate: structural safety, code/regulatory compliance, acoustics, sun
orientation, cost. Pure and deterministic.
"""

import math
from collections import defaultdict
from typing import Literal

from pydantic import Field
from shapely.geometry import LineString, Polygon
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.modules.building.elements import Door, Room, Wall, Window
from app.modules.building.enums import DoorKind, RelationshipKind, RoomType, WallKind, Zone
from app.modules.building.facades import facade_of_wall
from app.modules.building.footprint import MEASURED_LABELS
from app.modules.building.geometry import wall_axis
from app.modules.building.intent import Requirement, area_range, requirements
from app.modules.building.model import BuildingModel
from app.modules.building.primitives import Frozen
from app.modules.building.specification import (
    BuildingSpecification,
    DesignPriority,
    FacadeSide,
    WindowStyle,
)
from app.modules.building.summary import CIRCULATION, ModelSummary, summarize

# Two rooms are "next to each other" when they share at least this much boundary (enough for
# a door); "apart" when they share less than SEPARATION_TOLERANCE (a corner touch). "Open to"
# needs that much boundary without a wall, directly or facing each other across an open
# corridor stretch (the open-plan arrangement of the double-loaded plan).
ADJACENT_MIN_SHARED = 0.9
SEPARATION_TOLERANCE = 0.05
# Soft-criterion reference values. These are BuildAI evaluation heuristics, not rules: they
# only rank candidates and explain the result.
CIRCULATION_GOOD = 0.15  # share of gross floor area at or below which circulation scores 1
CIRCULATION_POOR = 0.30  # ... at or above which it scores 0
AREA_SCORE_SPAN = 0.25  # relative area deviation at which area accuracy scores 0
HABITABLE_ASPECT_LIMIT = 2.0
COMPACT_RATIO_SPAN = 0.5  # perimeter / (4 sqrt(area)) - 1 at which compactness scores 0
PRIORITY_WEIGHT = 3.0  # weight multiplier of a prioritised criterion

DAY = frozenset({RoomType.LIVING, RoomType.DINING, RoomType.KITCHEN, RoomType.OPEN_KITCHEN_LIVING})
GARDEN_ROOMS = (RoomType.LIVING, RoomType.DINING, RoomType.OPEN_KITCHEN_LIVING)
HABITABLE = DAY | {RoomType.BEDROOM, RoomType.STUDY}
EMPHASIS = (WindowStyle.LARGE, WindowStyle.PANORAMIC)


class RequirementCheck(Frozen):
    path: str  # JSON pointer into the spec
    kind: str
    label: str
    priority: str  # must | should
    origin: str
    quote: str | None
    expected: str
    delivered: str
    met: bool


class CriterionScore(Frozen):
    key: str
    label: str
    score: float = Field(ge=0, le=1)
    weight: float = Field(gt=0)
    explanation: str


class FootprintFacts(Frozen):
    """Shape of the ground floor outline, measured on the model (union of its rooms inside the
    envelope; garage and outdoor rooms excluded)."""

    shape: Literal["rectangular", "l_shape", "t_shape", "u_shape", "courtyard", "other"]
    vertices: int
    reflex_corners: int
    area_m2: float


class DesignEvaluation(Frozen):
    requirements: list[RequirementCheck]
    criteria: list[CriterionScore]
    score: float = Field(ge=0, le=1)  # weighted mean of the criteria
    footprint: FootprintFacts | None = None

    @property
    def hard_ok(self) -> bool:
        return all(r.met for r in self.requirements if r.priority == "must")

    @property
    def unmet_must(self) -> list[RequirementCheck]:
        return [r for r in self.requirements if r.priority == "must" and not r.met]


def grid_outline(room: Room) -> Polygon:
    """A room's outline in plan coordinates on the model's 1 mm grid, for unions (V1.2):
    corners are position + offset sums whose float noise (10.299999999999999 vs 10.3) would
    leave zero-width slits between rooms, counted as extra corners and perimeter."""
    return Polygon(
        [
            (round(room.position.x + p.x, 3), round(room.position.y + p.y, 3))
            for p in room.properties.boundary
        ]
    )


def measure_footprint(model: BuildingModel) -> FootprintFacts:
    """Rectangular = 4 corners; L-shaped = 6 corners with exactly one inside (reflex) corner."""
    if not model.levels:
        return FootprintFacts(shape="other", vertices=0, reflex_corners=0, area_m2=0.0)
    ground = model.levels[0].id
    parts = [
        grid_outline(r)
        for r in model.elements
        if isinstance(r, Room)
        and r.level_id == ground
        and r.properties.room_type != RoomType.GARAGE
        and r.properties.zone != Zone.EXTERIOR
    ]
    shape = unary_union(parts)
    if isinstance(shape, Polygon) and len(shape.interiors) == 1:
        # Rooms all around one enclosed outdoor space: a courtyard house.
        return FootprintFacts(
            shape="courtyard",
            vertices=len(shape.exterior.coords) - 1,
            reflex_corners=0,
            area_m2=round(shape.area, 2),
        )
    if not isinstance(shape, Polygon) or shape.interiors:
        return FootprintFacts(shape="other", vertices=0, reflex_corners=0, area_m2=0.0)
    ring = list(shape.exterior.coords)[:-1]
    if Polygon(ring).exterior.is_ccw is False:
        ring.reverse()
    corners: list[tuple[float, float]] = []
    inside: list[int] = []  # indices (in corners) of the reflex corners
    n = len(ring)
    for i in range(n):
        (ax, ay), (bx, by), (cx, cy) = ring[i - 1], ring[i], ring[(i + 1) % n]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) > 1e-6:
            if cross < 0:
                inside.append(len(corners))
            corners.append((bx, by))
    reflex = len(inside)
    kind: Literal["rectangular", "l_shape", "t_shape", "u_shape", "courtyard", "other"] = (
        "rectangular"
        if len(corners) == 4 and reflex == 0
        else "l_shape"
        if len(corners) == 6 and reflex == 1
        else _eight_corner_shape(corners, inside)
        if len(corners) == 8 and reflex == 2
        else "other"
    )
    return FootprintFacts(
        shape=kind, vertices=len(corners), reflex_corners=reflex, area_m2=round(shape.area, 2)
    )


def _eight_corner_shape(
    corners: list[tuple[float, float]], inside: list[int]
) -> Literal["t_shape", "u_shape", "other"]:
    """8 corners, 2 inside: U when the inside corners are neighbours (the court's back wall
    joins them); T when they lie on one line with the stem's three walls between them; else
    another shape (e.g. a Z)."""
    a, b = inside
    apart = min(b - a, len(corners) - (b - a))
    if apart == 1:
        return "u_shape"
    (ax, ay), (bx, by) = corners[a], corners[b]
    if apart == 3 and (abs(ax - bx) < 1e-6 or abs(ay - by) < 1e-6):
        return "t_shape"
    return "other"


class _Facts:
    """Geometry of the model needed by the checks (computed once)."""

    def __init__(self, model: BuildingModel) -> None:
        self.model = model
        self.rooms: dict[str, Room] = {
            el.semantic_key: el for el in model.elements if isinstance(el, Room) and el.semantic_key
        }
        self.polys: dict[str, Polygon] = {
            key: Polygon([(r.position.x + p.x, r.position.y + p.y) for p in r.properties.boundary])
            for key, r in self.rooms.items()
        }
        self.summary: ModelSummary = summarize(model)
        self.on_facade: dict[str, set[str]] = {
            f: set(keys) for f, keys in self.summary.rooms_on_facade.items()
        }
        self.lit = self._lit_rooms()
        self.footprint = measure_footprint(model)
        self._walls: dict[object, BaseGeometry] = {}

    def facade_lengths(self, facade: FacadeSide) -> dict[str, float]:
        """Room key -> length of its boundary on exterior walls of `facade` (room outlines
        run on the wall axes). Rooms of the house only (no garage, no outdoor rooms); rooms that
        do not reach that facade are left out."""
        lines: dict[object, list[LineString]] = defaultdict(list)
        for w in self.model.elements:
            if (
                isinstance(w, Wall)
                and w.properties.wall_kind == WallKind.EXTERIOR
                and facade_of_wall(w.properties.wall_kind, w.rotation.z) == facade
            ):
                lines[w.level_id].append(LineString(wall_axis(w)))
        zones = {level: unary_union(ls).buffer(1e-3) for level, ls in lines.items()}
        out: dict[str, float] = {}
        for key, poly in self.polys.items():
            zone = zones.get(self.rooms[key].level_id)
            props = self.rooms[key].properties
            if zone is None or props.zone == Zone.EXTERIOR or props.room_type == RoomType.GARAGE:
                continue  # the house's own rooms only
            # The buffer adds about its width at each end of a stretch; 1 cm is far below
            # any facade length that matters here.
            length = float(poly.exterior.intersection(zone).length)
            if length > 0.01:
                out[key] = round(length, 2)
        return out

    def instances(self, spec_key: str) -> list[str]:
        out = []
        for key in sorted(self.rooms):
            name = key.removeprefix("room:")
            suffix = name.removeprefix(spec_key)
            if name.startswith(spec_key) and (
                suffix == "" or (suffix.startswith("_") and suffix[1:].isdigit())
            ):
                out.append(key)
        return out

    def shared(self, a: str, b: str) -> float:
        ra, rb = self.rooms[a], self.rooms[b]
        if ra.level_id != rb.level_id:
            return 0.0
        return float(self.polys[a].exterior.intersection(self.polys[b].exterior).length)

    def _wall_lines(self, level_id: object) -> BaseGeometry:
        if level_id not in self._walls:
            self._walls[level_id] = unary_union(
                [
                    LineString(wall_axis(w)).buffer(1e-3)
                    for w in self.model.elements
                    if isinstance(w, Wall) and w.level_id == level_id
                ]
            )
        return self._walls[level_id]

    def _open_edge(self, a: str, b: str) -> BaseGeometry:
        """Shared boundary of two rooms that carries no wall."""
        shared = self.polys[a].exterior.intersection(self.polys[b].exterior)
        return shared.difference(self._wall_lines(self.rooms[a].level_id))

    def open_connection(self, a: str, b: str) -> float:
        """Length over which `a` and `b` are open to each other: a shared boundary without a
        wall, or open edges to the same circulation room that face each other."""
        if self.rooms[a].level_id != self.rooms[b].level_id:
            return 0.0
        best = float(self._open_edge(a, b).length)
        for c, room in self.rooms.items():
            if (
                room.properties.room_type not in CIRCULATION
                or room.level_id != self.rooms[a].level_id
            ):
                continue
            ea, eb = self._open_edge(a, c), self._open_edge(b, c)
            if ea.length < ADJACENT_MIN_SHARED or eb.length < ADJACENT_MIN_SHARED:
                continue
            ax0, ay0, ax1, ay1 = ea.bounds
            bx0, by0, bx1, by1 = eb.bounds
            along_x = ax1 - ax0 >= ay1 - ay0 and bx1 - bx0 >= by1 - by0
            facing = min(ax1, bx1) - max(ax0, bx0) if along_x else min(ay1, by1) - max(ay0, by0)
            best = max(best, facing)
        return best

    def _lit_rooms(self) -> set[str]:
        """Rooms with at least one window or glazed sliding door on their boundary."""
        walls = {el.id: el for el in self.model.elements if isinstance(el, Wall)}
        lit: set[str] = set()
        for el in self.model.elements:
            if not isinstance(el, (Window, Door)):
                continue
            if isinstance(el, Door) and el.properties.door_kind != DoorKind.SLIDING:
                continue
            host = next(
                (
                    walls.get(r.target_id)
                    for r in el.relationships
                    if r.kind == RelationshipKind.HOSTED_BY
                ),
                None,
            )
            if host is None:
                continue
            (x0, y0), (x1, y1) = wall_axis(host)
            t = (el.position.x + el.dimensions.width / 2) / max(host.dimensions.length, 1e-9)
            mid = ShapelyPoint(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            for key, poly in self.polys.items():
                if self.rooms[key].level_id == host.level_id and poly.exterior.distance(mid) < 1e-3:
                    lit.add(key)
        return lit


def _label(spec: BuildingSpecification, key: str | None) -> str:
    room = next((r for r in spec.rooms if r.key == key), None)
    if room is None:
        return key or "?"
    return room.name or room.key.replace("_", " ").capitalize()


def _check(spec: BuildingSpecification, req: Requirement, facts: _Facts) -> RequirementCheck:
    def make(label: str, expected: str, delivered: str, met: bool) -> RequirementCheck:
        return RequirementCheck(
            path=req.path,
            kind=req.kind,
            label=label,
            priority=req.priority.value,
            origin=req.origin.value,
            quote=req.quote,
            expected=expected,
            delivered=delivered,
            met=met,
        )

    name = _label(spec, req.room)
    if req.kind == "room_area":
        room = next(r for r in spec.rooms if r.key == req.room)
        bounds = area_range(room)
        keys = facts.instances(room.key)
        areas = [facts.rooms[k].dimensions.area for k in keys]
        met = bool(areas) and all(bounds.low - 1e-6 <= a <= bounds.high + 1e-6 for a in areas)
        return make(
            f"{name}: area",
            f"{bounds.target:g} m² ({bounds.low:.1f}-{bounds.high:.1f} m²)",
            ", ".join(f"{a:.1f} m²" for a in areas) or "missing",
            met,
        )
    if req.kind in ("adjacent", "open", "separate"):
        other = _label(spec, req.other)
        a_keys = facts.instances(req.room or "")
        b_keys = facts.instances(req.other or "")
        measure = facts.open_connection if req.kind == "open" else facts.shared
        best = max((measure(a, b) for a in a_keys for b in b_keys), default=0.0)
        if req.kind == "separate":
            return make(
                f"{name} apart from {other}",
                "no shared wall",
                f"{best:.1f} m shared" if best > SEPARATION_TOLERANCE else "no shared wall",
                bool(a_keys and b_keys) and best <= SEPARATION_TOLERANCE,
            )
        verb = "next to" if req.kind == "adjacent" else "open to"
        what = "shared wall" if req.kind == "adjacent" else "open connection (no wall)"
        return make(
            f"{name} {verb} {other}",
            f"{what} >= {ADJACENT_MIN_SHARED} m",
            f"{best:.1f} m {'shared' if req.kind == 'adjacent' else 'open'}",
            best >= ADJACENT_MIN_SHARED,
        )
    if req.kind == "faces":
        room = next(r for r in spec.rooms if r.key == req.room)
        side = room.faces.value if room.faces else "?"
        keys = facts.instances(room.key)
        reached = [k for k in keys if k in facts.on_facade.get(side, set())]
        return make(
            f"{name} faces the {side}",
            side,
            f"{len(reached)} of {len(keys)} on the {side} facade",
            bool(keys) and len(reached) == len(keys),
        )
    if req.kind == "footprint":
        wanted = spec.design.footprint_shape.value if spec.design.footprint_shape else "?"
        got = facts.footprint.shape
        names = MEASURED_LABELS
        return make(
            "Footprint shape",
            names.get(wanted, wanted),
            f"{names[got]} ({facts.footprint.vertices} corners)",
            wanted == got,
        )
    # windows
    intent = spec.design.windows
    by_facade = facts.summary.windows_by_facade
    missing = [
        f.value
        for f in (intent.preferred_facades if intent else [])
        if by_facade.get(f.value, {}).get(intent.emphasis.value if intent else "", 0) == 0
    ]
    misplaced = [
        f.value
        for f in (intent.excluded_facades if intent else [])
        if sum(by_facade.get(f.value, {}).get(s.value, 0) for s in EMPHASIS) > 0
    ]
    emphasis = intent.emphasis.value if intent else "?"
    where = ", ".join(f.value for f in intent.preferred_facades) if intent else "?"
    return make(
        f"{emphasis.capitalize()} windows on the {where} facade",
        f"{emphasis} on {where}",
        "as requested"
        if not missing and not misplaced
        else "; ".join(
            ([f"none on {', '.join(missing)}"] if missing else [])
            + ([f"emphasised on excluded {', '.join(misplaced)}"] if misplaced else [])
        ),
        not missing and not misplaced,
    )


def _criteria(
    spec: BuildingSpecification, facts: _Facts, checks: list[RequirementCheck]
) -> list[CriterionScore]:
    priorities = set(spec.design.priorities)
    out: list[CriterionScore] = []

    def add(
        key: str,
        label: str,
        score: float,
        explanation: str,
        *,
        base: float = 1.0,
        priority: DesignPriority | None = None,
    ) -> None:
        weight = base * (PRIORITY_WEIGHT if priority in priorities else 1.0)
        out.append(
            CriterionScore(
                key=key,
                label=label,
                score=round(min(1.0, max(0.0, score)), 4),
                weight=weight,
                explanation=explanation,
            )
        )

    rooms = facts.rooms
    by_type: dict[RoomType, list[str]] = defaultdict(list)
    for key, r in sorted(rooms.items()):
        by_type[r.properties.room_type].append(key)

    # Explicit room sizes.
    deviations: list[tuple[str, float]] = []
    for req in spec.rooms:
        if req.target_area_m2 is None:
            continue
        for key in facts.instances(req.key):
            area = rooms[key].dimensions.area
            deviations.append((key, (area - req.target_area_m2) / req.target_area_m2))
    if deviations:
        worst_key, worst = max(deviations, key=lambda d: (abs(d[1]), d[0]))
        score = sum(max(0.0, 1 - abs(d) / AREA_SCORE_SPAN) for _, d in deviations) / len(deviations)
        add(
            "area_accuracy",
            "Requested room sizes",
            score,
            f"{len(deviations)} sized room(s); largest deviation {worst:+.0%} "
            f"({worst_key.removeprefix('room:')})",
            base=2.0,
        )

    preferences = [c for c in checks if c.priority == "should"]
    if preferences:
        met = [c for c in preferences if c.met]
        missed = [c.label for c in preferences if not c.met]
        add(
            "preferences",
            "Preferences met",
            len(met) / len(preferences),
            f"{len(met)} of {len(preferences)} met"
            + (f"; missed: {'; '.join(missed[:3])}" if missed else ""),
            base=2.0,
        )

    gfa = facts.summary.gross_floor_area_m2
    circulation = sum(
        r.dimensions.area for r in rooms.values() if r.properties.room_type in CIRCULATION
    )
    if gfa > 0:
        share = circulation / gfa
        add(
            "circulation",
            "Circulation efficiency",
            (CIRCULATION_POOR - share) / (CIRCULATION_POOR - CIRCULATION_GOOD),
            f"corridors, hall and stairs take {share:.0%} of the floor area",
            priority=DesignPriority.COMPACTNESS,
        )

    habitable = [k for k, r in rooms.items() if r.properties.room_type in HABITABLE]
    if habitable:
        stretched = []
        for key in habitable:
            x0, y0, x1, y1 = facts.polys[key].bounds
            w, d = x1 - x0, y1 - y0
            if max(w, d) / max(min(w, d), 1e-9) > HABITABLE_ASPECT_LIMIT:
                stretched.append(key.removeprefix("room:"))
        add(
            "proportions",
            "Room proportions",
            1 - len(stretched) / len(habitable),
            f"{len(habitable) - len(stretched)} of {len(habitable)} habitable rooms within "
            f"{HABITABLE_ASPECT_LIMIT}:1"
            + (f"; elongated: {', '.join(stretched[:3])}" if stretched else ""),
        )
        lit = [k for k in habitable if k in facts.lit]
        add(
            "daylight",
            "Daylight",
            len(lit) / len(habitable),
            f"{len(lit)} of {len(habitable)} habitable rooms have a window or glazed door",
            priority=DesignPriority.DAYLIGHT,
        )

    bedrooms = by_type[RoomType.BEDROOM]
    day = [k for t in DAY for k in by_type[t]]
    if bedrooms:
        exposed = sorted(
            b.removeprefix("room:")
            for b in bedrooms
            if any(facts.shared(b, d) > SEPARATION_TOLERANCE for d in day)
        )
        add(
            "privacy",
            "Bedroom privacy",
            1 - len(exposed) / len(bedrooms),
            f"{len(bedrooms) - len(exposed)} of {len(bedrooms)} bedrooms share no wall with "
            "living, dining or kitchen spaces"
            + (f"; exposed: {', '.join(exposed[:3])}" if exposed else ""),
            priority=DesignPriority.PRIVACY,
        )

    living = [
        k
        for t in (RoomType.LIVING, RoomType.DINING, RoomType.OPEN_KITCHEN_LIVING)
        for k in by_type[t]
    ]
    if living:
        rear = [k for k in living if k in facts.on_facade.get("rear", set())]
        away = [k.removeprefix("room:") for k in living if k not in rear]
        add(
            "garden",
            "Garden connection",
            len(rear) / len(living),
            f"{len(rear)} of {len(living)} living/dining spaces reach the garden facade"
            + (f"; not: {', '.join(away)}" if away else ""),
            priority=DesignPriority.GARDEN_CONNECTION,
        )

    # Garden frontage (V1.2): how much of the garden (rear) facade the living spaces hold,
    # measured along the walls, when the client asked for a garden connection (priority, or a
    # living space that should face the rear). The explanation names what holds the rest.
    wants_garden = DesignPriority.GARDEN_CONNECTION in priorities or any(
        r.faces == FacadeSide.REAR and r.type.value in {t.value for t in GARDEN_ROOMS}
        for r in spec.rooms
    )
    if living and wants_garden:
        along_rear = facts.facade_lengths(FacadeSide.REAR)
        total = sum(along_rear.values())
        held = sum(v for k, v in along_rear.items() if k in living)
        others: dict[str, float] = defaultdict(float)
        for k, v in along_rear.items():
            if k not in living:
                others[rooms[k].properties.room_type.value.replace("_", " ")] += v
        rest = ", ".join(f"{t} {v:.1f} m" for t, v in sorted(others.items(), key=lambda i: -i[1]))
        add(
            "garden_frontage",
            "Garden frontage of the living spaces",
            held / total if total > 0 else 0.0,
            f"living/dining spaces hold {held:.1f} m of the {total:.1f} m garden facade"
            + (f"; the rest: {rest}" if rest else ""),
            priority=DesignPriority.GARDEN_CONNECTION,
        )

    pairs = [(RoomType.KITCHEN, RoomType.DINING), (RoomType.DINING, RoomType.LIVING)]
    present = [(a, b) for a, b in pairs if by_type[a] and by_type[b]]
    if present:
        joined = [
            (a, b)
            for a, b in present
            if any(
                facts.shared(x, y) >= ADJACENT_MIN_SHARED for x in by_type[a] for y in by_type[b]
            )
        ]
        add(
            "day_sequence",
            "Kitchen, dining and living together",
            len(joined) / len(present),
            f"{len(joined)} of {len(present)} of kitchen-dining / dining-living are neighbours",
            priority=DesignPriority.OPEN_PLAN,
        )

    ground = facts.model.levels[0].id if facts.model.levels else None
    outline = unary_union(  # not on the 1 mm grid yet: see docs/3d-engine.md §16.11
        [
            facts.polys[k]
            for k, r in rooms.items()
            if r.level_id == ground
            and r.properties.room_type != RoomType.GARAGE
            and r.properties.zone != Zone.EXTERIOR
        ]
    )
    if outline.area > 0:
        ratio = outline.length / (4 * math.sqrt(outline.area))
        add(
            "compactness",
            "Compact footprint",
            1 - (ratio - 1) / COMPACT_RATIO_SPAN,
            f"perimeter is {ratio:.2f}x that of a square of the same area",
            priority=DesignPriority.COMPACTNESS,
        )
    return out


def evaluate_design(spec: BuildingSpecification, model: BuildingModel) -> DesignEvaluation:
    facts = _Facts(model)
    checks = [_check(spec, req, facts) for req in requirements(spec)]
    criteria = _criteria(spec, facts, checks)
    total = sum(c.weight for c in criteria)
    score = sum(c.score * c.weight for c in criteria) / total if total > 0 else 0.0
    return DesignEvaluation(
        requirements=checks, criteria=criteria, score=round(score, 4), footprint=facts.footprint
    )
