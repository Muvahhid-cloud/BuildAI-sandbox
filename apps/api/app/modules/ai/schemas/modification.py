"""Structured output of a natural-language modification request (Phase 5, docs/ai-pipeline.md §11).

The model only interprets: for every change the user asked for it names an action and the
rooms/openings it concerns by their digest references (`R3`, `O5`), plus the numbers the user
stated. It never outputs coordinates, wall geometry, element ids or operations — the
deterministic resolver (modules/modification) turns each change into typed editing operations,
asks when something is missing or ambiguous, and validates the result. Unknown values stay null:
a null is a question for the user, never a guess.
"""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from app.modules.building.enums import RoomType

ChangeAction = Literal[
    "resize_room",  # make a room larger/smaller, wider/longer (moves one of its sides)
    "move_wall",  # move the wall between `room` and `other_room`
    "add_window",
    "add_door",  # between `room` and `other_room`
    "remove_opening",
    "resize_opening",
    "rename_room",
    "set_room_type",
    "remove_wall",  # between `room` and `other_room` (open up, or merge with merge_rooms)
]
CHANGE_ACTIONS: tuple[str, ...] = get_args(ChangeAction)
Side = Literal["north", "east", "south", "west"]


class DraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequestedChange(DraftModel):
    """One change the user asked for. Fields the user did not state stay null."""

    quote: str = Field(min_length=1, max_length=300, description="The user's words for it.")
    action: ChangeAction
    room: str | None = Field(
        default=None, max_length=12, description="Room reference (R1, R2, ...) it concerns."
    )
    room_hint: str | None = Field(
        default=None,
        max_length=80,
        description="The words the user used for the room when the reference is unclear.",
    )
    other_room: str | None = Field(
        default=None,
        max_length=12,
        description="Second room reference: the room on the other side of a wall or door.",
    )
    opening: str | None = Field(
        default=None, max_length=12, description="Opening reference (O1, O2, ...)."
    )
    opening_kind: Literal["window", "door"] | None = None
    side: Side | None = Field(default=None, description="Compass side, only if the user said it.")
    dimension: Literal["width", "length"] | None = Field(
        default=None, description="'wider' -> width, 'longer' -> length; null if not said."
    )
    direction: Literal["increase", "decrease"] | None = None
    amount_m: float | None = Field(
        default=None, gt=0, le=20, description="Distance in meters the user stated."
    )
    width_m: float | None = Field(default=None, gt=0, le=10)
    height_m: float | None = Field(default=None, gt=0, le=10)
    sill_m: float | None = Field(default=None, ge=0, le=5)
    new_name: str | None = Field(default=None, max_length=120)
    new_room_type: RoomType | None = None
    merge_rooms: bool | None = Field(
        default=None, description="remove_wall: true = make one room, false = open up."
    )


class UnsupportedRequest(DraftModel):
    quote: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=300)


class ModificationDraft(DraftModel):
    """The interpretation of a modification request."""

    understanding: str = Field(
        min_length=1, max_length=600, description="One or two sentences: what will change."
    )
    changes: list[RequestedChange] = Field(default_factory=list, max_length=12)
    unsupported: list[UnsupportedRequest] = Field(default_factory=list, max_length=12)
