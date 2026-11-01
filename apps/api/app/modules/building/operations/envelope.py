"""Facade edits (Phase 3.6 D2.5): move an exterior wall, or change its thickness, with the
envelope it carries.

A *facade* is the exterior wall on one straight line together with the walls on the same line
on the other storeys (stacked walls): they move together, so storeys stay aligned. Pure geometry
on the model, no layout engine:

- Walls: each storey's facade wall moves with `walls.shift_wall` (corner walls stretch or
  shrink, interior walls ending on it follow, room edges along it move, openings stay
  host-relative, furniture against it moves).
- Slabs and roofs: their outline edges on the facade's outer face line (roofs: the outer face
  plus their overhang) move with it, so footprint, floor slabs, roof planes, eaves, overhangs
  and parapets are recomputed from the new envelope. A pitched roof must stay a rectangle.
- What hangs on the facade outside it — balconies and terraces (their rooms, slabs, railings
  and furniture) and the entrance canopy — moves with it unchanged.

Refused with the reason (`OperationRejected`), never approximated:
`FACADE_CONTINUES` (another exterior wall continues the facade in line: moving part of a facade
would need a step in the envelope), `FACADE_STOREYS_DIFFER` (the walls on this line differ
between storeys), `VOLUME_ATTACHED` (another volume — a garage or a wing — joins this facade),
`FACADE_CUTS_STAIR` (the facade would run through a stair), `ROOF_CANNOT_FORM` (a pitched roof
would stop being a rectangle), `ENVELOPE_INVALID` (a slab or roof outline would fold) and, for
thickness, `BALCONY_ATTACHED` (a balcony/terrace slab starts at the outer face). Everything else
(room minimums, clear widths, reachability, slabs under walls, roof support) is judged by the
model validators and the rules profile in the editing service.
"""

import math
import uuid
from dataclasses import dataclass

from shapely.geometry import LineString
from shapely.geometry import Polygon as ShapelyPolygon

from app.modules.building.elements import (
    Element,
    Furniture,
    Railing,
    Roof,
    Room,
    Slab,
    Stair,
    Wall,
)
from app.modules.building.enums import Origin, RelationshipKind, RoofType, SlabKind, WallKind, Zone
from app.modules.building.geometry import (
    Point,
    is_axis_aligned_rectangle,
    railing_line,
    signed_area,
    stair_region,
    to_absolute,
    wall_axis,
)
from app.modules.building.model import BuildingModel
from app.modules.building.operations.relationships import refresh_level_relationships, room_ring
from app.modules.building.operations.schemas import OperationRejected
from app.modules.building.operations.walls import shift_wall
from app.modules.building.primitives import EPS, Vec2

#: Overlap of a moved facade with a stair flight that counts as cutting it (m²).
STAIR_CLASH_M2 = 0.01


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _param(p: Point, a: Point, u: Point) -> float:
    return _dot((p[0] - a[0], p[1] - a[1]), u)


def _off(p: Point, a: Point, u: Point) -> float:
    """Signed distance of p from the line through a along u (+ = left of u)."""
    return -(p[0] - a[0]) * u[1] + (p[1] - a[1]) * u[0]


def _round_pt(p: Point) -> Point:
    return (round(p[0], 3) + 0.0, round(p[1], 3) + 0.0)


@dataclass(frozen=True)
class Facade:
    """The exterior walls on one line, one per storey (lowest level first)."""

    walls: tuple[Wall, ...]
    a: Point  # axis start of the reference wall
    u: Point  # axis direction
    length: float
    thickness: float

    @property
    def out(self) -> Point:
        """Unit vector to the outside (the right face of a counter-clockwise exterior wall)."""
        return (self.u[1], -self.u[0])

    @property
    def level_ids(self) -> set[uuid.UUID | None]:
        return {w.level_id for w in self.walls}

    def name(self) -> str:
        return " / ".join(w.name for w in self.walls)


def _parallel(u: Point, v: Point) -> bool:
    return abs(u[0] * v[1] - u[1] * v[0]) < 1e-6


def _unit(wall: Wall) -> Point:
    return (math.cos(wall.rotation.z), math.sin(wall.rotation.z))


def facade_of(model: BuildingModel, wall: Wall) -> Facade:
    """The facade `wall` belongs to, or why it cannot be edited as one."""
    a, _ = wall_axis(wall)
    u = _unit(wall)
    length = wall.dimensions.length
    t = wall.dimensions.thickness
    elevation = {lvl.id: lvl.elevation for lvl in model.levels}
    exterior = sorted(
        (
            e
            for e in model.elements
            if isinstance(e, Wall) and e.properties.wall_kind == WallKind.EXTERIOR
        ),
        key=lambda w: (elevation.get(w.level_id, 0.0) if w.level_id else 0.0, str(w.id)),
    )
    stack: list[Wall] = []
    for w in exterior:
        wa, wb = wall_axis(w)
        if not _parallel(_unit(w), u) or abs(_off(wa, a, u)) > EPS:
            continue
        lo, hi = sorted((_param(wa, a, u), _param(wb, a, u)))
        if hi <= EPS or lo >= length - EPS:
            continue  # on the line but beside the facade (checked below)
        same_level = w.level_id == wall.level_id
        if abs(lo) > EPS or abs(hi - length) > EPS:
            if same_level and w.id != wall.id:
                raise OperationRejected(
                    "FACADE_CONTINUES",
                    f"{w.name} overlaps {wall.name} on the same line; this facade cannot be "
                    "moved as one.",
                    element_id=wall.id,
                    related_ids=[w.id],
                )
            raise OperationRejected(
                "FACADE_STOREYS_DIFFER",
                f"{w.name} on another storey runs along the same facade line as {wall.name} "
                "but not over the same length; storeys must stay aligned, so this facade "
                "cannot be moved or changed as one.",
                element_id=wall.id,
                related_ids=[w.id],
            )
        if abs(w.dimensions.thickness - t) > EPS:
            raise OperationRejected(
                "FACADE_STOREYS_DIFFER",
                f"{w.name} and {wall.name} are on the same facade line with different "
                "thicknesses; change them to one thickness first.",
                element_id=wall.id,
                related_ids=[w.id],
            )
        if any(s.level_id == w.level_id for s in stack):
            raise OperationRejected(
                "FACADE_STOREYS_DIFFER",
                f"Two exterior walls of one storey lie on the line of {wall.name}.",
                element_id=wall.id,
                related_ids=[w.id],
            )
        stack.append(w)
    facade = Facade(tuple(stack), a, u, length, t)
    levels = facade.level_ids
    ids = {w.id for w in stack}
    for w in stack:
        for end in wall_axis(w):
            corner = any(
                o.level_id == w.level_id
                and o.id not in ids
                and not _parallel(_unit(o), u)
                and any(math.dist(end, p) < EPS for p in wall_axis(o))
                for o in exterior
            )
            if not corner:
                raise OperationRejected(
                    "VOLUME_ATTACHED",
                    f"{w.name} ends against another volume (a garage or a wing) instead of at "
                    "a corner of the envelope; moving or thickening it is not supported. Edit "
                    "a facade that ends at corners.",
                    element_id=wall.id,
                    related_ids=[w.id],
                )
    for w in exterior:
        if w.level_id not in levels or w.id in ids:
            continue
        wa, wb = wall_axis(w)
        if _parallel(_unit(w), u) and abs(_off(wa, a, u)) <= EPS:
            raise OperationRejected(
                "FACADE_CONTINUES",
                f"{w.name} continues the facade of {wall.name} in line. Moving or thickening "
                "only part of a facade would need a step in the envelope; edit a facade that "
                "ends at corners on every storey.",
                element_id=wall.id,
                related_ids=[w.id],
            )
        for p in (wa, wb):
            along = _param(p, a, u)
            off = _off(p, a, u)
            on_axis_inside = abs(off) <= EPS and EPS < along < length - EPS
            on_outer_face = (
                abs(off + t / 2) <= EPS and -t / 2 - EPS <= along <= length + t / 2 + EPS
            )
            if on_axis_inside or on_outer_face:
                raise OperationRejected(
                    "VOLUME_ATTACHED",
                    f"{w.name} of another volume (a garage or a wing) joins the facade of "
                    f"{wall.name}; moving or thickening a facade another volume is built "
                    "against is not supported. Edit another facade.",
                    element_id=wall.id,
                    related_ids=[w.id],
                )
    return facade


@dataclass
class Attachments:
    """What hangs on the facade outside it and moves with it unchanged."""

    rooms: list[Room]
    slabs: list[Slab]  # balcony/terrace slabs and canopies
    railings: list[Railing]
    furniture: list[Furniture]

    @property
    def ids(self) -> set[uuid.UUID]:
        return {e.id for e in [*self.rooms, *self.slabs, *self.railings, *self.furniture]}

    @property
    def outdoor(self) -> list[Element]:
        """Balconies and terraces (not canopies)."""
        return [
            *self.rooms,
            *[s for s in self.slabs if s.properties.slab_kind != SlabKind.CANOPY],
        ]


def _outer_segment(f: Facade, extra: float = 0.0) -> LineString:
    off = f.thickness / 2 + extra
    lo, hi = -off, f.length + off
    p0 = (f.a[0] + lo * f.u[0] + off * f.out[0], f.a[1] + lo * f.u[1] + off * f.out[1])
    p1 = (f.a[0] + hi * f.u[0] + off * f.out[0], f.a[1] + hi * f.u[1] + off * f.out[1])
    return LineString([p0, p1])


def attachments(model: BuildingModel, f: Facade) -> Attachments:
    levels = f.level_ids
    outer = _outer_segment(f)
    axis = LineString([f.a, (f.a[0] + f.length * f.u[0], f.a[1] + f.length * f.u[1])])
    rooms: list[Room] = []
    slabs: list[Slab] = []
    shapes: list[ShapelyPolygon] = []
    for el in model.elements:
        if el.level_id not in levels:
            continue
        if isinstance(el, Room) and el.properties.zone == Zone.EXTERIOR:
            ring = room_ring(el)
            poly = ShapelyPolygon(ring)
            if _off(_centroid(poly), f.a, f.u) < 0 and poly.exterior.distance(axis) < EPS:
                rooms.append(el)
                shapes.append(poly)
        elif isinstance(el, Slab):
            ring = to_absolute(el.properties.outline, el.position, el.rotation)
            poly = ShapelyPolygon(ring)
            outside = _off(_centroid(poly), f.a, f.u) < -f.thickness / 2
            if outside and poly.exterior.distance(outer) < EPS:
                slabs.append(el)
                shapes.append(poly)
    room_ids = {r.id for r in rooms}
    railings = [
        el
        for el in model.elements
        if isinstance(el, Railing)
        and el.level_id in levels
        and any(
            s.buffer(0.05).contains(LineString(railing_line(el)).interpolate(0.5, normalized=True))
            for s in shapes
        )
    ]
    furniture = [
        el
        for el in model.elements
        if isinstance(el, Furniture)
        and any(
            r.kind == RelationshipKind.LOCATED_IN and r.target_id in room_ids
            for r in el.relationships
        )
    ]
    return Attachments(rooms, slabs, railings, furniture)


def _centroid(poly: ShapelyPolygon) -> Point:
    c = poly.centroid
    return (c.x, c.y)


def _shift_outline(
    ring: list[Point], f: Facade, off: float, lo: float, hi: float, m: Point, name: str
) -> list[Point] | None:
    """Move the parts of `ring` that lie on the line `off` outside the facade axis, between
    params lo..hi, by m. None if no edge lies on that line."""
    target = -off  # _off is + to the left; outside is to the right
    out: list[Point] = []
    touched = False
    for i, p in enumerate(ring):
        q = ring[(i + 1) % len(ring)]
        out.append(p)
        if abs(_off(p, f.a, f.u) - target) > EPS or abs(_off(q, f.a, f.u) - target) > EPS:
            continue
        tp, tq = _param(p, f.a, f.u), _param(q, f.a, f.u)
        a0, a1 = max(min(tp, tq), lo), min(max(tp, tq), hi)
        if a1 - a0 <= EPS:
            continue
        touched = True
        first, second = (a0, a1) if tp < tq else (a1, a0)
        base = (f.a[0] + f.out[0] * off, f.a[1] + f.out[1] * off)
        x0 = (base[0] + first * f.u[0], base[1] + first * f.u[1])
        x1 = (base[0] + second * f.u[0], base[1] + second * f.u[1])
        out += [x0, (x0[0] + m[0], x0[1] + m[1]), (x1[0] + m[0], x1[1] + m[1]), x1]
    if not touched:
        return None
    pts = [_round_pt(p) for p in out]
    changed = True
    while changed and len(pts) >= 3:
        changed = False
        n = len(pts)
        for i in range(n):
            prev, cur, nxt = pts[i - 1], pts[i], pts[(i + 1) % n]
            d1 = (cur[0] - prev[0], cur[1] - prev[1])
            d2 = (nxt[0] - cur[0], nxt[1] - cur[1])
            if math.dist(prev, cur) < EPS or abs(d1[0] * d2[1] - d1[1] * d2[0]) < EPS:
                pts = pts[:i] + pts[i + 1 :]
                changed = True
                break
    area = signed_area(pts)
    if len(pts) < 3 or not ShapelyPolygon(pts).is_valid or (area > 0) != (signed_area(ring) > 0):
        raise OperationRejected(
            "ENVELOPE_INVALID", f"The outline of {name} would fold over itself."
        )
    return pts


def _relative(points: list[Point], el: Slab | Roof) -> list[Vec2]:
    c, s = math.cos(el.rotation.z), math.sin(el.rotation.z)
    px, py = el.position.x, el.position.y
    return [
        Vec2(
            x=round((x - px) * c + (y - py) * s, 3) + 0.0,
            y=round(-(x - px) * s + (y - py) * c, 3) + 0.0,
        )
        for x, y in points
    ]


def _reshape_envelope(
    elements: list[Element], f: Facade, m: Point, skip: set[uuid.UUID], *, face_shift: float
) -> list[Element]:
    """Slab and roof outline edges on the facade's outer face line (roofs: + overhang) move by
    m. `face_shift` is how far that line itself was from the axis before (t/2)."""
    supported = {
        r.target_id for w in f.walls for r in w.relationships if r.kind == RelationshipKind.SUPPORTS
    }
    out: list[Element] = []
    for el in elements:
        if el.id in skip:
            out.append(el)
            continue
        if isinstance(el, Slab) and el.properties.slab_kind != SlabKind.CANOPY:
            off = face_shift
            ring = to_absolute(el.properties.outline, el.position, el.rotation)
            moved = _shift_outline(ring, f, off, -off, f.length + off, m, el.name)
            if moved is None:
                out.append(el)
                continue
            holes = [to_absolute(h, el.position, el.rotation) for h in el.properties.holes]
            shell = ShapelyPolygon(moved)
            for hole in holes:
                if not shell.buffer(EPS).contains(ShapelyPolygon(hole)):
                    raise OperationRejected(
                        "FACADE_CUTS_STAIR",
                        f"The facade {f.name()} would cut through the stair opening in "
                        f"{el.name}. Move it less, or the other way.",
                        element_id=f.walls[0].id,
                        related_ids=[el.id],
                    )
            area = ShapelyPolygon(moved, holes).area
            out.append(
                el.model_copy(
                    update={
                        "properties": el.properties.model_copy(
                            update={"outline": _relative(moved, el)}
                        ),
                        "dimensions": el.dimensions.model_copy(
                            update={"area": round(area, 2) + 0.0}
                        ),
                    }
                )
            )
        elif isinstance(el, Roof) and el.id in supported:
            off = face_shift + el.dimensions.overhang
            ring = to_absolute(el.properties.outline, el.position, el.rotation)
            moved = _shift_outline(ring, f, off, -off, f.length + off, m, el.name)
            if moved is None:
                raise OperationRejected(
                    "ROOF_CANNOT_FORM",
                    f"{el.name} does not follow the facade of {f.name()}: its eaves do not run "
                    "along it, so the roof cannot be re-formed for this move.",
                    element_id=f.walls[0].id,
                    related_ids=[el.id],
                )
            pitched = el.properties.roof_type != RoofType.FLAT
            if pitched and not is_axis_aligned_rectangle(moved):
                raise OperationRejected(
                    "ROOF_CANNOT_FORM",
                    f"{el.name} is a {el.properties.roof_type.value} roof, which needs a "
                    "rectangular outline; the facade move would break that.",
                    element_id=f.walls[0].id,
                    related_ids=[el.id],
                )
            out.append(
                el.model_copy(
                    update={
                        "properties": el.properties.model_copy(
                            update={"outline": _relative(moved, el)}
                        )
                    }
                )
            )
        else:
            out.append(el)
    return out


def _translate(el: Element, m: Point) -> Element:
    x, y = _round_pt((el.position.x + m[0], el.position.y + m[1]))
    return el.model_copy(update={"position": el.position.model_copy(update={"x": x, "y": y})})


def _check_stairs(model: BuildingModel, f: Facade, m: Point) -> None:
    h = f.thickness / 2
    body = ShapelyPolygon(
        [
            (
                f.a[0] + m[0] + s * f.length * f.u[0] + o * f.out[0],
                f.a[1] + m[1] + s * f.length * f.u[1] + o * f.out[1],
            )
            for s, o in ((0, -h), (1, -h), (1, h), (0, h))
        ]
    )
    for el in model.elements:
        if isinstance(el, Stair) and el.level_id in f.level_ids:
            clash = body.intersection(ShapelyPolygon(stair_region(el))).area
            if clash > STAIR_CLASH_M2:
                raise OperationRejected(
                    "FACADE_CUTS_STAIR",
                    f"The facade {f.name()} would run through {el.name}. Move it less, or the "
                    "other way.",
                    element_id=f.walls[0].id,
                    related_ids=[el.id],
                )


def move_facade(model: BuildingModel, wall: Wall, delta: float) -> BuildingModel:
    """`move_wall` on an exterior wall: the facade moves on every storey, the envelope follows."""
    f = facade_of(model, wall)
    n = (-f.u[1], f.u[0])  # left normal: + offsets move the wall this way (inwards)
    m = (delta * n[0], delta * n[1])
    _check_stairs(model, f, m)
    att = attachments(model, f)
    current = model
    skip_rooms = frozenset(r.id for r in att.rooms)
    for w in f.walls:
        stacked = next(e for e in current.elements if e.id == w.id)
        if not isinstance(stacked, Wall):  # pragma: no cover - ids are walls by construction
            raise OperationRejected("WALL_NOT_FOUND", f"{w.name} is no longer in this design.")
        current = shift_wall(current, stacked, delta, skip_rooms=skip_rooms)
    moved_ids = att.ids
    elements = [_translate(el, m) if el.id in moved_ids else el for el in current.elements]
    elements = _reshape_envelope(elements, f, m, moved_ids, face_shift=f.thickness / 2)
    for level_id in sorted(f.level_ids, key=str):
        elements = refresh_level_relationships(elements, level_id)
    return current.model_copy(update={"elements": elements})


def set_facade_thickness(model: BuildingModel, wall: Wall, thickness: float) -> BuildingModel:
    """`set_wall_thickness` on an exterior wall: every storey of the facade, the outer face (and
    the slab and roof edges on it, and the canopy) moves out by half the change."""
    f = facade_of(model, wall)
    att = attachments(model, f)
    if att.outdoor:
        hanging = att.outdoor[0]
        raise OperationRejected(
            "BALCONY_ATTACHED",
            f"{hanging.name} hangs on the facade of {wall.name}; its slab and railings start at "
            "the wall's outer face. Change the thickness of a facade without a balcony or "
            "terrace.",
            element_id=wall.id,
            related_ids=[hanging.id],
        )
    dt = round(thickness - f.thickness, 3)
    m = (f.out[0] * dt / 2, f.out[1] * dt / 2)
    ids = {w.id for w in f.walls}
    canopies = {s.id for s in att.slabs}
    elements: list[Element] = []
    for el in model.elements:
        if el.id in ids and isinstance(el, Wall):
            el = el.model_copy(
                update={
                    "dimensions": el.dimensions.model_copy(update={"thickness": thickness}),
                    "origin": Origin.USER,
                }
            )
        elif el.id in canopies:
            el = _translate(el, m)
        elements.append(el)
    elements = _reshape_envelope(elements, f, m, canopies, face_shift=f.thickness / 2)
    return model.model_copy(update={"elements": elements})
