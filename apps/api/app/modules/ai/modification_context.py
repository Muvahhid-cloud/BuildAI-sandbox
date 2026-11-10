"""The model digest an AI modification request is planned against (docs/ai-pipeline.md §11).

A model never sees the BuildingModel or any id: rooms and openings get short references (`R1`,
`O1`) with the facts a person would use to describe them — name, type, floor, area, extent, which
room or facade lies beyond each side, opening sizes. The deterministic resolver
(modules/modification) maps the references back with the same function, so a reference means the
same element on both sides. Pure: a function of the model only.
"""

import math
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.modules.building.elements import Door, Room, Wall, Window
from app.modules.building.enums import RoomType, WallKind
from app.modules.building.facades import facade_of_normal
from app.modules.building.geometry import polygon_edges, segment_overlap_length
from app.modules.building.model import BuildingModel
from app.modules.building.operations.openings import door_rooms, host_of
from app.modules.building.operations.relationships import room_ring
from app.modules.building.operations.rooms import FIXED_ROOM_TYPES, RoomSide, room_sides
from app.modules.building.primitives import EPS

Compass = Literal["north", "east", "south", "west"]


class DigestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SideDigest(DigestModel):
    side: Compass
    length_m: float
    # What lies beyond this side: neighbouring room refs, or the facade when it is exterior.
    neighbours: tuple[str, ...]
    facade: str | None  # front | rear | left | right (exterior sides only)
    has_wall: bool


class RoomRefDigest(DigestModel):
    ref: str
    name: str
    room_type: str
    level: int
    area_m2: float
    width_m: float  # extent west-east
    depth_m: float  # extent south-north
    sides: tuple[SideDigest, ...]
    windows: int
    doors: int


class OpeningRefDigest(DigestModel):
    ref: str
    kind: Literal["window", "door"]
    name: str
    level: int
    rooms: tuple[str, ...]  # room refs it opens into
    side: Compass | None  # outward direction of its wall (exterior walls only)
    width_m: float
    height_m: float
    sill_m: float


class ModificationContext(DigestModel):
    levels: tuple[str, ...]  # level names, index = level number
    rooms: tuple[RoomRefDigest, ...]
    openings: tuple[OpeningRefDigest, ...]
    # Room types a type change may use (staircase, garage and outdoor rooms are fixed).
    room_types: tuple[str, ...]


def compass_of(outward: tuple[float, float]) -> Compass:
    ox, oy = outward
    if abs(ox) >= abs(oy):
        return "east" if ox > 0 else "west"
    return "north" if oy > 0 else "south"


def _level_index(model: BuildingModel) -> dict[uuid.UUID | None, int]:
    return {lv.id: lv.index for lv in model.levels}


def ordered_rooms(model: BuildingModel) -> list[Room]:
    """Rooms in reference order: by floor, then semantic key (stable across replays)."""
    levels = _level_index(model)
    return sorted(
        (e for e in model.elements if isinstance(e, Room)),
        key=lambda r: (levels.get(r.level_id, 0), r.semantic_key, str(r.id)),
    )


def ordered_openings(model: BuildingModel) -> list[Door | Window]:
    levels = _level_index(model)
    return sorted(
        (e for e in model.elements if isinstance(e, Door | Window)),
        key=lambda o: (levels.get(o.level_id, 0), o.type, o.semantic_key, str(o.id)),
    )


def room_refs(model: BuildingModel) -> dict[str, Room]:
    return {f"R{i + 1}": r for i, r in enumerate(ordered_rooms(model))}


def opening_refs(model: BuildingModel) -> dict[str, Door | Window]:
    return {f"O{i + 1}": o for i, o in enumerate(ordered_openings(model))}


def side_neighbours(model: BuildingModel, room: Room, side: RoomSide) -> list[Room]:
    """Rooms of the same floor whose boundary shares a length with this side."""
    seg = (side.start, side.end)
    out = []
    for other in model.elements:
        if not isinstance(other, Room) or other.id == room.id or other.level_id != room.level_id:
            continue
        shared = max(
            (segment_overlap_length(seg, e) for e in polygon_edges(room_ring(other))), default=0.0
        )
        if shared > EPS:
            out.append(other)
    return sorted(out, key=lambda r: r.semantic_key)


def side_is_exterior(side: RoomSide) -> bool:
    return bool(side.walls) and all(w.properties.wall_kind == WallKind.EXTERIOR for w in side.walls)


def _extent(room: Room) -> tuple[float, float]:
    ring = room_ring(room)
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)


def opening_rooms(model: BuildingModel, opening: Door | Window) -> list[Room]:
    wall = host_of(model, opening)
    if wall is None:
        return []
    by_id = {e.id: e for e in model.elements}
    span = (opening.position.x, opening.position.x + opening.dimensions.width)
    return [r for i in door_rooms(model, wall, span) if isinstance(r := by_id.get(i), Room)]


def wall_outward(model: BuildingModel, wall: Wall) -> Compass | None:
    """Outward compass direction of an exterior wall (rooms lie on its inner side)."""
    if wall.properties.wall_kind != WallKind.EXTERIOR:
        return None
    # Exterior walls run counter-clockwise: the outside is to the right of start -> end.
    nx, ny = math.sin(wall.rotation.z), -math.cos(wall.rotation.z)
    return compass_of((nx, ny))


def build_modification_context(model: BuildingModel) -> ModificationContext:
    levels = _level_index(model)
    rooms = room_refs(model)
    ref_of = {r.id: ref for ref, r in rooms.items()}
    openings = opening_refs(model)
    room_openings: dict[uuid.UUID, list[Door | Window]] = {}
    for o in openings.values():
        for r in opening_rooms(model, o):
            room_openings.setdefault(r.id, []).append(o)

    room_digests = []
    for ref, room in rooms.items():
        sides = []
        for side in room_sides(model, room):
            if side.length < EPS:
                continue
            exterior = side_is_exterior(side)
            sides.append(
                SideDigest(
                    side=compass_of(side.outward),
                    length_m=round(side.length, 2),
                    neighbours=tuple(ref_of[n.id] for n in side_neighbours(model, room, side)),
                    facade=facade_of_normal(*side.outward).value if exterior else None,
                    has_wall=bool(side.walls),
                )
            )
        width, depth = _extent(room)
        own = room_openings.get(room.id, [])
        room_digests.append(
            RoomRefDigest(
                ref=ref,
                name=room.name,
                room_type=room.properties.room_type.value,
                level=levels.get(room.level_id, 0),
                area_m2=room.dimensions.area,
                width_m=width,
                depth_m=depth,
                sides=tuple(sides),
                windows=sum(1 for o in own if isinstance(o, Window)),
                doors=sum(1 for o in own if isinstance(o, Door)),
            )
        )

    opening_digests = []
    for ref, o in openings.items():
        wall = host_of(model, o)
        opening_digests.append(
            OpeningRefDigest(
                ref=ref,
                kind="window" if isinstance(o, Window) else "door",
                name=o.name,
                level=levels.get(o.level_id, 0),
                rooms=tuple(ref_of[r.id] for r in opening_rooms(model, o) if r.id in ref_of),
                side=wall_outward(model, wall) if wall else None,
                width_m=o.dimensions.width,
                height_m=o.dimensions.height,
                sill_m=o.position.z,
            )
        )

    return ModificationContext(
        levels=tuple(lv.name for lv in sorted(model.levels, key=lambda lv: lv.index)),
        rooms=tuple(room_digests),
        openings=tuple(opening_digests),
        room_types=tuple(t.value for t in RoomType if t not in FIXED_ROOM_TYPES),
    )
