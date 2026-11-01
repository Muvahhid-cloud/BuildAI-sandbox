"""Typed operations: the only way to change a BuildingModel (docs/building-model.md §5)."""

from app.modules.building.operations.apply import BatchRejected, apply_operation, apply_operations
from app.modules.building.operations.rooms import RoomSide, room_sides
from app.modules.building.operations.schemas import (
    MAX_WALL_MOVE_M,
    AddOpening,
    AddWall,
    MoveOpening,
    MoveWall,
    Operation,
    OperationRejected,
    RemoveElement,
    RemoveWall,
    RenameRoom,
    ResizeOpening,
    ResizeRoom,
    SetRoomType,
    SetWallFinish,
    SetWallHeight,
    SetWallThickness,
)

__all__ = [
    "MAX_WALL_MOVE_M",
    "AddOpening",
    "AddWall",
    "BatchRejected",
    "MoveOpening",
    "MoveWall",
    "Operation",
    "OperationRejected",
    "RemoveElement",
    "RemoveWall",
    "RenameRoom",
    "ResizeOpening",
    "ResizeRoom",
    "RoomSide",
    "SetRoomType",
    "SetWallFinish",
    "SetWallHeight",
    "SetWallThickness",
    "apply_operation",
    "apply_operations",
    "room_sides",
]
