"""`remove_wall`: take an interior wall out of the plan (Phase 3.6 D2.4, docs/building-model.md
§5.4).

Room boundaries run on wall axes, and two rooms that share a boundary without a wall on it are an
open plan (validation links them for reachability). Removing a wall therefore has two consistent
results:

- `merge_rooms` false: the wall and its doors go; the rooms on both sides keep their outlines and
  now open into each other along the former wall.
- `merge_rooms` true: the wall must separate exactly two rooms; they become one room whose outline
  is the union of both. The larger room (ties: the smaller semantic key) keeps its id, name, type,
  height and finishes; the other room is removed and everything that pointed at it (doors'
  `connects`, furniture's `located_in`, ...) points at the merged room.

Refused, with the reason: exterior walls (the footprint, floor slabs and roof depend on them),
locked elements, walls that other walls join or cross in their middle (they would be left
standing free), walls of rooms that keep their walls (bathrooms, WCs, en-suites, garages, plant
rooms; two rooms of the same such type may be merged), walls with a room on one side only (the
edge of a stair opening), a merge across anything but two rooms, and a merge that would leave
another wall inside the merged room. Everything else — reachability, minimum sizes, MUST
requirements of the spec — is judged on the result by the editing service.
"""

import math
import uuid
from collections.abc import Iterable

from shapely.geometry import LineString
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from app.modules.building.elements import Door, Element, Relationship, Room, Wall, Window
from app.modules.building.enums import Origin, RoomType, WallKind
from app.modules.building.geometry import (
    Point,
    is_axis_aligned,
    perimeter,
    polygon_edges,
    segment_overlap_length,
    signed_area,
    wall_axis,
)
from app.modules.building.model import BuildingModel
from app.modules.building.operations.openings import hosted
from app.modules.building.operations.relationships import refresh_level_relationships, room_ring
from app.modules.building.operations.schemas import OperationRejected, RemoveWall
from app.modules.building.primitives import EPS, Vec2

#: Rooms that keep their walls: opening them into another room is refused. Two rooms of the same
#: such type (two WCs, say) may still be merged into one.
ENCLOSED_ROOMS = frozenset(
    {RoomType.BATHROOM, RoomType.WC, RoomType.EN_SUITE, RoomType.GARAGE, RoomType.PLANT_ROOM}
)


def _round_pt(p: Point) -> Point:
    return (round(p[0], 3) + 0.0, round(p[1], 3) + 0.0)


def _on_segment_interior(p: Point, a: Point, b: Point) -> bool:
    length = math.dist(a, b)
    if length < EPS:
        return False
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    dx, dy = p[0] - a[0], p[1] - a[1]
    if abs(-dx * uy + dy * ux) > EPS:
        return False
    t = dx * ux + dy * uy
    return EPS < t < length - EPS


def rooms_along(model: BuildingModel, wall: Wall) -> list[Room]:
    """Rooms of the wall's level whose boundary runs along its axis, in semantic-key order."""
    axis = wall_axis(wall)
    return sorted(
        (
            e
            for e in model.elements
            if isinstance(e, Room)
            and e.level_id == wall.level_id
            and max(
                (segment_overlap_length(axis, ed) for ed in polygon_edges(room_ring(e))), default=0
            )
            > EPS
        ),
        key=lambda r: r.semantic_key,
    )


def _joining(model: BuildingModel, wall: Wall) -> list[Wall]:
    """Walls that end on, or cross, the wall between its ends."""
    a, b = wall_axis(wall)
    out = []
    for o in model.elements:
        if not isinstance(o, Wall) or o.level_id != wall.level_id or o.id == wall.id:
            continue
        oa, ob = wall_axis(o)
        line = LineString([oa, ob])
        crossing = line.intersection(LineString([a, b]))
        touches_middle = any(_on_segment_interior(p, a, b) for p in (oa, ob))
        crosses = (
            isinstance(crossing, ShapelyPoint)
            and _on_segment_interior((crossing.x, crossing.y), a, b)
            and _on_segment_interior((crossing.x, crossing.y), oa, ob)
        )
        if touches_middle or crosses:
            out.append(o)
    return sorted(out, key=lambda w: w.semantic_key)


def _local(room: Room, pts: list[Point]) -> list[Vec2]:
    c, s = math.cos(room.rotation.z), math.sin(room.rotation.z)
    px, py = room.position.x, room.position.y
    return [
        Vec2(
            x=round((x - px) * c + (y - py) * s, 3) + 0.0,
            y=round(-(x - px) * s + (y - py) * c, 3) + 0.0,
        )
        for x, y in pts
    ]


def _simplified(pts: list[Point]) -> list[Point]:
    """Drop repeated vertices and vertices where the boundary runs straight on."""
    changed = True
    while changed and len(pts) > 3:
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
    return pts


def _retarget(
    rels: Iterable[Relationship], old: uuid.UUID, new: uuid.UUID, own: uuid.UUID
) -> list[Relationship]:
    out: list[Relationship] = []
    for r in rels:
        target = new if r.target_id == old else r.target_id
        if target == own:
            continue  # a room adjacent to itself, say
        moved = r if target == r.target_id else r.model_copy(update={"target_id": target})
        if moved not in out:
            out.append(moved)
    return out


def _merge(wall: Wall, rooms: list[Room], elements: list[Element]) -> list[Element]:
    keep, gone = sorted(rooms, key=lambda r: (-r.dimensions.area, r.semantic_key))
    for r in (keep, gone):
        if r.locked:
            raise OperationRejected(
                "ELEMENT_LOCKED",
                f"{r.name} is locked; it cannot be merged with another room.",
                element_id=wall.id,
                related_ids=[r.id],
            )
    union = unary_union([ShapelyPolygon(room_ring(keep)), ShapelyPolygon(room_ring(gone))])
    if not isinstance(union, ShapelyPolygon) or len(union.interiors) > 0:
        raise OperationRejected(
            "ROOM_MERGE_INVALID",
            f"{keep.name} and {gone.name} do not form one simple room.",
            element_id=wall.id,
            related_ids=[keep.id, gone.id],
        )
    union = orient(union, sign=1.0)  # counter-clockwise
    pts = _simplified([_round_pt((x, y)) for x, y in list(union.exterior.coords)[:-1]])
    inner = ShapelyPolygon(pts).buffer(-EPS)
    for o in elements:
        if (
            isinstance(o, Wall)
            and o.level_id == wall.level_id
            and LineString(wall_axis(o)).intersection(inner).length > EPS
        ):
            raise OperationRejected(
                "ROOM_MERGE_WALL_INSIDE",
                f"{o.name} also stands between {keep.name} and {gone.name}; it would end up "
                "inside the merged room. Remove it first.",
                element_id=wall.id,
                related_ids=[o.id],
            )
    area = abs(signed_area(pts))
    merged = keep.model_copy(
        update={
            "properties": keep.properties.model_copy(update={"boundary": _local(keep, pts)}),
            "dimensions": keep.dimensions.model_copy(
                update={"area": round(area, 2) + 0.0, "perimeter": round(perimeter(pts), 3)}
            ),
            "origin": Origin.USER,
        }
    )
    out: list[Element] = []
    for e in elements:
        if e.id == gone.id:
            continue
        el = merged if e.id == keep.id else e
        if any(r.target_id == gone.id for r in el.relationships):
            el = el.model_copy(
                update={"relationships": _retarget(el.relationships, gone.id, keep.id, el.id)}
            )
        out.append(el)
    return out


def remove_wall(model: BuildingModel, op: RemoveWall) -> BuildingModel:
    wall = next((e for e in model.elements if e.id == op.wall_id), None)
    if wall is None:
        raise OperationRejected("WALL_NOT_FOUND", "The wall to remove is not in this design.")
    if not isinstance(wall, Wall):
        raise OperationRejected(
            "ELEMENT_NOT_REMOVABLE",
            f"{wall.name} is a {wall.type}, not a wall.",
            element_id=wall.id,
        )
    if wall.locked:
        raise OperationRejected(
            "ELEMENT_LOCKED", f"{wall.name} is locked and cannot be removed.", element_id=wall.id
        )
    if wall.properties.wall_kind == WallKind.EXTERIOR:
        raise OperationRejected(
            "EXTERIOR_WALL_FIXED",
            f"{wall.name} is an exterior wall. The footprint, the floor slabs and the roof rest on "
            "the exterior walls; only interior walls can be removed.",
            element_id=wall.id,
        )
    if not is_axis_aligned(wall.rotation.z):
        raise OperationRejected(
            "WALL_NOT_AXIS_ALIGNED", f"{wall.name} is not axis-aligned.", element_id=wall.id
        )
    joining = _joining(model, wall)
    if joining:
        names = ", ".join(w.name for w in joining)
        raise OperationRejected(
            "WALL_HAS_JUNCTIONS",
            f"{names} {'joins' if len(joining) == 1 else 'join'} {wall.name} between its ends and "
            "would be left standing free. Only walls without walls joining their middle can be "
            "removed.",
            element_id=wall.id,
            related_ids=[w.id for w in joining],
        )
    rooms = rooms_along(model, wall)
    if len(rooms) < 2:
        raise OperationRejected(
            "WALL_EDGES_OPEN_SPACE",
            f"{wall.name} has a room on one side only; the other side is a stair opening or open "
            "space that the wall closes off.",
            element_id=wall.id,
            related_ids=[r.id for r in rooms],
        )
    enclosed = [r for r in rooms if r.properties.room_type in ENCLOSED_ROOMS]
    same_type_merge = (
        op.merge_rooms
        and len(rooms) == 2
        and rooms[0].properties.room_type == rooms[1].properties.room_type
    )
    if enclosed and not same_type_merge:
        room = enclosed[0]
        raise OperationRejected(
            "WALL_ENCLOSES_ROOM",
            f"{wall.name} encloses {room.name}. Bathrooms, WCs, en-suites, garages and plant rooms "
            "keep their walls; it cannot be opened into another room.",
            element_id=wall.id,
            related_ids=[room.id],
        )
    if op.merge_rooms and len(rooms) != 2:
        raise OperationRejected(
            "ROOM_MERGE_UNSUPPORTED",
            f"{wall.name} borders {len(rooms)} room{'s' if len(rooms) != 1 else ''}; rooms can be "
            "merged only across a wall between exactly two rooms.",
            element_id=wall.id,
            related_ids=[r.id for r in rooms],
        )
    gone = {wall.id} | {o.id for o in hosted(model, wall) if isinstance(o, Door | Window)}
    locked = [o for o in hosted(model, wall) if o.locked]
    if locked:
        raise OperationRejected(
            "ELEMENT_LOCKED",
            f"{locked[0].name} in {wall.name} is locked; the wall cannot be removed.",
            element_id=wall.id,
            related_ids=[locked[0].id],
        )
    elements: list[Element] = []
    for e in model.elements:
        if e.id in gone:
            continue
        if any(r.target_id in gone for r in e.relationships):
            e = e.model_copy(
                update={"relationships": [r for r in e.relationships if r.target_id not in gone]}
            )
        elements.append(e)
    if op.merge_rooms:
        elements = _merge(wall, rooms, elements)
    elements = refresh_level_relationships(elements, wall.level_id)
    return model.model_copy(update={"elements": elements})
