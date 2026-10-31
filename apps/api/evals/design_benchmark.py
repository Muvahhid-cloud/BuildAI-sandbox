"""Design Intelligence benchmark runner (data/fixtures/benchmark/design-benchmark.v1.json).

Each case: prompt -> offline interpreter (the MockAIProvider's deterministic interpreter; no
paid model calls) -> SpecificationDraft (tier 1) -> spec checks (tier 2) -> layout engine with
the knowledge pack's layout patterns -> expectations checked on the generated BuildingModel.

The checks here compute their own facts from the model's geometry (room polygons, wall
facades, windows). They deliberately do not reuse building/evaluation.py, so the engine is
not grading itself.

    python -m evals.design_benchmark                 # table on stdout
    python -m evals.design_benchmark --json out.json
    python -m evals.design_benchmark --no-patterns   # same engine without pattern guidance
"""

import argparse
import inspect
import json
import math
import sys
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.geometry import Point as ShapelyPoint
from shapely.ops import unary_union

from app.modules.ai.providers.mock_interpreter import interpret_offline
from app.modules.ai.schemas.generation import SpecificationDraft
from app.modules.building.elements import Door, Roof, Room, Wall, Window
from app.modules.building.enums import DoorKind, RelationshipKind, WallKind
from app.modules.building.facades import facade_of_wall
from app.modules.building.geometry import wall_axis
from app.modules.building.issues import errors
from app.modules.building.model import BuildingModel
from app.modules.building.specification import BuildingSpecification
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.engine import LayoutError, LayoutResult, generate_layout
from app.modules.rules.loader import load_rules_profile
from app.modules.rules.spec_checks import check_spec

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
CASES_PATH = DATA_DIR / "fixtures" / "benchmark" / "design-benchmark.v1.json"
NAMESPACE = uuid.UUID("5d1f0c3e-8a3b-4f7e-9c11-0a2b3c4d5e6f")
RULES_REF = "generic-residential@1"
ADJACENT_MIN_SHARED = 0.9  # m of shared boundary: room for a door
APART_TOLERANCE = 0.05  # m: a corner touch is not a shared wall
CIRCULATION = {"corridor", "hall", "entrance", "staircase"}
HABITABLE = {"living", "dining", "kitchen", "open_kitchen_living", "bedroom", "study"}


@dataclass
class Outcome:
    kind: str
    priority: str
    category: str
    passed: bool
    measured: str
    known_gap: str | None = None


@dataclass
class CaseResult:
    id: str
    status: str  # model | failed | clarification | spec_invalid
    set: str = "v1"  # benchmark generation the case was added in (reported separately)
    message: str = ""
    patterns: list[str] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)


@dataclass
class _Run:
    draft: SpecificationDraft
    spec: BuildingSpecification | None
    result: LayoutResult | None
    error: LayoutError | None
    facts: "_Facts | None"
    spec_errors: list[str] = field(default_factory=list)
    rerun: Callable[[], BuildingModel] | None = None  # same inputs again (determinism check)


class _Facts:
    def __init__(self, model: BuildingModel) -> None:
        self.model = model
        self.rooms = {
            el.semantic_key: el for el in model.elements if isinstance(el, Room) and el.semantic_key
        }
        self.poly = {
            k: Polygon(
                [
                    (round(r.position.x + p.x, 3), round(r.position.y + p.y, 3))
                    for p in r.properties.boundary
                ]
            )
            for k, r in self.rooms.items()
        }
        self.walls = [el for el in model.elements if isinstance(el, Wall)]
        self.exterior = [w for w in self.walls if w.properties.wall_kind == WallKind.EXTERIOR]
        ground = model.levels[0].id
        inside = [
            self.poly[k]
            for k, r in self.rooms.items()
            if r.level_id == ground
            and r.properties.room_type.value not in ("garage", "terrace")
            and r.properties.zone.value != "exterior"
        ]
        self.footprint = unary_union(inside)

    def keys(self, name: str) -> list[str]:
        """Rooms of a spec key: room:<name> or room:<name>_<n>."""
        out = []
        for k in sorted(self.rooms):
            tail = k.removeprefix("room:")
            rest = tail.removeprefix(name)
            if tail.startswith(name) and (rest == "" or (rest[1:].isdigit() and rest[0] == "_")):
                out.append(k)
        return out

    def of_type(self, room_type: str) -> list[str]:
        return [
            k for k, r in sorted(self.rooms.items()) if r.properties.room_type.value == room_type
        ]

    def shared(self, a: str, b: str) -> float:
        if self.rooms[a].level_id != self.rooms[b].level_id:
            return 0.0
        return float(self.poly[a].exterior.intersection(self.poly[b].exterior).length)

    def wall_free(self, a: str, b: str) -> Any:
        """Part of the shared boundary of two rooms with no wall on it."""
        level = self.rooms[a].level_id
        walls = unary_union(
            [LineString(wall_axis(w)).buffer(1e-3) for w in self.walls if w.level_id == level]
        )
        return self.poly[a].exterior.intersection(self.poly[b].exterior).difference(walls)

    def open_to(self, a: str, b: str) -> float:
        """Wall-free connection: directly, or both open onto a circulation room where their
        open edges face each other (measured along the edge)."""
        if self.rooms[a].level_id != self.rooms[b].level_id:
            return 0.0
        best = float(self.wall_free(a, b).length)
        for c, room in self.rooms.items():
            if room.level_id != self.rooms[a].level_id:
                continue
            if room.properties.room_type.value not in CIRCULATION:
                continue
            ea, eb = self.wall_free(a, c), self.wall_free(b, c)
            if ea.length < ADJACENT_MIN_SHARED or eb.length < ADJACENT_MIN_SHARED:
                continue
            (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = ea.bounds, eb.bounds
            if ax1 - ax0 >= ay1 - ay0:
                best = max(best, min(ax1, bx1) - max(ax0, bx0))
            else:
                best = max(best, min(ay1, by1) - max(ay0, by0))
        return best

    def house_walls(self) -> list[Wall]:
        return [w for w in self.exterior if w.semantic_key.startswith("wall:ext:")]

    def reaches(self, key: str, facade: str) -> bool:
        """The room has >= 0.5 m of boundary on an exterior wall of the house that faces
        `facade` (works for any rectilinear footprint, e.g. an L)."""
        level = self.rooms[key].level_id
        ring = self.poly[key].exterior
        for w in self.house_walls():
            side = facade_of_wall(w.properties.wall_kind, w.rotation.z)
            if w.level_id != level or side is None or side.value != facade:
                continue
            if ring.intersection(LineString(wall_axis(w)).buffer(1e-3)).length >= 0.5:
                return True
        return False

    def facade_length(self, key: str, facade: str) -> float:
        """Length of the room's boundary on exterior walls of the house facing `facade`."""
        level = self.rooms[key].level_id
        ring = self.poly[key].exterior
        total = 0.0
        for w in self.house_walls():
            side = facade_of_wall(w.properties.wall_kind, w.rotation.z)
            if w.level_id != level or side is None or side.value != facade:
                continue
            total += ring.intersection(LineString(wall_axis(w)).buffer(1e-3)).length
        return total

    def windows(self, *, glazed_doors: bool = False) -> list[tuple[str | None, str | None, str]]:
        """(facade, size class, room key) per window (and glazed sliding door if asked)."""
        walls = {w.id: w for w in self.walls}
        out = []
        for el in self.model.elements:
            if not isinstance(el, (Window, Door)):
                continue
            if isinstance(el, Door) and not (
                glazed_doors and el.properties.door_kind == DoorKind.SLIDING
            ):
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
            side = facade_of_wall(host.properties.wall_kind, host.rotation.z)
            (x0, y0), (x1, y1) = wall_axis(host)
            t = (el.position.x + el.dimensions.width / 2) / max(host.dimensions.length, 1e-9)
            mid = ShapelyPoint(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            room = next(
                (
                    k
                    for k, p in self.poly.items()
                    if self.rooms[k].level_id == host.level_id and p.exterior.distance(mid) < 1e-3
                ),
                "",
            )
            size = (
                el.properties.size_class.value
                if isinstance(el, Window) and el.properties.size_class
                else None
            )
            out.append((side.value if side else None, size, room))
        return out


Check = Callable[[dict[str, Any], _Run], tuple[bool, str]]
CHECKS: dict[str, Check] = {}


def check(kind: str) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS[kind] = fn
        return fn

    return register


def _needs_model(run: _Run) -> _Facts:
    if run.facts is None:
        raise _NoModelError
    return run.facts


class _NoModelError(Exception):
    pass


@check("storeys")
def _storeys(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    n = len(_needs_model(run).model.levels)
    return n == e["equals"], f"{n} storeys"


@check("room_count")
def _room_count(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    n = len(_needs_model(run).of_type(e["room_type"]))
    return n == e["equals"], f"{n} {e['room_type']}"


@check("has_room_type")
def _has(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    n = len(_needs_model(run).of_type(e["room_type"]))
    return n > 0, f"{n} {e['room_type']}"


@check("room_area")
def _room_area(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    areas = [f.rooms[k].dimensions.area for k in f.keys(e["room"])]
    target, tol = e["target"], e["tolerance"]
    ok = bool(areas) and all(abs(a - target) <= tol * target + 1e-6 for a in areas)
    return ok, ", ".join(f"{a:.1f} m²" for a in areas) or "missing"


@check("room_area_range")
def _room_area_range(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    areas = [f.rooms[k].dimensions.area for k in f.keys(e["room"])]
    ok = bool(areas) and all(e["min"] - 1e-6 <= a <= e["max"] + 1e-6 for a in areas)
    return ok, ", ".join(f"{a:.1f} m²" for a in areas) or "missing"


@check("adjacent")
def _adjacent(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    a, b = f.keys(e["a"]), f.keys(e["b"])
    best = max((f.shared(x, y) for x in a for y in b), default=0.0)
    if not a or not b:
        return False, "room missing"
    return best >= ADJACENT_MIN_SHARED, f"{best:.2f} m shared"


def _corners(shape: Any) -> tuple[int, int]:
    """(corners, inside corners) of a polygon's outer ring, collinear points dropped."""
    ring = list(shape.exterior.coords)[:-1]
    if not shape.exterior.is_ccw:
        ring.reverse()
    corners = reflex = 0
    for i in range(len(ring)):
        (ax, ay), (bx, by), (cx, cy) = ring[i - 1], ring[i], ring[(i + 1) % len(ring)]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) > 1e-6:
            corners += 1
            reflex += cross < 0
    return corners, reflex


@check("footprint_shape")
def _footprint_shape(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    if not isinstance(f.footprint, Polygon):
        return False, "ground floor rooms are not one polygon"
    if f.footprint.interiors:
        holes = len(f.footprint.interiors)
        shape = "courtyard" if holes == 1 else "other"
        return shape == e["equals"], f"{shape} ({holes} enclosed outdoor space(s))"
    corners, reflex = _corners(f.footprint)
    shape = (
        "rectangular"
        if (corners, reflex) == (4, 0)
        else "l_shape"
        if (corners, reflex) == (6, 1)
        else _eight_corners(f.footprint)
        if (corners, reflex) == (8, 2)
        else "other"
    )
    return shape == e["equals"], f"{shape} ({corners} corners, {reflex} inside)"


def _eight_corners(shape: Any) -> str:
    """8 corners, 2 inside: U when the two inside corners are joined by one edge (the court's
    back), T when they lie on one line three edges apart (the stem between them)."""
    ring = list(shape.exterior.coords)[:-1]
    if not Polygon(ring).exterior.is_ccw:
        ring.reverse()
    corners: list[tuple[float, float]] = []
    inside: list[int] = []
    for i in range(len(ring)):
        (ax, ay), (bx, by), (cx, cy) = ring[i - 1], ring[i], ring[(i + 1) % len(ring)]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) > 1e-6:
            if cross < 0:
                inside.append(len(corners))
            corners.append((bx, by))
    a, b = inside
    gap = min(b - a, len(corners) - (b - a))
    if gap == 1:
        return "u_shape"
    same_line = (
        abs(corners[a][0] - corners[b][0]) < 1e-6 or abs(corners[a][1] - corners[b][1]) < 1e-6
    )
    return "t_shape" if gap == 3 and same_line else "other"


@check("envelope_closed")
def _envelope_closed(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    walls = _needs_model(run).house_walls()
    axes = [wall_axis(w) for w in walls if w.level_id == run.facts.model.levels[0].id]  # type: ignore[union-attr]
    open_ends = sum(
        1 for _, end in axes if sum(1 for start, _ in axes if math.dist(start, end) < 1e-4) != 1
    )
    return open_ends == 0 and len(axes) >= 4, f"{len(axes)} walls, {open_ends} open ends"


@check("rooms_tile_envelope")
def _rooms_tile(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    ground = f.model.levels[0].id
    polys = [
        f.poly[k]
        for k, r in f.rooms.items()
        if r.level_id == ground
        and r.properties.room_type.value not in ("garage", "terrace")
        and r.properties.zone.value != "exterior"
    ]
    union = unary_union(polys)
    overlap = sum(p.area for p in polys) - union.area
    walls = unary_union(
        [LineString(wall_axis(w)).buffer(1e-3) for w in f.house_walls() if w.level_id == ground]
    )
    gap = union.boundary.difference(walls).length
    return (
        overlap < 1e-3 and gap < 1e-3,
        f"overlap {overlap:.3f} m², boundary off walls {gap:.3f} m",
    )


@check("all_rooms_reachable")
def _reachable(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    """From the room behind the front door, through doors and wall-free openings."""
    f = _needs_model(run)
    by_id = {r.id: k for k, r in f.rooms.items()}
    doors = [el for el in f.model.elements if isinstance(el, Door)]
    links: dict[str, set[str]] = defaultdict(set)
    start = None
    for d in doors:
        keys = [
            by_id[r.target_id]
            for r in d.relationships
            if r.kind == RelationshipKind.CONNECTS and r.target_id in by_id
        ]
        if d.properties.door_kind == DoorKind.ENTRANCE and keys:
            start = keys[0]
        for a in keys:
            links[a] |= set(keys) - {a}
    keys = sorted(f.rooms)
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if f.rooms[a].level_id == f.rooms[b].level_id and f.wall_free(a, b).length >= 0.9:
                links[a].add(b)
                links[b].add(a)
    if start is None:
        return False, "no front door"
    seen, todo = {start}, [start]
    while todo:
        for n in sorted(links[todo.pop()]):
            if n not in seen:
                seen.add(n)
                todo.append(n)
    inside = [
        k
        for k, r in f.rooms.items()
        if r.properties.zone.value != "exterior" and r.level_id == f.model.levels[0].id
    ]
    missing = sorted(k.removeprefix("room:") for k in inside if k not in seen)
    return not missing, "all reachable" if not missing else f"unreachable: {', '.join(missing)}"


@check("openings_hosted")
def _openings(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    walls = {w.id: w for w in f.walls}
    bad = []
    for el in f.model.elements:
        if isinstance(el, (Door, Window)):
            host = next(
                (
                    walls.get(r.target_id)
                    for r in el.relationships
                    if r.kind == RelationshipKind.HOSTED_BY
                ),
                None,
            )
            if (
                host is None
                or el.position.x < -1e-6
                or (el.position.x + el.dimensions.width > host.dimensions.length + 1e-6)
                or host.level_id != el.level_id
            ):
                bad.append(el.name)
    return not bad, "all on their host walls" if not bad else ", ".join(bad[:4])


@check("deterministic")
def _deterministic(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    if run.rerun is None:
        return False, "cannot rerun"
    same = run.rerun().model_dump_json() == f.model.model_dump_json()
    return same, "identical model" if same else "different model on the same inputs"


@check("failure_mentions")
def _failure_mentions(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    """The reason given when generation stopped: the layout engine's issues, or the spec
    checks that refused the request before layout (e.g. a shape with no generator)."""
    if run.error is not None:
        text = " ".join(f"{i.message} {i.suggestion or ''}" for i in run.error.issues)
    elif run.spec_errors:
        text = " ".join(run.spec_errors)
    else:
        return False, "generation did not fail"
    found = [w for w in e["contains"] if w.lower() in text.lower()]
    return len(found) == len(e["contains"]), text[:160]


@check("open_connection")
def _open_connection(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    a, b = f.keys(e["a"]), f.keys(e["b"])
    if not a or not b:
        return False, "room missing"
    best = max(f.open_to(x, y) for x in a for y in b)
    return best >= ADJACENT_MIN_SHARED, f"{best:.2f} m open"


@check("apart")
def _apart(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    exposed = sorted(
        x.removeprefix("room:")
        for x in f.of_type(e["a_type"])
        for t in e["b_types"]
        for y in f.of_type(t)
        if f.shared(x, y) > APART_TOLERANCE
    )
    return not exposed, "apart" if not exposed else f"sharing walls: {', '.join(exposed)}"


@check("reaches_facade")
def _reaches(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    keys = f.keys(e["room"])
    hits = [k for k in keys if f.reaches(k, e["facade"])]
    return bool(keys) and len(hits) == len(keys), f"{len(hits)}/{len(keys)} on {e['facade']}"


@check("facade_share_min")
def _facade_share(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    """Share of the house's `facade` (length along its exterior walls, house rooms only) held
    by the named rooms: e.g. how much of the garden facade the living spaces get."""
    f = _needs_model(run)
    rooms = [
        k
        for k, r in f.rooms.items()
        if r.properties.zone.value != "exterior" and r.properties.room_type.value != "garage"
    ]
    lengths = {k: f.facade_length(k, e["facade"]) for k in rooms}
    total = sum(lengths.values())
    named = {k for name in e["rooms"] for k in f.keys(name)}
    held = sum(v for k, v in lengths.items() if k in named)
    share = held / total if total > 0 else 0.0
    return share >= e["min"], f"{held:.1f} of {total:.1f} m ({share:.0%})"


@check("windows_on_facade")
def _windows_on(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    n = sum(
        1
        for side, size, _ in _needs_model(run).windows()
        if side == e["facade"] and size == e["size"]
    )
    return n >= e["min"], f"{n} {e['size']} on {e['facade']}"


@check("no_windows_on_facade")
def _no_windows_on(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    n = sum(
        1
        for side, size, _ in _needs_model(run).windows()
        if side == e["facade"] and size in e["sizes"]
    )
    return n == 0, f"{n} {'/'.join(e['sizes'])} on {e['facade']}"


@check("facade_color")
def _facade_color(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    colors = sorted({w.properties.finish_right_color or "-" for w in _needs_model(run).exterior})
    return colors == [e["hex"]], ", ".join(colors)


@check("facade_material")
def _facade_material(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    materials = sorted({w.material_id or "-" for w in _needs_model(run).exterior})
    return materials == [e["material_id"]], ", ".join(materials)


@check("roof_type")
def _roof(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    model = _needs_model(run).model
    types = sorted({el.properties.roof_type.value for el in model.elements if isinstance(el, Roof)})
    return e["equals"] in types and len(types) <= 2, ", ".join(types)


@check("footprint_max_width")
def _footprint_width(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    xs = [x for w in _needs_model(run).exterior for p in wall_axis(w) for x in (p[0],)]
    thickness = max((w.dimensions.thickness for w in _needs_model(run).exterior), default=0.0)
    width = (max(xs) - min(xs) + thickness) if xs else 0.0  # outer faces
    return width <= e["max"] + 1e-6, f"{width:.2f} m"


@check("circulation_share_max")
def _circulation(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    inside = [
        r
        for r in f.rooms.values()
        if r.properties.zone.value != "exterior" and r.properties.room_type.value != "garage"
    ]
    total = sum(r.dimensions.area for r in inside)
    circ = sum(r.dimensions.area for r in inside if r.properties.room_type.value in CIRCULATION)
    share = circ / total if total else 1.0
    return share <= e["max"], f"{share:.0%}"


@check("daylight_all_habitable")
def _daylight(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    lit = {room for _, _, room in f.windows(glazed_doors=True)}
    rooms = [k for k, r in f.rooms.items() if r.properties.room_type.value in HABITABLE]
    dark = sorted(k.removeprefix("room:") for k in rooms if k not in lit)
    return not dark, f"{len(rooms) - len(dark)}/{len(rooms)} lit" + (
        f" (dark: {', '.join(dark)})" if dark else ""
    )


@check("enclosed_courtyard")
def _courtyard(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    f = _needs_model(run)
    holes = sum(
        len(getattr(g, "interiors", [])) for g in getattr(f.footprint, "geoms", [f.footprint])
    )
    return holes > 0, f"{holes} enclosed outdoor space(s)"


@check("unsupported_mentions")
def _unsupported(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    items = run.draft.unsupported_requests
    return any(e["contains"].lower() in u.lower() for u in items), "; ".join(items) or "none"


@check("spec_shape")
def _spec_shape(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    """The interpreted footprint shape and its priority (must | should)."""
    if run.spec is None:
        return False, "no spec"
    shape = run.spec.design.footprint_shape
    priority = run.spec.priority_of("/design/footprint_shape").value
    got = f"{shape.value if shape else None}={priority}"
    return got == f"{e['equals']}={e['priority_value']}", got


@check("spec_storeys")
def _spec_storeys(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    n = run.spec.targets.storeys if run.spec else None
    return n == e["equals"], f"{n} storeys in the spec"


@check("spec_room_count")
def _spec_room_count(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    n = sum(r.count for r in run.spec.rooms if r.type.value == e["room_type"]) if run.spec else 0
    return n == e["equals"], f"{n} {e['room_type']} in the spec"


@check("no_warning")
def _no_warning(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    if run.result is None:
        raise _NoModelError
    found = [w.message for w in run.result.warnings if w.code == e["code"]]
    return not found, found[0][:160] if found else f"no {e['code']}"


@check("spec_priority")
def _spec_priority(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    if run.spec is None:
        return False, "no spec"
    values = [p.value for p in getattr(run.spec.design, "priorities", [])]
    return e["priority_value"] in values, ", ".join(values) or "none"


@check("spec_gfa")
def _spec_gfa(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    gfa = run.spec.targets.gross_floor_area_m2 if run.spec else None
    return gfa == e["equals"], f"{gfa} m²"


@check("spec_must")
def _spec_must(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    traces = getattr(run.spec, "requirements", []) if run.spec else []
    hits = [t for t in traces if t.path.endswith(e["path_suffix"])]
    ok = any(t.priority.value == "must" for t in hits)
    return ok, ", ".join(f"{t.path}={t.priority.value}" for t in hits) or "no trace"


@check("pattern_applied")
def _pattern(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    applied = [p.id for p in getattr(run.result, "patterns", ())] if run.result else []
    return e["pattern"] in applied, ", ".join(applied) or "none"


@check("pattern_not_applied")
def _no_pattern(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    applied = [p.id for p in getattr(run.result, "patterns", ())] if run.result else []
    return e["pattern"] not in applied, ", ".join(applied) or "none"


@check("musts_honoured_or_explained")
def _musts(e: dict[str, Any], run: _Run) -> tuple[bool, str]:
    """Either every MUST requirement holds on the model, or generation (or tier-2 validation)
    failed and said why. A model that silently misses a MUST requirement fails."""
    if run.spec_errors:
        return True, f"rejected before layout: {run.spec_errors[0]}"
    if run.error is not None:
        named = [i.message for i in run.error.issues]
        return bool(named), f"{run.error.code}: {'; '.join(named[:2])}"
    if run.spec is None or run.facts is None:
        return False, "no spec"
    failures = []
    for trace in getattr(run.spec, "requirements", []):
        if trace.priority.value != "must":
            continue
        parts = trace.path.strip("/").split("/")
        if parts[0] != "rooms":
            continue
        room = run.spec.rooms[int(parts[1])]
        if parts[2] == "target_area_m2" and room.target_area_m2 is not None:
            low = room.min_area_m2 or room.target_area_m2 * 0.9
            high = room.max_area_m2 or room.target_area_m2 * 1.1
            for k in run.facts.keys(room.key):
                a = run.facts.rooms[k].dimensions.area
                if not low - 1e-6 <= a <= high + 1e-6:
                    failures.append(f"{room.key} {a:.1f} m²")
        elif parts[2] == "adjacent_to":
            ok, measured = _adjacent({"a": room.key, "b": room.adjacent_to[int(parts[3])]}, run)
            if not ok:
                failures.append(f"{room.key} next to {room.adjacent_to[int(parts[3])]}: {measured}")
        elif parts[2] == "faces" and room.faces is not None:
            facade = room.faces.value
            missed = [k for k in run.facts.keys(room.key) if not run.facts.reaches(k, facade)]
            if missed:
                failures.append(f"{room.key} not on the {facade} facade")
    return not failures, "all MUST requirements met" if not failures else "; ".join(failures)


def _patterns() -> Any:
    try:
        from app.modules.catalog.loader import read_knowledge
        from app.modules.catalog.patterns import pattern_library
    except ImportError:  # older engine without layout patterns
        return None
    return pattern_library(read_knowledge(DATA_DIR))


def run_case(case: dict[str, Any], *, use_patterns: bool = True) -> CaseResult:
    draft = SpecificationDraft.model_validate(interpret_offline(case["prompt"]))
    profile = load_rules_profile(DATA_DIR, RULES_REF)
    spec = draft.specification
    run = _Run(draft, spec, None, None, None)
    result = CaseResult(case["id"], "model", set=case.get("set", "v1"))
    if spec is None:
        result.status, result.message = "clarification", "; ".join(draft.clarification_questions)
    else:
        spec_errors = errors(
            check_spec(spec, profile, floor_structure_m=DEFAULT_CONFIG.floor_slab_thickness)
        )
        if spec_errors:
            result.status = "spec_invalid"
            result.message = "; ".join(f"{i.code}: {i.message}" for i in spec_errors[:3])
            run.spec_errors = [f"{i.code}: {i.message}" for i in spec_errors]
        else:
            kwargs: dict[str, Any] = {}
            if use_patterns and "patterns" in inspect.signature(generate_layout).parameters:
                kwargs["patterns"] = _patterns()
            library = json.loads((DATA_DIR / "materials" / "library.json").read_text("utf-8"))
            try:
                run.result = generate_layout(
                    spec,
                    profile,
                    id_namespace=NAMESPACE,
                    seed=0,
                    material_ids={m["id"] for m in library["materials"]},
                    **kwargs,
                )
                run.facts = _Facts(run.result.model)
                run.rerun = lambda: (
                    generate_layout(
                        spec,
                        profile,
                        id_namespace=NAMESPACE,
                        seed=0,
                        material_ids={m["id"] for m in library["materials"]},
                        **kwargs,
                    ).model
                )
                result.patterns = [p.id for p in getattr(run.result, "patterns", ())]
            except LayoutError as exc:
                run.error = exc
                result.status = "failed"
                result.message = f"{exc.code}: {exc.message}"
    for e in case["expectations"]:
        try:
            passed, measured = CHECKS[e["kind"]](e, run)
        except _NoModelError:
            passed, measured = False, f"no model ({result.status})"
        result.outcomes.append(
            Outcome(e["kind"], e["priority"], e["category"], passed, measured, e.get("known_gap"))
        )
    return result


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = json.loads(path.read_text("utf-8"))["cases"]
    return cases


def summarize_by_set(results: list[CaseResult]) -> dict[str, dict[str, Any]]:
    """summarize() per benchmark generation (v1 = Design Intelligence V1, v1.1 = L footprints,
    v1.2 = L layout quality), so new cases never blur the results of the existing ones."""
    sets = sorted({r.set for r in results})
    return {s: summarize([r for r in results if r.set == s]) for s in sets}


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    by: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        for o in r.outcomes:
            if o.known_gap:
                by["known_gap"].append(o.passed)
                continue
            by[o.priority].append(o.passed)
            by[f"category:{o.category}"].append(o.passed)
    return {
        k: {"passed": sum(v), "total": len(v), "rate": round(sum(v) / len(v), 3) if v else math.nan}
        for k, v in sorted(by.items())
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path)
    parser.add_argument("--no-patterns", action="store_true")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):  # "m²" etc. on consoles with a legacy code page
        sys.stdout.reconfigure(encoding="utf-8")
    results = [run_case(c, use_patterns=not args.no_patterns) for c in load_cases()]
    out = sys.stdout
    for r in results:
        out.write(f"\n{r.id}  ({r.set}) [{r.status}] {r.message}\n")
        if r.patterns:
            out.write(f"  patterns: {', '.join(r.patterns)}\n")
        for o in r.outcomes:
            mark = "GAP " if o.known_gap else ("PASS" if o.passed else "FAIL")
            out.write(f"  {mark} {o.priority:4s} {o.category:9s} {o.kind:28s} {o.measured}\n")
    summary = summarize(results)
    by_set = summarize_by_set(results)
    out.write("\n" + json.dumps({"all": summary, "by_set": by_set}, indent=2) + "\n")
    if args.json:
        args.json.write_text(
            json.dumps(
                {"summary": summary, "by_set": by_set, "cases": [asdict(r) for r in results]},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
