"""Room operations: `resize_room` moves one side of a room by moving the walls it runs along
(docs/building-model.md §5.2); `rename_room` and `set_room_type` change what a room is called and
what it is (§5.4).

A room side is not geometry of its own: room boundaries run on wall axes. Resizing a room is
therefore expressed as `move_wall` on every interior wall along that side, by the same distance in
the direction that moves the side outwards (+) or inwards (-). Everything a wall move keeps
consistent — the neighbouring room on the other side of a shared wall, joined walls, step walls,
openings, furniture, relationships — follows for free, and the result is judged by the same
validation. Sides the operation cannot move are refused with the reason, naming the room.
"""

import math
import unicodedata
import uuid
from dataclasses import dataclass

from app.modules.building.elements import Room, Wall
from app.modules.building.enums import Origin, RoomType, WallKind, Zone
from app.modules.building.geometry import Point, segment_overlap_length, signed_area, wall_axis
from app.modules.building.model import BuildingModel
from app.modules.building.operations.relationships import room_ring
from app.modules.building.operations.schemas import (
    MoveWall,
    OperationRejected,
    RenameRoom,
    ResizeRoom,
    SetRoomType,
)
from app.modules.building.operations.walls import move_wall
from app.modules.building.primitives import EPS

COMPASS = ((0.0, 1.0, "north"), (1.0, 0.0, "east"), (0.0, -1.0, "south"), (-1.0, 0.0, "west"))


@dataclass(frozen=True)
class RoomSide:
    """One side of a room boundary and the walls it runs along."""

    index: int
    start: Point
    end: Point
    outward: Point  # unit normal pointing out of the room
    walls: tuple[Wall, ...]  # walls whose axis overlaps the side, in id order
    covered: float  # length of the side that runs along those walls

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def compass(self) -> str:
        return max(COMPASS, key=lambda c: c[0] * self.outward[0] + c[1] * self.outward[1])[2]


def room_sides(model: BuildingModel, room: Room) -> list[RoomSide]:
    ring = room_ring(room)
    ccw = signed_area(ring) > 0
    walls = sorted(
        (e for e in model.elements if isinstance(e, Wall) and e.level_id == room.level_id),
        key=lambda w: str(w.id),
    )
    sides = []
    for i, p in enumerate(ring):
        q = ring[(i + 1) % len(ring)]
        length = math.dist(p, q)
        ux, uy = ((q[0] - p[0]) / length, (q[1] - p[1]) / length) if length > EPS else (0.0, 0.0)
        # Outward is to the right of the direction of travel on a counter-clockwise ring.
        outward = (uy, -ux) if ccw else (-uy, ux)
        along = [(w, segment_overlap_length(wall_axis(w), (p, q))) for w in walls]
        on_side = tuple(w for w, overlap in along if overlap > EPS)
        sides.append(RoomSide(i, p, q, outward, on_side, sum(o for _, o in along if o > EPS)))
    return sides


def resize_room(model: BuildingModel, op: ResizeRoom) -> BuildingModel:
    room = next((e for e in model.elements if e.id == op.room_id), None)
    if not isinstance(room, Room):
        raise OperationRejected("ROOM_NOT_FOUND", "The room to resize is not in this design.")
    sides = room_sides(model, room)
    if op.edge >= len(sides):
        raise OperationRejected(
            "ROOM_SIDE_NOT_FOUND",
            f"{room.name} has no side {op.edge}; the plan may have changed. Select the side again.",
            element_id=room.id,
        )
    side = sides[op.edge]
    delta = round(op.delta_m, 3)
    if abs(delta) < 0.001:
        raise OperationRejected(
            "NO_CHANGE",
            f"The {side.compass} side of {room.name} would move by less than 1 mm.",
            element_id=room.id,
        )
    where = f"The {side.compass} side of {room.name}"
    if not side.walls:
        raise OperationRejected(
            "ROOM_SIDE_OPEN",
            f"{where} is an open boundary without a wall (it opens into the next room); "
            "resizing across open boundaries is not supported yet.",
            element_id=room.id,
        )
    if side.covered < side.length - EPS:
        raise OperationRejected(
            "ROOM_SIDE_PARTLY_OPEN",
            f"{where} is only partly a wall ({side.covered:.2f} of {side.length:.2f} m); "
            "resizing it is not supported yet.",
            element_id=room.id,
            related_ids=[w.id for w in side.walls],
        )
    exterior = [w for w in side.walls if w.properties.wall_kind == WallKind.EXTERIOR]
    if exterior:
        raise OperationRejected(
            "EXTERIOR_WALL_FIXED",
            f"{where} is the exterior wall {exterior[0].name}. Moving exterior walls changes the "
            "footprint, the floor slabs and the roof; rooms can be resized at interior walls for "
            "now.",
            element_id=room.id,
            related_ids=[w.id for w in exterior],
        )
    current = model
    for wall in side.walls:
        nx, ny = -math.sin(wall.rotation.z), math.cos(wall.rotation.z)
        sign = 1.0 if nx * side.outward[0] + ny * side.outward[1] > 0 else -1.0
        try:
            current = move_wall(current, MoveWall(wall_id=wall.id, offset_m=sign * delta))
        except OperationRejected as err:
            raise OperationRejected(
                err.code,
                f"Resizing {room.name}: {err.message}",
                element_id=room.id,
                related_ids=[wall.id, *err.related_ids],
            ) from err
    return current


#: Zones of room types (the layout engine's program assigns the same to the types it plans).
PUBLIC_ROOMS = frozenset(
    {RoomType.LIVING, RoomType.DINING, RoomType.KITCHEN, RoomType.OPEN_KITCHEN_LIVING}
)
PRIVATE_ROOMS = frozenset({RoomType.BEDROOM, RoomType.STUDY})
CIRCULATION_ROOMS = frozenset(
    {RoomType.ENTRANCE, RoomType.HALL, RoomType.CORRIDOR, RoomType.STAIRCASE}
)
OUTDOOR_ROOMS = frozenset({RoomType.BALCONY, RoomType.TERRACE})
#: Types tied to other elements or to the envelope: a staircase room holds the stair, a garage
#: its vehicle door, balconies and terraces are outdoors. A room cannot be changed to or from
#: them by a type change.
FIXED_ROOM_TYPES = frozenset({RoomType.STAIRCASE, RoomType.GARAGE}) | OUTDOOR_ROOMS


def room_zone(room_type: RoomType) -> Zone:
    if room_type in PUBLIC_ROOMS:
        return Zone.PUBLIC
    if room_type in PRIVATE_ROOMS:
        return Zone.PRIVATE
    if room_type in CIRCULATION_ROOMS:
        return Zone.CIRCULATION
    if room_type in OUTDOOR_ROOMS:
        return Zone.EXTERIOR
    return Zone.SERVICE


def _room(model: BuildingModel, room_id: uuid.UUID, action: str) -> Room:
    room = next((e for e in model.elements if e.id == room_id), None)
    if not isinstance(room, Room):
        raise OperationRejected("ROOM_NOT_FOUND", f"The room to {action} is not in this design.")
    if room.locked:
        raise OperationRejected(
            "ELEMENT_LOCKED", f"{room.name} is locked and cannot be changed.", element_id=room.id
        )
    return room


def _replace_room(model: BuildingModel, room: Room) -> BuildingModel:
    return model.model_copy(
        update={"elements": [room if e.id == room.id else e for e in model.elements]}
    )


def clean_name(name: str) -> str:
    """Trimmed, inner whitespace runs collapsed to one space."""
    return " ".join(name.split())


def rename_room(model: BuildingModel, op: RenameRoom) -> BuildingModel:
    room = _room(model, op.room_id, "rename")
    name = clean_name(op.name)
    if not name or any(unicodedata.category(c).startswith("C") for c in name):
        raise OperationRejected(
            "ROOM_NAME_INVALID",
            "A room name needs at least one visible character and no control characters.",
            element_id=room.id,
        )
    if name == room.name:
        raise OperationRejected(
            "NO_CHANGE", f"{room.name} already has this name.", element_id=room.id
        )
    taken = next(
        (
            e
            for e in model.elements
            if isinstance(e, Room) and e.id != room.id and e.name.casefold() == name.casefold()
        ),
        None,
    )
    if taken is not None:
        raise OperationRejected(
            "ROOM_NAME_TAKEN",
            f"Another room is already called {taken.name}; room names must tell rooms apart in "
            "the plan and the reports.",
            element_id=room.id,
            related_ids=[taken.id],
        )
    return _replace_room(model, room.model_copy(update={"name": name, "origin": Origin.USER}))


def _type_label(room_type: RoomType) -> str:
    return room_type.value.replace("_", " ")


def set_room_type(model: BuildingModel, op: SetRoomType) -> BuildingModel:
    room = _room(model, op.room_id, "change")
    old = room.properties.room_type
    if op.room_type == old:
        raise OperationRejected(
            "NO_CHANGE", f"{room.name} is already a {_type_label(old)}.", element_id=room.id
        )
    fixed = old if old in FIXED_ROOM_TYPES else op.room_type
    if fixed in FIXED_ROOM_TYPES:
        reason = {
            RoomType.STAIRCASE: "a staircase room holds the stair between floors",
            RoomType.GARAGE: "a garage is defined by its vehicle door and access",
        }.get(fixed, "balconies and terraces are outdoor spaces outside the heated envelope")
        raise OperationRejected(
            "ROOM_TYPE_UNSUPPORTED",
            f"{room.name} cannot become a {_type_label(op.room_type)}: {reason}, so a type change "
            f"to or from {_type_label(fixed)} is not supported.",
            element_id=room.id,
        )
    props = room.properties.model_copy(
        update={"room_type": op.room_type, "zone": room_zone(op.room_type)}
    )
    return _replace_room(
        model, room.model_copy(update={"properties": props, "origin": Origin.USER})
    )
