"""`add_wall`: split a room with a new interior wall (Phase 3.6 D2.4, docs/building-model.md §5.5).

The new wall runs east-west or north-south through a point inside the room, across the room from
boundary to boundary (in an L-shaped room: across the arm that holds the point). Room boundaries
run on wall axes, so both ends must meet an existing wall (a T-junction into its side, or a
corner); an end on an open, wall-less boundary is refused.

- The room is split along the wall's axis. The larger part keeps the room (id, name, type, key);
  the smaller part becomes a new room (`room:edit:<n>`, uuid5 of the model id) of
  `new_room_type` (default: the room's type), with the room's height and finishes.
- The wall copies the build-up of an interior wall of the room (else of the level, else of the
  model): thickness, height, finishes, type. Key `wall:edit:<n>`, name `New wall <n>`.
- Furniture and stairs `located_in` the room move to the part that holds their centre; doors that
  open into the room are reconnected to the part they open into. Furniture the wall would cut
  through is refused (move it first).
- With a door size, an interior door is placed in the middle of the new wall (`add_opening`), so
  the new room can be reached; without one, the reachability check of the editing service
  refuses a room cut off.

Everything else — minimum sizes of both parts, windows of habitable rooms, MUST requirements — is
judged on the result by the editing service.
"""

import math
import uuid

from shapely.geometry import LineString
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry.polygon import orient
from shapely.ops import split

from app.modules.building.elements import Door, Element, Furniture, Room, Stair, Wall
from app.modules.building.enums import Origin, RelationshipKind, WallKind
from app.modules.building.geometry import Point, perimeter, signed_area, wall_axis
from app.modules.building.model import BuildingModel
from app.modules.building.operations.openings import _relationships, add_opening, host_of, hosted
from app.modules.building.operations.relationships import refresh_level_relationships, room_ring
from app.modules.building.operations.rooms import FIXED_ROOM_TYPES, room_zone
from app.modules.building.operations.schemas import AddOpening, AddWall, OperationRejected
from app.modules.building.operations.wall_removal import _local, _round_pt, _simplified
from app.modules.building.primitives import EPS, Rotation, Vec3


def _on_axis(p: Point, wall: Wall) -> bool:
    a, b = wall_axis(wall)
    return LineString([a, b]).distance(ShapelyPoint(p)) < EPS


def _new_key(model: BuildingModel, kind: str) -> tuple[str, int]:
    taken = {e.semantic_key for e in model.elements}
    n = 1
    while f"{kind}:edit:{n}" in taken:
        n += 1
    return f"{kind}:edit:{n}", n


def _template(model: BuildingModel, room: Room) -> Wall | None:
    """An interior wall to copy the build-up from: one bounding the room, else one of its level,
    else any; first by semantic key."""
    interior = sorted(
        (
            e
            for e in model.elements
            if isinstance(e, Wall) and e.properties.wall_kind != WallKind.EXTERIOR
        ),
        key=lambda w: w.semantic_key,
    )
    bounding = [
        w
        for w in interior
        if any(
            r.kind == RelationshipKind.BOUNDS and r.target_id == room.id for r in w.relationships
        )
    ]
    level = [w for w in interior if w.level_id == room.level_id]
    found = bounding or level or interior
    return found[0] if found else None


def _footprint(item: Furniture) -> ShapelyPolygon:
    w, d = item.dimensions.width, item.dimensions.depth
    c, s = math.cos(item.rotation.z), math.sin(item.rotation.z)
    return ShapelyPolygon(
        [
            (item.position.x + x * c - y * s, item.position.y + x * s + y * c)
            for x, y in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))
        ]
    )


def _ring(poly: ShapelyPolygon) -> list[Point]:
    poly = orient(poly, sign=1.0)  # counter-clockwise
    return _simplified([_round_pt((x, y)) for x, y in list(poly.exterior.coords)[:-1]])


def add_wall(model: BuildingModel, op: AddWall) -> BuildingModel:
    room = next((e for e in model.elements if e.id == op.room_id), None)
    if not isinstance(room, Room):
        raise OperationRejected("ROOM_NOT_FOUND", "The room to divide is not in this design.")
    if room.locked:
        raise OperationRejected(
            "ELEMENT_LOCKED", f"{room.name} is locked and cannot be divided.", element_id=room.id
        )
    new_type = op.new_room_type or room.properties.room_type
    if room.properties.room_type in FIXED_ROOM_TYPES or new_type in FIXED_ROOM_TYPES:
        fixed = (
            room.properties.room_type if room.properties.room_type in FIXED_ROOM_TYPES else new_type
        )
        raise OperationRejected(
            "ROOM_TYPE_UNSUPPORTED",
            f"A {fixed.value.replace('_', ' ')} is tied to the building (stair, garage door or "
            "outdoors); it cannot be divided or created by a new wall.",
            element_id=room.id,
        )
    poly = ShapelyPolygon(room_ring(room))
    p = (round(op.x_m, 3) + 0.0, round(op.y_m, 3) + 0.0)
    if not poly.buffer(-EPS).contains(ShapelyPoint(p)):
        raise OperationRejected(
            "POINT_OUTSIDE_ROOM",
            f"The point ({p[0]:.2f}, {p[1]:.2f}) is not inside {room.name}.",
            element_id=room.id,
        )

    # The line through the point, across the room; the piece that holds the point.
    minx, miny, maxx, maxy = poly.bounds
    east = op.direction == "east_west"
    line = (
        LineString([(minx - 1, p[1]), (maxx + 1, p[1])])
        if east
        else LineString([(p[0], miny - 1), (p[0], maxy + 1)])
    )
    cut = line.intersection(poly)
    pieces = [g for g in getattr(cut, "geoms", [cut]) if isinstance(g, LineString)]
    piece = next((g for g in pieces if g.distance(ShapelyPoint(p)) < EPS), None)
    if piece is None or piece.length < EPS:
        raise OperationRejected(
            "ADD_WALL_INVALID",
            f"No wall can be drawn across {room.name} there.",
            element_id=room.id,
        )
    (x0, y0), (x1, y1) = piece.coords[0], piece.coords[-1]
    a, b = sorted((_round_pt((x0, y0)), _round_pt((x1, y1))))
    level_walls = sorted(
        (e for e in model.elements if isinstance(e, Wall) and e.level_id == room.level_id),
        key=lambda w: w.semantic_key,
    )
    for end in (a, b):
        if not any(_on_axis(end, w) for w in level_walls):
            raise OperationRejected(
                "WALL_END_OPEN",
                f"The new wall would end at ({end[0]:.2f}, {end[1]:.2f}) on an open boundary of "
                f"{room.name} (no wall there to meet).",
                element_id=room.id,
            )
    template = _template(model, room)
    half_t = (template.dimensions.thickness if template else 0.0) / 2
    for end in (a, b):
        for w in level_walls:
            if not _on_axis(end, w):
                continue
            wa, _ = wall_axis(w)
            along = math.dist(wa, end)
            for o in hosted(model, w):
                if (
                    o.position.x - half_t - EPS
                    < along
                    < o.position.x + o.dimensions.width + half_t + EPS
                ):
                    raise OperationRejected(
                        "WALL_END_ON_OPENING",
                        f"The new wall would meet {w.name} at {o.name}; place it beside the "
                        "opening (or move the opening first).",
                        element_id=room.id,
                        related_ids=[o.id, w.id],
                    )
    if template is None:
        raise OperationRejected(
            "WALL_TEMPLATE_MISSING",
            "The design has no interior wall to take the build-up of a new wall from.",
            element_id=room.id,
        )

    # Split the room along the axis (the cut runs 1 mm past the boundary so it always splits).
    u = (1.0, 0.0) if east else (0.0, 1.0)
    blade = LineString(
        [(a[0] - 0.001 * u[0], a[1] - 0.001 * u[1]), (b[0] + 0.001 * u[0], b[1] + 0.001 * u[1])]
    )
    parts = [g for g in split(poly, blade).geoms if isinstance(g, ShapelyPolygon)]
    if len(parts) != 2:
        raise OperationRejected(
            "ADD_WALL_INVALID", f"The wall would not divide {room.name} in two.", element_id=room.id
        )
    keep_poly, new_poly = sorted(parts, key=lambda g: (-round(g.area, 6), g.bounds))
    keep_ring, new_ring = _ring(keep_poly), _ring(new_poly)

    half = template.dimensions.thickness / 2
    body = LineString([a, b]).buffer(half, cap_style="flat")
    for item in model.elements:
        if (
            isinstance(item, Furniture)
            and item.level_id == room.level_id
            and _footprint(item).intersection(body).area > 1e-4
        ):
            raise OperationRejected(
                "FURNITURE_IN_THE_WAY",
                f"The new wall would cut through {item.name}; move the wall or the furniture.",
                element_id=room.id,
                related_ids=[item.id],
            )

    wall_key, n = _new_key(model, "wall")
    room_key, m = _new_key(model, "room")
    taken = {e.name.casefold() for e in model.elements if isinstance(e, Room)}
    room_name = f"New room {m}"
    while room_name.casefold() in taken:
        m += 1
        room_name = f"New room {m}"
    wall = template.model_copy(
        update={
            "id": uuid.uuid5(model.id, f"edit:{wall_key}"),
            "name": f"New wall {n}",
            "level_id": room.level_id,
            "position": Vec3(x=a[0], y=a[1], z=template.position.z),
            "rotation": Rotation(z=0.0 if east else round(math.pi / 2, 6)),
            "dimensions": template.dimensions.model_copy(
                update={"length": round(math.dist(a, b), 3)}
            ),
            "relationships": [],
            "origin": Origin.USER,
            "locked": False,
            "semantic_key": wall_key,
        }
    )
    kept = room.model_copy(
        update={
            "properties": room.properties.model_copy(update={"boundary": _local(room, keep_ring)}),
            "dimensions": room.dimensions.model_copy(
                update={
                    "area": round(abs(signed_area(keep_ring)), 2) + 0.0,
                    "perimeter": round(perimeter(keep_ring), 3),
                }
            ),
            "origin": Origin.USER,
        }
    )
    new_room = room.model_copy(
        update={
            "id": uuid.uuid5(model.id, f"edit:{room_key}"),
            "name": room_name,
            "semantic_key": room_key,
            "properties": room.properties.model_copy(
                update={
                    "boundary": _local(room, new_ring),
                    "room_type": new_type,
                    "zone": room_zone(new_type),
                }
            ),
            "dimensions": room.dimensions.model_copy(
                update={
                    "area": round(abs(signed_area(new_ring)), 2) + 0.0,
                    "perimeter": round(perimeter(new_ring), 3),
                }
            ),
            "relationships": [],
            "origin": Origin.USER,
            "locked": False,
            "type_ref": None,
        }
    )

    # Furniture and stairs located in the room go to the part that holds their centre.
    new_inside = ShapelyPolygon(new_ring)
    elements: list[Element] = []
    for e in model.elements:
        el: Element = kept if e.id == room.id else e
        if (
            isinstance(el, Furniture | Stair)
            and any(
                r.kind == RelationshipKind.LOCATED_IN and r.target_id == room.id
                for r in el.relationships
            )
            and new_inside.contains(ShapelyPoint(el.position.x, el.position.y))
        ):
            el = el.model_copy(
                update={
                    "relationships": [
                        r.model_copy(update={"target_id": new_room.id})
                        if r.kind == RelationshipKind.LOCATED_IN and r.target_id == room.id
                        else r
                        for r in el.relationships
                    ]
                }
            )
        elements.append(el)
        if e.id == room.id:
            elements.append(new_room)
    last_wall = max(
        i for i, e in enumerate(elements) if isinstance(e, Wall) and e.level_id == room.level_id
    )
    elements.insert(last_wall + 1, wall)
    current = model.model_copy(update={"elements": elements})

    # Doors into the room open into one of the parts now.
    reconnected: list[Element] = []
    for e in current.elements:
        if isinstance(e, Door) and any(
            r.kind == RelationshipKind.CONNECTS and r.target_id == room.id for r in e.relationships
        ):
            host = host_of(current, e)
            if host is not None:
                span = (e.position.x, e.position.x + e.dimensions.width)
                e = e.model_copy(update={"relationships": _relationships(e, current, host, span)})
        reconnected.append(e)
    current = current.model_copy(
        update={"elements": refresh_level_relationships(reconnected, room.level_id)}
    )

    if op.door_width_m is not None and op.door_height_m is not None:
        width = round(op.door_width_m, 3)
        offset = round(max(wall.dimensions.length - width, 0.0) / 2, 3)
        try:
            current = add_opening(
                current,
                AddOpening(
                    kind="door",
                    host_wall_id=wall.id,
                    offset_m=offset,
                    width_m=width,
                    height_m=op.door_height_m,
                ),
            )
        except OperationRejected as err:
            raise OperationRejected(
                err.code,
                f"The door of the new wall: {err.message}",
                element_id=room.id,
                related_ids=err.related_ids,
            ) from err
    return current
