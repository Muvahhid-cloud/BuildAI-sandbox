"""Evaluate a BuildingModel against a BuildingRulesProfile (conceptual checks only).

Every finding is a warning with a `rule_ref` pointing at the exact rule. Rules findings never
make a model invalid (model invariants do, see building/validation.py): they tell the user where
a design departs from the active profile. Not a building-code compliance check.
"""

import itertools
import uuid
from collections import defaultdict
from collections.abc import Sequence

from shapely import Point as ShapelyPoint
from shapely import Polygon as ShapelyPolygon
from shapely import box

from app.modules.building.elements import Door, Element, Railing, Room, Stair, Wall, Window
from app.modules.building.enums import DoorKind, RelationshipKind, RoomType, Zone
from app.modules.building.geometry import Point, to_absolute, wall_axis
from app.modules.building.issues import Issue
from app.modules.building.model import BuildingModel
from app.modules.building.primitives import EPS
from app.modules.rules.profile import BuildingRulesProfile

HABITABLE = frozenset(
    {
        RoomType.LIVING,
        RoomType.DINING,
        RoomType.KITCHEN,
        RoomType.OPEN_KITCHEN_LIVING,
        RoomType.BEDROOM,
        RoomType.STUDY,
    }
)
WET = frozenset({RoomType.BATHROOM, RoomType.WC, RoomType.EN_SUITE})
CIRCULATION = frozenset({RoomType.CORRIDOR, RoomType.HALL})
TOLERANCE = 1e-3


def clear_width(points: Sequence[Point]) -> float:
    """Clear width of a rectilinear room: the largest short side of any axis-aligned rectangle
    that fits inside it (for an L-shaped bedroom, the width of its main part, not of a
    shallow alcove). Measured on the boundary (wall centerlines).

    Rooms are small (a handful of vertices), so trying every rectangle on the vertex grid is
    cheap and exact for rectilinear shapes.
    """
    poly = ShapelyPolygon(points).buffer(TOLERANCE)
    xs = sorted({round(p[0], 6) for p in points})
    ys = sorted({round(p[1], 6) for p in points})
    best = 0.0
    for x0, x1 in itertools.combinations(xs, 2):
        for y0, y1 in itertools.combinations(ys, 2):
            side = min(x1 - x0, y1 - y0)
            if side > best and poly.contains(box(x0, y0, x1, y1)):
                best = side
    return best


class _Evaluator:
    def __init__(self, model: BuildingModel, profile: BuildingRulesProfile) -> None:
        self.model = model
        self.profile = profile
        self.issues: list[Issue] = []
        self.index = {el.id: i for i, el in enumerate(model.elements)}
        self.by_id: dict[uuid.UUID, Element] = {el.id: el for el in model.elements}
        self.levels = {lvl.id: lvl for lvl in model.levels}
        self.room_polys: dict[uuid.UUID, ShapelyPolygon] = {
            el.id: ShapelyPolygon(to_absolute(el.properties.boundary, el.position, el.rotation))
            for el in model.elements
            if isinstance(el, Room)
        }

    def warn(self, el: Element, code: str, suffix: str, message: str, rule: str) -> None:
        self.issues.append(
            Issue(
                severity="warning",
                code=code,
                path=f"/elements/{self.index[el.id]}{suffix}",
                message=message,
                rule_ref=self.profile.rule_ref(rule),
                element_id=el.id,
            )
        )

    def _rooms_at(self, level_id: uuid.UUID | None, p: Point) -> list[Room]:
        pt = ShapelyPoint(p)
        rooms = []
        for rid, poly in self.room_polys.items():
            room = self.by_id[rid]
            if (
                isinstance(room, Room)
                and room.level_id == level_id
                and poly.exterior.distance(pt) < EPS
            ):
                rooms.append(room)
        return rooms

    def _opening_point(self, el: Door | Window) -> tuple[Wall, Point] | None:
        hosts = [r.target_id for r in el.relationships if r.kind == RelationshipKind.HOSTED_BY]
        host = self.by_id.get(hosts[0]) if hosts else None
        if not isinstance(host, Wall):
            return None
        (sx, sy), (ex, ey) = wall_axis(host)
        t = (el.position.x + el.dimensions.width / 2) / host.dimensions.length
        return host, (sx + (ex - sx) * t, sy + (ey - sy) * t)

    # --- rooms ------------------------------------------------------------------------------

    def rooms(self) -> None:
        ceiling = self.profile.ceiling
        for el in self.model.elements:
            if not isinstance(el, Room):
                continue
            rtype = el.properties.room_type
            rule = self.profile.room(rtype)
            ref = self.profile.room_rule_ref(rtype).split(":", 1)[1]
            if el.dimensions.area + TOLERANCE < rule.min_area_m2:
                self.warn(
                    el,
                    "RULE_ROOM_AREA",
                    "/dimensions/area",
                    f"{el.name}: {el.dimensions.area} m² is below the {rule.min_area_m2} m² "
                    f"minimum for a {rtype}",
                    f"{ref}.min_area_m2",
                )
            pts = to_absolute(el.properties.boundary, el.position, el.rotation)
            width = clear_width(pts)
            min_width, width_rule = (
                (self.profile.corridors.min_width_m, "corridors.min_width_m")
                if rtype in CIRCULATION
                else (rule.min_width_m, f"{ref}.min_width_m")
            )
            if width + TOLERANCE < min_width:
                self.warn(
                    el,
                    "RULE_ROOM_WIDTH",
                    "/properties/boundary",
                    f"{el.name}: clear width {width:.2f} m is below the {min_width} m minimum",
                    width_rule,
                )
            if el.properties.zone == Zone.EXTERIOR:
                continue
            habitable = rtype in HABITABLE
            needed = ceiling.min_clear_height_m if habitable else ceiling.min_clear_height_service_m
            if el.dimensions.height + TOLERANCE < needed:
                self.warn(
                    el,
                    "RULE_CEILING_HEIGHT",
                    "/dimensions/height",
                    f"{el.name}: clear height {el.dimensions.height} m is below {needed} m",
                    "ceiling.min_clear_height_m"
                    if habitable
                    else "ceiling.min_clear_height_service_m",
                )
        self._glazing()

    def _glazing(self) -> None:
        glazing: dict[uuid.UUID, float] = defaultdict(float)
        for el in self.model.elements:
            glazed = isinstance(el, Window) or (
                isinstance(el, Door) and el.properties.door_kind == DoorKind.SLIDING
            )
            if not glazed or not isinstance(el, Door | Window):
                continue
            located = self._opening_point(el)
            if located is None:
                continue
            host, p = located
            for room in self._rooms_at(host.level_id, p):
                glazing[room.id] += el.dimensions.width * el.dimensions.height
        ratio = self.profile.windows.min_glazing_to_floor_ratio
        for el in self.model.elements:
            if (
                not isinstance(el, Room)
                or not self.profile.room(el.properties.room_type).requires_window
            ):
                continue
            needed = ratio * el.dimensions.area
            if glazing[el.id] + TOLERANCE < needed:
                self.warn(
                    el,
                    "RULE_GLAZING_RATIO",
                    "",
                    f"{el.name}: {glazing[el.id]:.2f} m² of glazing, {needed:.2f} m² needed "
                    f"({ratio:.3f} of the floor area)",
                    "windows.min_glazing_to_floor_ratio",
                )

    # --- openings ---------------------------------------------------------------------------

    def openings(self) -> None:
        doors = self.profile.doors
        windows = self.profile.windows
        for el in self.model.elements:
            if isinstance(el, Door):
                kind = el.properties.door_kind
                if kind == DoorKind.GARAGE:
                    min_w, min_h = doors.garage.min_width_per_car_m, doors.garage.min_height_m
                    rule = "doors.garage"
                elif kind == DoorKind.ENTRANCE:
                    min_w, min_h, rule = (
                        doors.entrance.min_width_m,
                        doors.entrance.min_height_m,
                        "doors.entrance",
                    )
                else:
                    located = self._opening_point(el)
                    wet = located is not None and any(
                        r.properties.room_type in WET
                        for r in self._rooms_at(located[0].level_id, located[1])
                    )
                    door_rule = doors.bathroom if wet else doors.interior
                    min_w, min_h = door_rule.min_width_m, door_rule.min_height_m
                    rule = "doors.bathroom" if wet else "doors.interior"
                if el.dimensions.width + TOLERANCE < min_w:
                    self.warn(
                        el,
                        "RULE_DOOR_WIDTH",
                        "/dimensions/width",
                        f"{el.name}: {el.dimensions.width} m wide, {min_w} m required",
                        rule,
                    )
                if el.dimensions.height + TOLERANCE < min_h:
                    self.warn(
                        el,
                        "RULE_DOOR_HEIGHT",
                        "/dimensions/height",
                        f"{el.name}: {el.dimensions.height} m high, {min_h} m required",
                        rule,
                    )
            elif isinstance(el, Window):
                if el.dimensions.width + TOLERANCE < windows.min_width_m:
                    self.warn(
                        el,
                        "RULE_WINDOW_SIZE",
                        "/dimensions/width",
                        f"{el.name}: narrower than {windows.min_width_m} m",
                        "windows.min_width_m",
                    )
                if el.dimensions.height + TOLERANCE < windows.min_height_m:
                    self.warn(
                        el,
                        "RULE_WINDOW_SIZE",
                        "/dimensions/height",
                        f"{el.name}: lower than {windows.min_height_m} m",
                        "windows.min_height_m",
                    )
                level = self.levels.get(el.level_id) if el.level_id else None
                sill = el.position.z
                upper = level is not None and level.index > 0
                if upper and sill + TOLERANCE < windows.guard_required_below_sill_m:
                    self.warn(
                        el,
                        "RULE_WINDOW_GUARD",
                        "/position/z",
                        f"{el.name}: sill {sill} m on an upper floor needs a guard (below "
                        f"{windows.guard_required_below_sill_m} m)",
                        "windows.guard_required_below_sill_m",
                    )
                if sill + TOLERANCE < windows.min_sill_height_m:
                    self.warn(
                        el,
                        "RULE_WINDOW_SILL",
                        "/position/z",
                        f"{el.name}: sill below {windows.min_sill_height_m} m",
                        "windows.min_sill_height_m",
                    )

    # --- stairs and railings ----------------------------------------------------------------

    def stairs(self) -> None:
        s = self.profile.stairs
        for el in self.model.elements:
            if not isinstance(el, Stair):
                continue
            r, t = el.properties.riser_height, el.properties.tread_depth
            checks = [
                (
                    s.riser_m.min - TOLERANCE <= r <= s.riser_m.max + TOLERANCE,
                    "RULE_STAIR_RISER",
                    f"riser {r} m outside {s.riser_m.min}-{s.riser_m.max} m",
                    "stairs.riser_m",
                ),
                (
                    s.tread_m.min - TOLERANCE <= t <= s.tread_m.max + TOLERANCE,
                    "RULE_STAIR_TREAD",
                    f"tread {t} m outside {s.tread_m.min}-{s.tread_m.max} m",
                    "stairs.tread_m",
                ),
                (
                    s.comfort_rule.min - TOLERANCE <= 2 * r + t <= s.comfort_rule.max + TOLERANCE,
                    "RULE_STAIR_COMFORT",
                    f"2R+T = {2 * r + t:.3f} m outside {s.comfort_rule.min}-{s.comfort_rule.max}",
                    "stairs.comfort_rule",
                ),
                (
                    el.properties.risers <= s.max_risers_per_flight,
                    "RULE_STAIR_RISERS",
                    f"{el.properties.risers} risers in one flight (max {s.max_risers_per_flight})",
                    "stairs.max_risers_per_flight",
                ),
                (
                    el.dimensions.width + TOLERANCE >= s.min_width_m,
                    "RULE_STAIR_WIDTH",
                    f"width {el.dimensions.width} m below {s.min_width_m} m",
                    "stairs.min_width_m",
                ),
            ]
            for ok, code, message, rule in checks:
                if not ok:
                    self.warn(el, code, "/properties", f"{el.name}: {message}", rule)

    def railings(self) -> None:
        rules = self.profile.railings
        for el in self.model.elements:
            if not isinstance(el, Railing):
                continue
            rooms = [
                self.by_id.get(r.target_id)
                for r in el.relationships
                if r.kind == RelationshipKind.LOCATED_IN
            ]
            balcony = any(
                isinstance(r, Room)
                and r.properties.room_type in {RoomType.BALCONY, RoomType.TERRACE}
                for r in rooms
            )
            needed = rules.balcony_min_height_m if balcony else rules.min_height_m
            if el.dimensions.height + TOLERANCE < needed:
                self.warn(
                    el,
                    "RULE_RAILING_HEIGHT",
                    "/dimensions/height",
                    f"{el.name}: {el.dimensions.height} m high, {needed} m required",
                    "railings.balcony_min_height_m" if balcony else "railings.min_height_m",
                )


def check_model(model: BuildingModel, profile: BuildingRulesProfile) -> list[Issue]:
    """Rules findings (warnings) for `model` under `profile`."""
    evaluator = _Evaluator(model, profile)
    evaluator.rooms()
    evaluator.openings()
    evaluator.stairs()
    evaluator.railings()
    return evaluator.issues
