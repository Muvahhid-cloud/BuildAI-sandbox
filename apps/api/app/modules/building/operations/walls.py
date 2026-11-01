"""`move_wall`: shift an interior wall sideways and keep the plan consistent around it.

Geometry (all on the wall's level; walls are axis-aligned in v1):

- The wall's axis A→B moves by m = offset · n (n = left normal). Its length, openings and their
  offsets do not change.
- At each end E of the wall:
  * E against the side of another wall (a T-junction into it): the end slides along that wall;
    it must stay on it.
  * E is a joint in a straight line of walls (another wall continues the line): the moved wall
    steps out of the line, and a short "jog" wall from E to E+m closes the gap, unless a wall
    already runs from E in the direction of the move.
  * otherwise (corner or T where the moved wall is the through-wall): the walls ending at E
    follow, stretching or shrinking along their own axis.
- Walls that end on the moved wall (T-junctions into its side) follow the same way.
- Rooms: every boundary edge that runs along the moved wall moves with it; where an edge runs
  along it only in part, the boundary steps (two new vertices). Areas and perimeters are
  recomputed from the new boundaries.
- Openings in walls that stretch at their start keep their absolute position (offsets adjust).
- Furniture standing against the wall (within 10 cm of either face, along its length) moves
  with it.
- `bounds` / `adjacent_to` are recomputed for the level (relationships.py).

Anything the operation cannot express is refused with an explanation (`OperationRejected`);
everything else — minimum sizes, openings in junctions, stairs, reachability — is judged by the
model validators and the rules profile in the editing service, never here.
"""

import math
import uuid

from shapely.geometry import Polygon as ShapelyPolygon

from app.modules.building.elements import Element, Furniture, Room, Wall
from app.modules.building.enums import Origin, WallKind
from app.modules.building.geometry import (
    Point,
    is_axis_aligned,
    perimeter,
    signed_area,
    wall_axis,
)
from app.modules.building.model import BuildingModel
from app.modules.building.operations.relationships import refresh_level_relationships, room_ring
from app.modules.building.operations.schemas import MoveWall, OperationRejected
from app.modules.building.primitives import EPS, Vec2, Vec3

#: Furniture closer than this to a face of the moved wall moves with it (m).
FURNITURE_CONTACT_M = 0.10
#: Semantic-key marker of the short walls created when a wall steps out of a straight line.
JOG_MARKER = ":jog:"


def _near(p: Point, q: Point) -> bool:
    return math.dist(p, q) < EPS


def _add(p: Point, m: Point) -> Point:
    return (p[0] + m[0], p[1] + m[1])


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _round_pt(p: Point) -> Point:
    return (round(p[0], 3) + 0.0, round(p[1], 3) + 0.0)


def _unit(wall: Wall) -> Point:
    return (math.cos(wall.rotation.z), math.sin(wall.rotation.z))


def _param(p: Point, a: Point, u: Point) -> float:
    """Position of p along the line through a with direction u."""
    return _dot((p[0] - a[0], p[1] - a[1]), u)


def _off_line(p: Point, a: Point, u: Point) -> float:
    """Signed distance of p from the line through a with direction u (+ = left)."""
    return -(p[0] - a[0]) * u[1] + (p[1] - a[1]) * u[0]


def _on_segment(p: Point, a: Point, b: Point, *, interior: bool) -> bool:
    length = math.dist(a, b)
    if length < EPS:
        return False
    u = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
    if abs(_off_line(p, a, u)) > EPS:
        return False
    t = _param(p, a, u)
    if interior:
        return EPS < t < length - EPS
    return -EPS <= t <= length + EPS


def _parallel(a: Wall, b: Wall) -> bool:
    ua, ub = _unit(a), _unit(b)
    return abs(ua[0] * ub[1] - ua[1] * ub[0]) < 1e-6


class _Edit:
    """Mutable working set for one operation: elements by id, in model order."""

    def __init__(self, model: BuildingModel) -> None:
        self.model = model
        self.order: list[uuid.UUID] = [e.id for e in model.elements]
        self.by_id: dict[uuid.UUID, Element] = {e.id: e for e in model.elements}
        self.removed: set[uuid.UUID] = set()

    def set(self, el: Element) -> None:
        self.by_id[el.id] = el

    def insert_after(self, anchor: uuid.UUID, el: Element) -> None:
        self.order.insert(self.order.index(anchor) + 1, el.id)
        self.by_id[el.id] = el

    def remove(self, el_id: uuid.UUID) -> None:
        self.removed.add(el_id)

    def elements(self) -> list[Element]:
        return [self.by_id[i] for i in self.order if i not in self.removed]


def _stretch(edit: _Edit, wall: Wall, which: str, m: Point, mover: Wall) -> None:
    """Move one end of `wall` (perpendicular to the moved wall, so along its own axis) by m."""
    current = edit.by_id[wall.id]
    if not isinstance(current, Wall):  # removed or replaced by an earlier step: nothing to do
        return
    u = _unit(current)
    along = _dot(m, u)
    length = current.dimensions.length + (along if which == "end" else -along)
    if length < 0.001:
        if JOG_MARKER in current.semantic_key:
            edit.remove(current.id)  # a step created by an earlier move, now flat again
            return
        raise OperationRejected(
            "WALL_WOULD_VANISH",
            f"Moving {mover.name} this far would shrink {current.name} to nothing. "
            "Move it less, or remove the wall first.",
            element_id=mover.id,
            related_ids=[current.id],
        )
    update: dict[str, object] = {
        "dimensions": current.dimensions.model_copy(update={"length": round(length, 3)})
    }
    if which == "start":
        x, y = _round_pt(_add((current.position.x, current.position.y), m))
        update["position"] = current.position.model_copy(update={"x": x, "y": y})
    edit.set(current.model_copy(update=update))
    if which == "start":
        # Openings are placed from the wall's start: keep them where they are in the plan.
        for el in list(edit.by_id.values()):
            hosts = [r.target_id for r in el.relationships if r.kind == "hosted_by"]
            if el.type in ("door", "window") and hosts == [current.id]:
                x = round(el.position.x - along, 3) + 0.0
                edit.set(
                    el.model_copy(update={"position": el.position.model_copy(update={"x": x})})
                )


def _jog(edit: _Edit, mover: Wall, end: str, start: Point, m: Point) -> None:
    """A short wall from `start` along m, closing the step between the moved wall and the line
    it left. Deterministic id and key, so replaying the same operations gives the same model."""
    base_key = f"{mover.semantic_key}{JOG_MARKER}{end}"
    taken = {e.semantic_key for e in edit.by_id.values()}
    key, n = base_key, 2
    while key in taken:
        key, n = f"{base_key}:{n}", n + 1
    jog = mover.model_copy(
        update={
            "id": uuid.uuid5(edit.model.id, f"edit:{key}"),
            "name": f"{mover.name}-J{'1' if end == 'start' else '2'}",
            "position": Vec3(x=start[0], y=start[1], z=mover.position.z),
            "rotation": mover.rotation.model_copy(update={"z": round(math.atan2(m[1], m[0]), 6)}),
            "dimensions": mover.dimensions.model_copy(update={"length": round(math.hypot(*m), 3)}),
            "relationships": [],
            "origin": Origin.USER,
            "locked": False,
            "semantic_key": key,
        }
    )
    edit.insert_after(mover.id, jog)


def _move_room_edges(room: Room, a: Point, u: Point, length: float, m: Point) -> Room:
    """Move the parts of the room's boundary that run along the wall axis a + t·u, t∈[0, L]."""
    ring = room_ring(room)
    out: list[Point] = []
    for i, p in enumerate(ring):
        q = ring[(i + 1) % len(ring)]
        out.append(p)
        if abs(_off_line(p, a, u)) > EPS or abs(_off_line(q, a, u)) > EPS:
            continue
        tp, tq = _param(p, a, u), _param(q, a, u)
        lo, hi = max(min(tp, tq), 0.0), min(max(tp, tq), length)
        if hi - lo <= EPS:
            continue
        first, second = (lo, hi) if tp < tq else (hi, lo)
        x0 = (a[0] + first * u[0], a[1] + first * u[1])
        x1 = (a[0] + second * u[0], a[1] + second * u[1])
        out += [x0, _add(x0, m), _add(x1, m), x1]
    cleaned = _simplify([_round_pt(p) for p in out], room)
    area = signed_area(cleaned)
    if abs(area) < 0.01 or (area > 0) != (signed_area(ring) > 0):
        raise OperationRejected(
            "ROOM_WOULD_COLLAPSE",
            f"{room.name} would close up or turn inside out.",
            element_id=room.id,
        )
    c, s = math.cos(room.rotation.z), math.sin(room.rotation.z)
    px, py = room.position.x, room.position.y
    local = [
        Vec2(x=(x - px) * c + (y - py) * s, y=-(x - px) * s + (y - py) * c) for x, y in cleaned
    ]
    return room.model_copy(
        update={
            "properties": room.properties.model_copy(update={"boundary": local}),
            "dimensions": room.dimensions.model_copy(
                update={
                    "area": round(abs(area), 2) + 0.0,
                    "perimeter": round(perimeter(cleaned), 3),
                }
            ),
        }
    )


def _simplify(pts: list[Point], room: Room) -> list[Point]:
    """Drop repeated vertices and vertices where the boundary runs straight on or doubles back
    along itself (the corner a shrinking room leaves behind), then require a simple polygon."""
    changed = True
    while changed and len(pts) >= 3:
        changed = False
        n = len(pts)
        for i in range(n):
            prev, cur, nxt = pts[i - 1], pts[i], pts[(i + 1) % n]
            d1 = (cur[0] - prev[0], cur[1] - prev[1])
            d2 = (nxt[0] - cur[0], nxt[1] - cur[1])
            if _near(prev, cur) or abs(d1[0] * d2[1] - d1[1] * d2[0]) < EPS:
                pts = pts[:i] + pts[i + 1 :]
                changed = True
                break
    if len(pts) < 4 or not ShapelyPolygon(pts).is_valid:
        raise OperationRejected(
            "ROOM_WOULD_COLLAPSE",
            f"{room.name} would close up or fold over itself: the wall would reach or pass "
            "another wall of the room.",
            element_id=room.id,
        )
    return pts


def _line_continues(rooms: list[Room], a: Point, u: Point, length: float, end: str) -> bool:
    """Whether a room boundary runs on along the wall's line past its start or end."""
    for room in rooms:
        ring = room_ring(room)
        for i, p in enumerate(ring):
            q = ring[(i + 1) % len(ring)]
            if abs(_off_line(p, a, u)) > EPS or abs(_off_line(q, a, u)) > EPS:
                continue
            lo, hi = sorted((_param(p, a, u), _param(q, a, u)))
            if end == "start" and lo < -EPS and hi > -EPS:
                return True
            if end == "end" and hi > length + EPS and lo < length + EPS:
                return True
    return False


def _furniture_against(item: Furniture, wall: Wall, a: Point, u: Point) -> bool:
    w, d = item.dimensions.width, item.dimensions.depth
    c, s = math.cos(item.rotation.z), math.sin(item.rotation.z)
    corners = [
        (item.position.x + x * c - y * s, item.position.y + x * s + y * c)
        for x, y in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))
    ]
    off = [_off_line(p, a, u) for p in corners]
    along = [_param(p, a, u) for p in corners]
    half = wall.dimensions.thickness / 2 + FURNITURE_CONTACT_M
    touches = min(abs(v) for v in off) <= half or min(off) * max(off) < 0
    return touches and max(along) > EPS and min(along) < wall.dimensions.length - EPS


def move_wall(model: BuildingModel, op: MoveWall) -> BuildingModel:
    wall = next((e for e in model.elements if e.id == op.wall_id), None)
    if not isinstance(wall, Wall):
        raise OperationRejected("WALL_NOT_FOUND", "The wall to move is not in this design.")
    if not is_axis_aligned(wall.rotation.z):
        raise OperationRejected(
            "WALL_NOT_AXIS_ALIGNED", f"{wall.name} is not axis-aligned.", element_id=wall.id
        )
    delta = round(op.offset_m, 3)
    if abs(delta) < 0.001:
        raise OperationRejected(
            "NO_CHANGE", f"{wall.name} would move by less than 1 mm.", element_id=wall.id
        )
    if wall.properties.wall_kind == WallKind.EXTERIOR:
        # The whole facade moves, with the envelope it carries (D2.5).
        from app.modules.building.operations.envelope import move_facade

        return move_facade(model, wall, delta)
    return shift_wall(model, wall, delta)


def shift_wall(
    model: BuildingModel,
    wall: Wall,
    delta: float,
    *,
    skip_rooms: frozenset[uuid.UUID] = frozenset(),
) -> BuildingModel:
    """Move one wall sideways on its level with everything that joins it (see module doc).
    Rooms in `skip_rooms` keep their boundaries (a facade move translates the outdoor rooms
    that hang on it instead)."""
    edit = _Edit(model)
    a, b = wall_axis(wall)
    u = _unit(wall)
    n = (-u[1], u[0])
    m = (delta * n[0], delta * n[1])
    length = wall.dimensions.length
    others = sorted(
        (
            e
            for e in model.elements
            if isinstance(e, Wall) and e.level_id == wall.level_id and e.id != wall.id
        ),
        key=lambda w: str(w.id),
    )

    # Walls crossing the moved wall's middle cannot follow it.
    for o in others:
        oa, ob = wall_axis(o)
        if _parallel(o, wall):
            continue
        cross = _param(oa, a, u)
        if EPS < cross < length - EPS and _on_segment(
            (a[0] + cross * u[0], a[1] + cross * u[1]), oa, ob, interior=True
        ):
            raise OperationRejected(
                "WALL_CROSSED",
                f"{o.name} crosses {wall.name}; walls that cross cannot be moved.",
                element_id=wall.id,
                related_ids=[o.id],
            )

    rooms = [
        e
        for e in model.elements
        if isinstance(e, Room) and e.level_id == wall.level_id and e.id not in skip_rooms
    ]
    for end, e in (("start", a), ("end", b)):
        moved_e = _add(e, m)
        at_e = [
            (o, "start" if _near(wall_axis(o)[0], e) else "end")
            for o in others
            if _near(wall_axis(o)[0], e) or _near(wall_axis(o)[1], e)
        ]
        through = [o for o in others if _on_segment(e, *wall_axis(o), interior=True)]
        if through:
            # The end stands against the side of another wall and slides along it.
            host = through[0]
            if not _on_segment(moved_e, *wall_axis(host), interior=False):
                raise OperationRejected(
                    "WALL_END_UNSUPPORTED",
                    f"The {end} of {wall.name} would slide past the end of {host.name}.",
                    element_id=wall.id,
                    related_ids=[host.id],
                )
            continue
        in_line = [o for o, _ in at_e if _parallel(o, wall)]
        # Does the wall's line go on past this end — another wall, or a room / void boundary?
        line_goes_on = bool(in_line) or _line_continues(rooms, a, u, length, end)
        covered = False
        for o, which in at_e:
            if _parallel(o, wall):
                continue
            oa, ob = wall_axis(o)
            far = ob if which == "start" else oa
            if _dot((far[0] - e[0], far[1] - e[1]), m) > 0:
                # o runs from e the way the wall moves.
                if not line_goes_on:
                    _stretch(edit, o, which, m, wall)  # an L-corner: o shortens with it
                    continue
                if math.dist(oa, ob) < abs(delta) - EPS:
                    raise OperationRejected(
                        "WALL_END_UNSUPPORTED",
                        f"The {end} of {wall.name} would leave {o.name}; move it less than "
                        f"{math.dist(oa, ob):.2f} m.",
                        element_id=wall.id,
                        related_ids=[o.id],
                    )
                covered = True  # o keeps its length; the moved wall now meets its side
            elif not in_line:
                _stretch(edit, o, which, m, wall)  # o lengthens to meet the moved wall
                covered = True
        if line_goes_on and not covered:
            _jog(edit, wall, end, e, m)

    # Walls that end on the moved wall's side follow it.
    for o in others:
        oa, ob = wall_axis(o)
        for which, p in (("start", oa), ("end", ob)):
            if _on_segment(p, a, b, interior=True) and not _parallel(o, wall):
                _stretch(edit, o, which, m, wall)

    x, y = _round_pt(_add(a, m))
    edit.set(
        wall.model_copy(
            update={
                "position": wall.position.model_copy(update={"x": x, "y": y}),
                "origin": Origin.USER,
            }
        )
    )

    for el in model.elements:
        if isinstance(el, Room) and el.level_id == wall.level_id:
            if el.id not in skip_rooms:
                edit.set(_move_room_edges(el, a, u, length, m))
        elif (
            isinstance(el, Furniture)
            and el.level_id == wall.level_id
            and not any(r.target_id in skip_rooms for r in el.relationships)
            and _furniture_against(el, wall, a, u)
        ):
            fx, fy = _round_pt(_add((el.position.x, el.position.y), m))
            edit.set(
                el.model_copy(
                    update={"position": el.position.model_copy(update={"x": fx, "y": fy})}
                )
            )

    elements = refresh_level_relationships(edit.elements(), wall.level_id)
    return model.model_copy(update={"elements": elements})
