"""Typed model operations (docs/building-model.md §5).

An operation names WHAT to change in terms of existing element ids and plain numbers; the
applier (`apply.py`) works out the geometry. Operations are user/client input and therefore
untrusted: every reference is checked, and the result is validated by the editing service
before anything is shown as valid or saved.

Implemented: `move_wall` (D2.1), `resize_room` (D2.2, expressed as wall moves), for doors and
windows (D2.3) `move_opening`, `add_opening` and `remove_element`, (D2.4) `resize_opening`,
`remove_wall`, `rename_room`, `set_room_type` and `add_wall`, and (D2.5) exterior wall moves,
`set_wall_thickness`, `set_wall_finish` and `set_wall_height`. All join the `Operation` union
(discriminated on `op`).
"""

import uuid
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.building.enums import DoorKind, DoorSwing, RoomType, WindowKind
from app.modules.building.primitives import Frozen

#: Largest single wall move (m). Plans are ≤ ~30 m across; anything larger is a client bug.
MAX_WALL_MOVE_M = 20.0
#: Bounds of opening parameters (m): input sanity only, not design rules (those live in the
#: rules profile and are applied by the editing service).
MAX_OPENING_OFFSET_M = 100.0
MAX_OPENING_SIZE_M = 10.0
#: Plan coordinates accepted as input (m): v1 houses are a few tens of meters across.
MAX_PLAN_COORD_M = 1000.0


class MoveWall(Frozen):
    """Shift a wall sideways (perpendicular to its axis) by `offset_m`.

    Positive = towards the wall's left face (+v: the left of the direction from its start to its
    end). Walls that join it follow (they stretch or shrink), the rooms on both sides change
    shape and area, openings stay where they are on their walls, and furniture standing against
    the wall moves with it. An exterior wall moves its whole facade (D2.5, `envelope.py`): the
    walls on the same line on every storey, the slab and roof edges along it, and what hangs on
    it (canopy, balconies, terraces); shapes that cannot follow are refused with the reason.
    """

    op: Literal["move_wall"] = "move_wall"
    wall_id: uuid.UUID
    offset_m: float = Field(ge=-MAX_WALL_MOVE_M, le=MAX_WALL_MOVE_M, allow_inf_nan=False)


class ResizeRoom(Frozen):
    """Move one side of a room outwards (`delta_m` > 0, the room grows) or inwards (< 0).

    `edge` is the index of the side in the room's boundary as the model stores it: side i runs
    from vertex i to vertex i + 1. The side must run along walls over its whole length; the
    operation moves those walls (`MoveWall`), so the neighbouring rooms, joined walls, openings
    and furniture follow exactly as for a wall move. A side along an exterior wall moves the
    whole facade (D2.5). Open (wall-less) boundaries are refused for now.
    """

    op: Literal["resize_room"] = "resize_room"
    room_id: uuid.UUID
    edge: int = Field(ge=0, le=255)
    delta_m: float = Field(ge=-MAX_WALL_MOVE_M, le=MAX_WALL_MOVE_M, allow_inf_nan=False)


class MoveOpening(Frozen):
    """Place a door or window at `offset_m` along a wall (the offset of its start edge from the
    wall's start, as stored). `host_wall_id` names another wall to move it to (same level);
    omitted, it slides along its own wall. Identity, kind and size are kept; a door's
    `connects` rooms are recomputed."""

    op: Literal["move_opening"] = "move_opening"
    opening_id: uuid.UUID
    host_wall_id: uuid.UUID | None = None
    offset_m: float = Field(ge=0, le=MAX_OPENING_OFFSET_M, allow_inf_nan=False)


class AddOpening(Frozen):
    """A new door or window in a wall: start edge at `offset_m`, `width_m` by `height_m`, sill at
    `sill_m` (doors stand on the wall base: 0). The kind defaults to an interior door / a
    casement window; materials and the door leaf thickness follow the model's other openings
    of that kind."""

    op: Literal["add_opening"] = "add_opening"
    kind: Literal["door", "window"]
    host_wall_id: uuid.UUID
    offset_m: float = Field(ge=0, le=MAX_OPENING_OFFSET_M, allow_inf_nan=False)
    width_m: float = Field(gt=0, le=MAX_OPENING_SIZE_M, allow_inf_nan=False)
    height_m: float = Field(gt=0, le=MAX_OPENING_SIZE_M, allow_inf_nan=False)
    sill_m: float = Field(default=0.0, ge=0, le=MAX_OPENING_SIZE_M, allow_inf_nan=False)
    door_kind: DoorKind | None = None
    swing: DoorSwing | None = None
    window_kind: WindowKind | None = None


class RemoveElement(Frozen):
    """Remove an element. Only doors and windows can be removed this way (the wall closes over
    the opening); walls have `remove_wall`, other element types are refused."""

    op: Literal["remove_element"] = "remove_element"
    element_id: uuid.UUID


class ResizeOpening(Frozen):
    """Give a door or window a new width and height (and a window a new sill height).

    `offset_m` is the new start edge along the wall; omitted, the opening keeps its centre
    (shifted only as far as needed to stay inside its wall). `sill_m` omitted keeps the sill; a
    door's sill must stay 0. Identity, host, kind and materials are kept; a door's `connects`
    rooms are recomputed."""

    op: Literal["resize_opening"] = "resize_opening"
    opening_id: uuid.UUID
    width_m: float = Field(gt=0, le=MAX_OPENING_SIZE_M, allow_inf_nan=False)
    height_m: float = Field(gt=0, le=MAX_OPENING_SIZE_M, allow_inf_nan=False)
    sill_m: float | None = Field(default=None, ge=0, le=MAX_OPENING_SIZE_M, allow_inf_nan=False)
    offset_m: float | None = Field(default=None, ge=0, le=MAX_OPENING_OFFSET_M, allow_inf_nan=False)


class RemoveWall(Frozen):
    """Remove an interior wall. Its doors go with it (the gap becomes an open passage).

    `merge_rooms` false: the rooms on both sides keep their outlines and open into each other
    (an open, wall-less boundary). True: the wall must separate exactly two rooms, and they
    become one room (the larger keeps its id, name and type; the outline is the union)."""

    op: Literal["remove_wall"] = "remove_wall"
    wall_id: uuid.UUID
    merge_rooms: bool = False


class RenameRoom(Frozen):
    """Give a room a new name (trimmed; unique among the rooms of the design)."""

    op: Literal["rename_room"] = "rename_room"
    room_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)


class SetRoomType(Frozen):
    """Change a room's semantic type (and with it its zone). Geometry, name and identity stay;
    the rules for the new type (minimum size, window, door widths) are applied by the editing
    service like for every edit."""

    op: Literal["set_room_type"] = "set_room_type"
    room_id: uuid.UUID
    room_type: RoomType


class AddWall(Frozen):
    """Split a room with a new interior wall.

    The wall runs `direction` (east-west or north-south) through the point (`x_m`, `y_m`) inside
    the room, across the room from boundary to boundary; both ends must meet existing walls. The
    larger part keeps the room (id, name, type); the smaller part becomes a new room of
    `new_room_type` (default: the room's type). With `door_width_m` and `door_height_m` an
    interior door is placed in the middle of the new wall, so the new room can be reached."""

    op: Literal["add_wall"] = "add_wall"
    room_id: uuid.UUID
    direction: Literal["east_west", "north_south"]
    x_m: float = Field(ge=-MAX_PLAN_COORD_M, le=MAX_PLAN_COORD_M, allow_inf_nan=False)
    y_m: float = Field(ge=-MAX_PLAN_COORD_M, le=MAX_PLAN_COORD_M, allow_inf_nan=False)
    new_room_type: RoomType | None = None
    door_width_m: float | None = Field(
        default=None, gt=0, le=MAX_OPENING_SIZE_M, allow_inf_nan=False
    )
    door_height_m: float | None = Field(
        default=None, gt=0, le=MAX_OPENING_SIZE_M, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def _door_size_complete(self) -> "AddWall":
        if (self.door_width_m is None) != (self.door_height_m is None):
            raise ValueError("door_width_m and door_height_m go together")
        return self


#: Input sanity bounds of wall properties (m); the design limits come from the rules profile.
MAX_WALL_THICKNESS_M = 1.5
MAX_WALL_HEIGHT_M = 10.0


class SetWallThickness(Frozen):
    """A wall's thickness (D2.5). The axis stays where it is (room boundaries stay on wall
    axes), so both faces move by half the change; clear widths and areas are re-checked by the
    rules profile (`walls.*_thickness_m`). An exterior wall changes on every storey of its facade
    and the slab and roof edges on its outer face follow."""

    op: Literal["set_wall_thickness"] = "set_wall_thickness"
    wall_id: uuid.UUID
    thickness_m: float = Field(gt=0, le=MAX_WALL_THICKNESS_M, allow_inf_nan=False)


class SetWallFinish(Frozen):
    """The finish material (a material-library id) of one or both faces of a wall (D2.5).
    `left` = the +normal side (the interior of exterior walls), `right` = the other side (the
    facade). A chosen material replaces a display colour on that face."""

    op: Literal["set_wall_finish"] = "set_wall_finish"
    wall_id: uuid.UUID
    face: Literal["left", "right", "both"]
    material_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")


class SetWallHeight(Frozen):
    """A non-structural wall's height (D2.5): walls that carry a slab or a roof keep the storey
    height. Not above the storey's structural walls, not below the profile's lowest wall
    (`walls.min_height_m`), never below the head of an opening in it."""

    op: Literal["set_wall_height"] = "set_wall_height"
    wall_id: uuid.UUID
    height_m: float = Field(gt=0, le=MAX_WALL_HEIGHT_M, allow_inf_nan=False)


Operation = Annotated[
    MoveWall
    | ResizeRoom
    | MoveOpening
    | AddOpening
    | RemoveElement
    | ResizeOpening
    | RemoveWall
    | RenameRoom
    | SetRoomType
    | AddWall
    | SetWallThickness
    | SetWallFinish
    | SetWallHeight,
    Field(discriminator="op"),
]


class OperationRejected(Exception):  # noqa: N818 - domain outcome, not a programming error
    """An operation cannot be applied to this model. `code` is stable; `message` is user-facing
    and says what would go wrong and with which element."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        element_id: uuid.UUID | None = None,
        related_ids: list[uuid.UUID] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.element_id = element_id
        self.related_ids = related_ids or []
