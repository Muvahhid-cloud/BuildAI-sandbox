"""Geometric invariants of a BuildingModel (Phase 3.5 K2.5, docs/building-model.md §4.1).

Pure geometry on the model as stored: hosting and placement of openings, walls, room
boundaries against walls, relationships against geometry, levels and stairs, slabs, roofs, and
whether the fixed dimensions of component types fit their hosts. Nothing here consults
architectural knowledge or a rules profile (enforceable minimums stay in rules/), and nothing
is corrected: every violation is reported with the constraint it breaks
(building/constraints.py) and the model is left as it is.

Tolerances are those of building/geometry.py. Two sampling distances are used to ask "which
room is there?" next to a door or a flight; they are probes, not requirements.
"""

import itertools
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence

from shapely import LineString, unary_union
from shapely import Point as ShapelyPoint
from shapely import Polygon as ShapelyPolygon
from shapely.geometry.base import BaseGeometry

from app.modules.building.axes import derive_axes
from app.modules.building.constraints import CONSTRAINTS
from app.modules.building.elements import (
    Door,
    Element,
    Furniture,
    Railing,
    Roof,
    Room,
    Slab,
    Stair,
    Wall,
    Window,
)
from app.modules.building.enums import RelationshipKind, RoofType, WallKind, Zone
from app.modules.building.geometry import (
    DERIVED_TOLERANCE,
    OVERLAP_AREA_TOLERANCE,
    Point,
    WallFrame,
    is_axis_aligned,
    is_untilted,
    polygon_edges,
    railing_line,
    roof_underside,
    segment_overlap_length,
    shared_boundary_length,
    signed_area,
    stair_point,
    stair_region,
    stair_rises_above,
    to_absolute,
    wall_axis,
    wall_frame,
)
from app.modules.building.hosting import junction_zones, opening_rise, opening_span, overlap
from app.modules.building.issues import Issue, Measure
from app.modules.building.model import BuildingModel, Level
from app.modules.building.primitives import EPS
from app.modules.building.types import DoorTypeParams

DOOR_SIDE_PROBE = 0.01  # m off the wall axis: which room lies on each side of a door
STAIR_END_PROBE = 0.1  # m beyond each end of a flight: where it is entered and left

# kind -> (allowed source element types, allowed target element types); docs/building-model.md
# §3.4. MEP kinds are reserved until their element types exist (Phase 6).
RELATIONSHIP_ENDS: dict[RelationshipKind, tuple[frozenset[str], frozenset[str]]] = {
    RelationshipKind.HOSTED_BY: (frozenset({"door", "window"}), frozenset({"wall"})),
    RelationshipKind.BOUNDS: (frozenset({"wall"}), frozenset({"room"})),
    RelationshipKind.ADJACENT_TO: (frozenset({"room"}), frozenset({"room"})),
    RelationshipKind.CONNECTS: (frozenset({"door"}), frozenset({"room"})),
    RelationshipKind.SUPPORTS: (frozenset({"wall"}), frozenset({"slab", "roof"})),
    RelationshipKind.LOCATED_IN: (
        frozenset({"furniture", "stair", "railing"}),
        frozenset({"room"}),
    ),
}


def _poly(points: Sequence[Point], holes: Sequence[Sequence[Point]] = ()) -> ShapelyPolygon | None:
    """A valid shapely polygon, or None (invalid polygons are reported by validation.py)."""
    if len(points) < 3 or signed_area(points) <= EPS:
        return None
    poly = ShapelyPolygon(points, list(holes))
    return poly if poly.is_valid else None


class _GeometryChecker:
    def __init__(self, model: BuildingModel) -> None:
        self.model = model
        self.issues: list[Issue] = []
        self.index = {el.id: i for i, el in enumerate(model.elements)}
        self.by_id: dict[uuid.UUID, Element] = {el.id: el for el in model.elements}
        self.levels: dict[uuid.UUID, Level] = {lvl.id: lvl for lvl in model.levels}
        self.all_walls = [el for el in model.elements if isinstance(el, Wall)]
        self.frames: dict[uuid.UUID, WallFrame] = {w.id: wall_frame(w) for w in self.all_walls}
        self.bodies: dict[uuid.UUID, ShapelyPolygon] = {
            w.id: ShapelyPolygon(self.frames[w.id].footprint()) for w in self.all_walls
        }
        self.room_polys: dict[uuid.UUID, tuple[Room, ShapelyPolygon]] = {}
        for el in model.elements:
            if isinstance(el, Room):
                poly = _poly(to_absolute(el.properties.boundary, el.position, el.rotation))
                if poly is not None:
                    self.room_polys[el.id] = (el, poly)
        self.slab_polys: dict[uuid.UUID, tuple[Slab, ShapelyPolygon]] = {}
        for el in model.elements:
            if isinstance(el, Slab):
                outline = to_absolute(el.properties.outline, el.position, el.rotation)
                holes = [to_absolute(h, el.position, el.rotation) for h in el.properties.holes]
                poly = _poly(outline, holes)
                if poly is not None:
                    self.slab_polys[el.id] = (el, poly)
        self.types = {t.id: t for t in model.types}

    # --- helpers --------------------------------------------------------------------------

    def add(
        self,
        constraint: str,
        el: Element | None,
        message: str,
        *,
        path: str | None = None,
        related: Iterable[uuid.UUID] = (),
        measure: Measure | None = None,
    ) -> None:
        c = CONSTRAINTS[constraint]
        if path is None:
            path = f"/elements/{self.index[el.id]}" if el is not None else ""
        self.issues.append(
            Issue(
                severity=c.severity,
                code=c.code,
                path=path,
                message=message,
                element_id=el.id if el is not None else None,
                constraint=c.id,
                related_ids=list(related),
                measure=measure,
            )
        )

    def path(self, el: Element, suffix: str) -> str:
        return f"/elements/{self.index[el.id]}{suffix}"

    def walls_on(self, level_id: uuid.UUID | None) -> list[Wall]:
        return [w for w in self.all_walls if w.level_id == level_id]

    def rooms_on(self, level_id: uuid.UUID | None) -> list[tuple[Room, ShapelyPolygon]]:
        return [(r, p) for r, p in self.room_polys.values() if r.level_id == level_id]

    def slabs_on(self, level_id: uuid.UUID | None) -> list[tuple[Slab, ShapelyPolygon]]:
        return [(s, p) for s, p in self.slab_polys.values() if s.level_id == level_id]

    def rooms_at(self, level_id: uuid.UUID | None, p: Point) -> list[Room]:
        pt = ShapelyPoint(p)
        return [r for r, poly in self.rooms_on(level_id) if poly.distance(pt) <= EPS]

    def elevation(self, level_id: uuid.UUID | None) -> float | None:
        level = self.levels.get(level_id) if level_id is not None else None
        return level.elevation if level is not None else None

    def host_of(self, el: Door | Window) -> Wall | None:
        hosts = [r.target_id for r in el.relationships if r.kind == RelationshipKind.HOSTED_BY]
        host = self.by_id.get(hosts[0]) if len(hosts) == 1 else None
        return host if isinstance(host, Wall) else None

    # --- 1. hosting and openings ----------------------------------------------------------

    def openings(self) -> None:
        by_host: dict[uuid.UUID, list[Door | Window]] = defaultdict(list)
        zones: dict[uuid.UUID, list[tuple[float, float]]] = {}
        for el in self.model.elements:
            if not isinstance(el, Door | Window):
                continue
            hosts = [r for r in el.relationships if r.kind == RelationshipKind.HOSTED_BY]
            kind = el.type
            if not hosts:
                self.add(
                    "host.exists",
                    el,
                    f"{el.name}: a {kind} needs a host wall (hosted_by relationship)",
                    path=self.path(el, "/relationships"),
                )
                continue
            if len(hosts) > 1:
                self.add(
                    "host.unique",
                    el,
                    f"{el.name} names {len(hosts)} hosts; a {kind} has exactly one",
                    path=self.path(el, "/relationships"),
                    related=[h.target_id for h in hosts],
                )
                continue
            host = self.by_id.get(hosts[0].target_id)
            if host is None:
                self.add(
                    "host.exists",
                    el,
                    f"{el.name}: host {hosts[0].target_id} does not exist",
                    path=self.path(el, "/relationships"),
                )
                continue
            if not isinstance(host, Wall):
                self.add(
                    "host.is_wall",
                    el,
                    f"{el.name} is hosted by {host.name}, a {host.type}; only walls host a {kind}",
                    path=self.path(el, "/relationships"),
                    related=[host.id],
                )
                continue
            by_host[host.id].append(el)
            self._placement(el, host)
            if host.id not in zones:
                frame = self.frames[host.id]
                zones[host.id] = junction_zones(
                    wall_axis(host),
                    (frame.v0, frame.v1),
                    [
                        (wall_axis(w), w.dimensions.thickness)
                        for w in self.walls_on(host.level_id)
                        if w.id != host.id
                    ],
                )
            span = opening_span(el)
            for lo, hi in zones[host.id]:
                inside = overlap(span, (lo, hi))
                if inside > EPS:
                    self.add(
                        "opening.clear_of_junctions",
                        el,
                        f"{el.name} reaches {inside:.3f} m into the junction of {host.name} with "
                        f"another wall ({lo:.3f}-{hi:.3f} m along the wall)",
                        path=self.path(el, "/position/x"),
                        related=[host.id],
                        measure=Measure(
                            quantity="junction_overlap",
                            actual=round(inside, 4),
                            limit=0.0,
                            unit="m",
                        ),
                    )
        for wall_id, items in by_host.items():
            items.sort(key=lambda o: (o.position.x, str(o.id)))
            for a, b in itertools.combinations(items, 2):
                shared = overlap(opening_span(a), opening_span(b))
                if shared > EPS:
                    self.add(
                        "opening.no_overlap",
                        b,
                        f"{a.name} and {b.name} overlap by {shared:.3f} m in "
                        f"{self.by_id[wall_id].name}",
                        path=self.path(b, "/position"),
                        related=[a.id, wall_id],
                        measure=Measure(
                            quantity="opening_overlap", actual=round(shared, 4), limit=0.0, unit="m"
                        ),
                    )

    def _placement(self, el: Door | Window, host: Wall) -> None:
        length, height = host.dimensions.length, host.dimensions.height
        if host.level_id != el.level_id:
            self.add(
                "host.same_level",
                el,
                f"{el.name} is not on the level of its host {host.name}",
                path=self.path(el, "/level_id"),
                related=[host.id],
            )
        r = el.rotation
        off_axis = abs(el.position.y) > EPS or max(abs(r.x), abs(r.y), abs(r.z)) > EPS
        if off_axis or (isinstance(el, Door) and abs(el.position.z) > EPS):
            self.add(
                "host.local_position",
                el,
                f"{el.name} is not placed in {host.name}'s wall coordinates "
                "(position.y and rotation must be 0; a door's position.z is 0)",
                path=self.path(el, "/position"),
                related=[host.id],
            )
        u0, u1 = opening_span(el)
        z0, z1 = opening_rise(el)
        if u0 < -EPS:
            self.add(
                "opening.within_length",
                el,
                f"{el.name} starts {-u0:.3f} m before the start of {host.name}",
                path=self.path(el, "/position/x"),
                related=[host.id],
                measure=Measure(quantity="opening_start", actual=u0, limit=0.0, unit="m"),
            )
        if u1 > length + EPS:
            self.add(
                "opening.within_length",
                el,
                f"{el.name} extends {u1 - length:.3f} m beyond the end of {host.name} "
                f"({u1:.3f} m of a {length:.3f} m wall)",
                path=self.path(el, "/dimensions/width"),
                related=[host.id],
                measure=Measure(
                    quantity="opening_end", actual=round(u1, 4), limit=length, unit="m"
                ),
            )
        if z0 < -EPS:
            self.add(
                "opening.above_base",
                el,
                f"{el.name} starts {-z0:.3f} m below the base of {host.name}",
                path=self.path(el, "/position/z"),
                related=[host.id],
                measure=Measure(quantity="opening_sill", actual=z0, limit=0.0, unit="m"),
            )
        if z1 > height + EPS:
            self.add(
                "opening.within_height",
                el,
                f"{el.name} reaches {z1:.3f} m, {host.name} is {height:.3f} m high",
                path=self.path(el, "/dimensions/height"),
                related=[host.id],
                measure=Measure(
                    quantity="opening_top", actual=round(z1, 4), limit=height, unit="m"
                ),
            )
        if isinstance(el, Door) and el.dimensions.thickness > host.dimensions.thickness + EPS:
            self.add(
                "opening.within_thickness",
                el,
                f"{el.name} is {el.dimensions.thickness:.3f} m thick, {host.name} only "
                f"{host.dimensions.thickness:.3f} m",
                path=self.path(el, "/dimensions/thickness"),
                related=[host.id],
                measure=Measure(
                    quantity="door_thickness",
                    actual=el.dimensions.thickness,
                    limit=host.dimensions.thickness,
                    unit="m",
                ),
            )
        t = self.types.get(el.type_ref) if el.type_ref else None
        if t is not None and isinstance(t.params, DoorTypeParams) and isinstance(el, Door):
            p = t.params
            for field, fixed, limit in (
                ("height", p.height, height),
                ("thickness", p.thickness, host.dimensions.thickness),
            ):
                if fixed > limit + EPS:
                    self.add(
                        "type.fits_host",
                        el,
                        f"{el.name}: its type {t.id} fixes the {field} at {fixed:.3f} m, which "
                        f"{host.name} ({limit:.3f} m) cannot accommodate",
                        path=self.path(el, "/type_ref"),
                        related=[host.id],
                        measure=Measure(
                            quantity=f"type_{field}", actual=fixed, limit=limit, unit="m"
                        ),
                    )

    # --- 2. walls -------------------------------------------------------------------------

    def walls(self) -> None:
        for w in self.all_walls:
            level = self.levels.get(w.level_id) if w.level_id else None
            if level and w.dimensions.height > level.height + EPS:
                self.add(
                    "wall.within_level_height",
                    w,
                    f"{w.name} is {w.dimensions.height:.3f} m high, taller than its level "
                    f"({level.height:.3f} m)",
                    path=self.path(w, "/dimensions/height"),
                    measure=Measure(
                        quantity="wall_height",
                        actual=w.dimensions.height,
                        limit=level.height,
                        unit="m",
                    ),
                )
            if not is_untilted(w.rotation) or not is_axis_aligned(w.rotation.z):
                self.add(
                    "wall.orientation",
                    w,
                    f"{w.name} must be vertical and run along x or y",
                    path=self.path(w, "/rotation"),
                )
        by_id = {w.id: w for w in self.all_walls}
        for axis in derive_axes(self.model):
            members = [by_id[i] for i in axis.wall_ids]
            for a, b in itertools.combinations(members, 2):
                if a.level_id != b.level_id:
                    continue
                shared = segment_overlap_length(wall_axis(a), wall_axis(b))
                if shared > EPS:
                    self.add(
                        "wall.no_overlap",
                        b,
                        f"{a.name} and {b.name} overlap by {shared:.3f} m along axis {axis.key}",
                        related=[a.id],
                        measure=Measure(
                            quantity="wall_overlap", actual=round(shared, 4), limit=0.0, unit="m"
                        ),
                    )
        for w in self.all_walls:
            if w.properties.wall_kind == WallKind.EXTERIOR:
                self._connected(w)
        self._on_slabs()

    def _connected(self, w: Wall) -> None:
        others = [o for o in self.walls_on(w.level_id) if o.id != w.id]
        for label, p in zip(("start", "end"), wall_axis(w), strict=True):
            joined = False
            for o in others:
                f = self.frames[o.id]
                u, v = f.local(p)
                if -EPS <= u <= f.length + EPS and f.v0 - EPS <= v <= f.v1 + EPS:
                    joined = True
                    break
            if not joined:
                self.add(
                    "wall.connected",
                    w,
                    f"The {label} of exterior wall {w.name} meets no other wall "
                    "(the envelope is open)",
                    path=self.path(w, "/position" if label == "start" else "/dimensions/length"),
                )

    def _on_slabs(self) -> None:
        support: dict[uuid.UUID | None, BaseGeometry] = {}
        for w in self.all_walls:
            if w.level_id not in support:
                support[w.level_id] = unary_union([p for _, p in self.slabs_on(w.level_id)])
            missing = self.bodies[w.id].difference(support[w.level_id]).area
            if missing > OVERLAP_AREA_TOLERANCE:
                self.add(
                    "wall.on_slab",
                    w,
                    f"{missing:.2f} m² of {w.name}'s footprint is not on a slab of its level",
                    path=self.path(w, "/position"),
                    measure=Measure(
                        quantity="unsupported_area", actual=round(missing, 4), limit=0.0, unit="m2"
                    ),
                )

    # --- 3. rooms, doors and relationships ------------------------------------------------

    def rooms(self) -> None:
        levels = {r.level_id for r, _ in self.room_polys.values()}
        for level_id in sorted(levels, key=str):
            rooms = self.rooms_on(level_id)
            walls = self.walls_on(level_id)
            bodies = unary_union([self.bodies[w.id] for w in walls]).buffer(EPS)
            holes = [
                LineString(list(ring.coords))
                for _, p in self.slabs_on(level_id)
                for ring in p.interiors
            ]
            base = unary_union([bodies, *[h.buffer(EPS) for h in holes]])
            indoor = [(r, p) for r, p in rooms if r.properties.zone != Zone.EXTERIOR]
            for room, poly in rooms:
                if room.properties.zone == Zone.EXTERIOR:
                    touching = poly.buffer(EPS).intersects(bodies) or any(
                        poly.buffer(EPS).intersects(p) for r, p in indoor if r.id != room.id
                    )
                    if not touching:
                        self.add(
                            "room.attached",
                            room,
                            f"{room.name} touches neither a wall nor an indoor room",
                        )
                    continue
                self._enclosed(room, poly, base, rooms)
                inner = poly.buffer(-EPS)
                for w in walls:
                    crossing = LineString(wall_axis(w)).intersection(inner).length
                    if crossing > EPS:
                        self.add(
                            "room.not_crossed",
                            room,
                            f"{w.name} runs {crossing:.3f} m through the inside of {room.name}",
                            path=self.path(room, "/properties/boundary"),
                            related=[w.id],
                            measure=Measure(
                                quantity="wall_inside_room",
                                actual=round(crossing, 4),
                                limit=0.0,
                                unit="m",
                            ),
                        )

    def _enclosed(
        self,
        room: Room,
        poly: ShapelyPolygon,
        base: BaseGeometry,
        rooms: list[tuple[Room, ShapelyPolygon]],
    ) -> None:
        others = [p.exterior.buffer(EPS) for r, p in rooms if r.id != room.id]
        coords = [(float(x), float(y)) for x, y in list(poly.exterior.coords)[:-1]]
        for a, b in polygon_edges(coords):
            rest = LineString([a, b]).difference(base)
            if rest.length > EPS:
                rest = rest.difference(unary_union([o for o in others if o.intersects(rest)]))
            if rest.length > EPS:
                x, y = rest.representative_point().coords[0]
                self.add(
                    "room.enclosed",
                    room,
                    f"{room.name}: {rest.length:.3f} m of its boundary near ({x:.2f}, {y:.2f}) "
                    "runs along no wall, room or slab opening",
                    path=self.path(room, "/properties/boundary"),
                    measure=Measure(
                        quantity="open_boundary", actual=round(rest.length, 4), limit=0.0, unit="m"
                    ),
                )

    def doors(self) -> None:
        for el in self.model.elements:
            if not isinstance(el, Door):
                continue
            host = self.host_of(el)
            if host is None:
                continue
            left, right = self.door_sides(el, host)
            exterior = host.properties.wall_kind == WallKind.EXTERIOR
            if (exterior and not (left or right)) or (not exterior and not (left and right)):
                side = "either side" if not (left or right) else "one side"
                self.add(
                    "door.opens_to_rooms",
                    el,
                    f"{el.name} in {host.name} opens to no room on {side}",
                    related=[host.id],
                )

    def door_sides(self, door: Door, host: Wall) -> tuple[list[Room], list[Room]]:
        f = self.frames[host.id]
        u = door.position.x + door.dimensions.width / 2
        left = f.v1 + DOOR_SIDE_PROBE if f.v1 > 0 else DOOR_SIDE_PROBE
        right = f.v0 - DOOR_SIDE_PROBE if f.v0 < 0 else -DOOR_SIDE_PROBE
        # Room boundaries run on wall axes, so probing just off the axis suffices; probing past
        # the faces as well keeps the answer right for off-centre (left/right aligned) walls.
        probes_left = [f.at(u, DOOR_SIDE_PROBE), f.at(u, left)]
        probes_right = [f.at(u, -DOOR_SIDE_PROBE), f.at(u, right)]

        def found(points: list[Point]) -> list[Room]:
            seen: dict[uuid.UUID, Room] = {}
            for p in points:
                for r in self.rooms_at(host.level_id, p):
                    seen[r.id] = r
            return [seen[k] for k in sorted(seen, key=str)]

        return found(probes_left), found(probes_right)

    def relationships(self) -> None:
        for el in self.model.elements:
            for j, rel in enumerate(el.relationships):
                target = self.by_id.get(rel.target_id)
                if target is None:
                    continue  # DANGLING_RELATIONSHIP (validation.py)
                ends = RELATIONSHIP_ENDS.get(rel.kind)
                path = self.path(el, f"/relationships/{j}")
                if ends is None:
                    self.add(
                        "relationship.kinds",
                        el,
                        f"{el.name}: {rel.kind} is reserved for MEP elements (Phase 6)",
                        path=path,
                        related=[target.id],
                    )
                    continue
                sources, targets = ends
                if el.type not in sources or (
                    target.type not in targets and rel.kind != RelationshipKind.HOSTED_BY
                ):
                    self.add(
                        "relationship.kinds",
                        el,
                        f"{el.name}: {rel.kind} cannot join a {el.type} to a {target.type}",
                        path=path,
                        related=[target.id],
                    )
                    continue
                reason = self._relationship_geometry(el, rel.kind, target)
                if reason is not None:
                    self.add(
                        "relationship.geometry",
                        el,
                        f"{el.name} {rel.kind} {target.name}, but {reason}",
                        path=path,
                        related=[target.id],
                    )

    def _relationship_geometry(
        self, el: Element, kind: RelationshipKind, target: Element
    ) -> str | None:
        room_entry = self.room_polys.get(target.id)
        if kind not in (
            RelationshipKind.BOUNDS,
            RelationshipKind.ADJACENT_TO,
            RelationshipKind.CONNECTS,
            RelationshipKind.LOCATED_IN,
        ):
            return None
        if room_entry is None:
            return None  # invalid room polygon: reported by validation.py
        room, poly = room_entry
        if room.level_id != el.level_id:
            return "they are on different levels"
        ring = [(float(x), float(y)) for x, y in list(poly.exterior.coords)[:-1]]
        if isinstance(el, Wall) and kind == RelationshipKind.BOUNDS:
            along = max(
                (segment_overlap_length(wall_axis(el), e) for e in polygon_edges(ring)),
                default=0.0,
            )
            return None if along > EPS else "the wall does not run along the room's boundary"
        if isinstance(el, Room) and kind == RelationshipKind.ADJACENT_TO:
            own = self.room_polys.get(el.id)
            if own is None:
                return None
            own_ring = [(float(x), float(y)) for x, y in list(own[1].exterior.coords)[:-1]]
            shared = shared_boundary_length(own_ring, ring)
            return None if shared > EPS else "the rooms share no boundary"
        if isinstance(el, Door) and kind == RelationshipKind.CONNECTS:
            host = self.host_of(el)
            if host is None:
                return None
            left, right = self.door_sides(el, host)
            f = self.frames[host.id]
            u0, u1 = opening_span(el)
            span = (f.at(u0), f.at(u1))
            along = max((segment_overlap_length(span, e) for e in polygon_edges(ring)), default=0.0)
            if room in left + right or along > EPS:
                return None
            return "the door does not open into that room"
        if isinstance(el, Furniture):
            inside = poly.buffer(EPS).covers(ShapelyPoint(el.position.x, el.position.y))
            return None if inside else "its base centre is outside the room"
        if isinstance(el, Stair):
            region = ShapelyPolygon(stair_region(el))
            inside = region.intersection(poly).area > OVERLAP_AREA_TOLERANCE
            return None if inside else "the flight does not stand in the room"
        if isinstance(el, Railing):
            (sx, sy), (ex, ey) = railing_line(el)
            inside = LineString([(sx, sy), (ex, ey)]).intersection(poly.buffer(EPS)).length > EPS
            return None if inside else "the railing does not run in the room"
        return None

    # --- 4. levels and stairs -------------------------------------------------------------

    def levels_and_stairs(self) -> None:
        ordered = sorted(enumerate(self.model.levels), key=lambda iv: iv[1].index)
        for n, (i, lvl) in enumerate(ordered):
            expected = 0.0 if n == 0 else ordered[n - 1][1].elevation + ordered[n - 1][1].height
            if abs(lvl.elevation - expected) > DERIVED_TOLERANCE:
                below = "" if n == 0 else f" ({ordered[n - 1][1].name} ends at {expected:.3f} m)"
                self.add(
                    "level.stacking",
                    None,
                    f"{lvl.name} is at {lvl.elevation:.3f} m, expected {expected:.3f} m{below}",
                    path=f"/levels/{i}/elevation",
                    measure=Measure(
                        quantity="level_elevation",
                        actual=lvl.elevation,
                        limit=round(expected, 4),
                        unit="m",
                    ),
                )
        for el in self.model.elements:
            if isinstance(el, Stair):
                self._stair(el)

    def _stair(self, stair: Stair) -> None:
        if not is_untilted(stair.rotation) or not is_axis_aligned(stair.rotation.z):
            self.add(
                "stair.orientation",
                stair,
                f"{stair.name} must be untilted and run along x or y",
                path=self.path(stair, "/rotation"),
            )
            return
        region = ShapelyPolygon(stair_region(stair))
        rooms = self.rooms_on(stair.level_id)
        outside = region.difference(unary_union([p for _, p in rooms]).buffer(EPS)).area
        if outside > OVERLAP_AREA_TOLERANCE:
            self.add(
                "stair.in_rooms",
                stair,
                f"{outside:.2f} m² of {stair.name} lies outside the rooms of its level",
                path=self.path(stair, "/position"),
                measure=Measure(
                    quantity="area_outside_rooms", actual=round(outside, 4), limit=0.0, unit="m2"
                ),
            )
        for w in self.walls_on(stair.level_id):
            clash = region.intersection(self.bodies[w.id]).area
            if clash > OVERLAP_AREA_TOLERANCE:
                self.add(
                    "stair.clear_of_walls",
                    stair,
                    f"{stair.name} cuts {clash:.2f} m² into {w.name}",
                    path=self.path(stair, "/position"),
                    related=[w.id],
                    measure=Measure(
                        quantity="wall_intersection", actual=round(clash, 4), limit=0.0, unit="m2"
                    ),
                )
        p = stair.properties
        base = self.elevation(stair.level_id)
        top = self.elevation(p.to_level_id)
        if base is None or top is None or p.from_level_id not in self.levels:
            return  # STAIR_LEVELS (validation.py)
        start = stair_point(stair, -STAIR_END_PROBE)
        end = stair_point(stair, stair.dimensions.run_length + STAIR_END_PROBE)
        for label, level_id, point in (
            ("starts", p.from_level_id, start),
            ("arrives", p.to_level_id, end),
        ):
            if not self.rooms_at(level_id, point):
                self.add(
                    "stair.access",
                    stair,
                    f"{stair.name} {label} at ({point[0]:.2f}, {point[1]:.2f}), outside every "
                    f"room of {self.levels[level_id].name}",
                    path=self.path(stair, "/position"),
                )
        floor = base + stair.position.z
        for slab, poly in self.slabs_on(p.to_level_id):
            underside = top + slab.position.z - slab.dimensions.thickness - floor
            x0 = stair_rises_above(stair, underside)
            if x0 is None:
                continue
            high = ShapelyPolygon(stair_region(stair, x0))
            clash = high.intersection(poly).area
            if clash > OVERLAP_AREA_TOLERANCE:
                self.add(
                    "stair.slab_opening",
                    stair,
                    f"{stair.name} rises through {slab.name} outside its openings "
                    f"({clash:.2f} m² of flight above the slab underside)",
                    path=self.path(stair, "/position"),
                    related=[slab.id],
                    measure=Measure(
                        quantity="flight_in_slab", actual=round(clash, 4), limit=0.0, unit="m2"
                    ),
                )

    # --- 5. slabs and roofs ---------------------------------------------------------------

    def slabs(self) -> None:
        by_level: dict[uuid.UUID | None, list[tuple[Slab, ShapelyPolygon]]] = defaultdict(list)
        for slab, poly in self.slab_polys.values():
            by_level[slab.level_id].append((slab, poly))
        for items in by_level.values():
            for (a, pa), (b, pb) in itertools.combinations(items, 2):
                shared = pa.intersection(pb).area
                if shared > OVERLAP_AREA_TOLERANCE:
                    self.add(
                        "slab.no_overlap",
                        b,
                        f"{a.name} and {b.name} overlap by {shared:.2f} m²",
                        related=[a.id],
                        measure=Measure(
                            quantity="slab_overlap", actual=round(shared, 4), limit=0.0, unit="m2"
                        ),
                    )
        for w in self.all_walls:
            top = self._wall_top(w)
            for rel in w.relationships:
                target = self.by_id.get(rel.target_id)
                if rel.kind != RelationshipKind.SUPPORTS or not isinstance(target, Slab):
                    continue
                entry = self.slab_polys.get(target.id)
                slab_z = self.elevation(target.level_id)
                if entry is None or top is None or slab_z is None:
                    continue
                shell = ShapelyPolygon(entry[1].exterior)
                outside = self.bodies[w.id].difference(shell).area
                if outside > OVERLAP_AREA_TOLERANCE:
                    self.add(
                        "support.slab",
                        target,
                        f"{w.name} supports {target.name} but {outside:.2f} m² of it lies "
                        "outside the slab",
                        related=[w.id],
                    )
                underside = slab_z + target.position.z - target.dimensions.thickness
                if abs(underside - top) > DERIVED_TOLERANCE:
                    self.add(
                        "support.slab",
                        target,
                        f"{w.name} supports {target.name} but its top ({top:.3f} m) does not "
                        f"meet the slab's underside ({underside:.3f} m)",
                        related=[w.id],
                        measure=Measure(
                            quantity="wall_top",
                            actual=round(top, 4),
                            limit=round(underside, 4),
                            unit="m",
                        ),
                    )

    def _wall_top(self, w: Wall) -> float | None:
        z = self.elevation(w.level_id)
        return None if z is None else z + w.position.z + w.dimensions.height

    def roofs(self) -> None:
        supports: dict[uuid.UUID, list[Wall]] = defaultdict(list)
        for w in self.all_walls:
            for rel in w.relationships:
                if rel.kind == RelationshipKind.SUPPORTS and isinstance(
                    self.by_id.get(rel.target_id), Roof
                ):
                    supports[rel.target_id].append(w)
        for el in self.model.elements:
            if isinstance(el, Roof):
                self._roof(el, supports.get(el.id, []))

    def _roof(self, roof: Roof, walls: list[Wall]) -> None:
        pr = roof.properties
        flat = pr.roof_type == RoofType.FLAT
        problems = []
        if not is_untilted(roof.rotation):
            problems.append("roofs are untilted")
        if flat and pr.pitch_deg > 0:
            problems.append("a flat roof has no pitch")
        if not flat and pr.pitch_deg <= 0:
            problems.append(f"a {pr.roof_type} roof needs a pitch")
        if not flat and pr.parapet_height > 0:
            problems.append("parapets belong to flat roofs")
        for problem in problems:
            self.add(
                "roof.shape", roof, f"{roof.name}: {problem}", path=self.path(roof, "/properties")
            )
        if not walls:
            self.add("roof.supported", roof, f"No wall supports {roof.name}")
            return
        outline = _poly(to_absolute(pr.outline, roof.position, roof.rotation))
        level_z = self.elevation(roof.level_id)
        if outline is None or level_z is None:
            return
        ids = [w.id for w in walls]
        for w in walls:
            outside = self.bodies[w.id].difference(outline).area
            if outside > OVERLAP_AREA_TOLERANCE:
                self.add(
                    "roof.covers_supports",
                    roof,
                    f"{roof.name} does not cover {w.name} ({outside:.2f} m² outside the outline)",
                    path=self.path(roof, "/properties/outline"),
                    related=[w.id],
                )
        # Overhang: outline bounds minus the supporting walls' outer bounds, per side.
        bx0, by0, bx1, by1 = unary_union([self.bodies[i] for i in ids]).bounds
        ox0, oy0, ox1, oy1 = outline.bounds
        over = roof.dimensions.overhang
        for side, actual in (
            ("west", bx0 - ox0),
            ("south", by0 - oy0),
            ("east", ox1 - bx1),
            ("north", oy1 - by1),
        ):
            if abs(actual - over) > DERIVED_TOLERANCE:
                self.add(
                    "roof.overhang",
                    roof,
                    f"{roof.name} overhangs its walls by {actual:.3f} m on the {side}, "
                    f"declared {over:.3f} m",
                    path=self.path(roof, "/dimensions/overhang"),
                    related=ids,
                    measure=Measure(
                        quantity=f"overhang_{side}", actual=round(actual, 4), limit=over, unit="m"
                    ),
                )
        # Bearing: underside >= wall top over every wall, and = at the lowest contact.
        lowest: float | None = None
        for w in walls:
            top = self._wall_top(w)
            if top is None:
                continue
            corners = list(self.bodies[w.id].exterior.coords)[:-1]
            under = level_z + min(roof_underside(roof, (x, y)) for x, y in corners)
            gap = under - top
            lowest = gap if lowest is None else min(lowest, gap)
            if gap < -DERIVED_TOLERANCE:
                self.add(
                    "support.roof",
                    roof,
                    f"{roof.name} cuts {-gap:.3f} m into {w.name}",
                    related=[w.id],
                    measure=Measure(quantity="roof_gap", actual=round(gap, 4), limit=0.0, unit="m"),
                )
        if lowest is not None and lowest > DERIVED_TOLERANCE:
            self.add(
                "support.roof",
                roof,
                f"{roof.name} floats {lowest:.3f} m above the walls that support it",
                related=ids,
                measure=Measure(quantity="roof_gap", actual=round(lowest, 4), limit=0.0, unit="m"),
            )


def check_geometry(model: BuildingModel) -> list[Issue]:
    """Geometric findings for `model` (errors and warnings; see building/constraints.py)."""
    checker = _GeometryChecker(model)
    checker.openings()
    checker.walls()
    checker.rooms()
    checker.doors()
    checker.relationships()
    checker.levels_and_stairs()
    checker.slabs()
    checker.roofs()
    return checker.issues
