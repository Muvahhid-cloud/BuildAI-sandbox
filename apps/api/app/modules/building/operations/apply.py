"""Apply a batch of operations: pure (model, ops) -> model.

The result is re-validated through the Pydantic schema (rounding to 1 mm, enums, shapes), so an
operation can never hand back a document the schema would not accept. Whether the result is a
*good* model (invariants, rules) is decided by the caller (modules/editing) with the same
validators every generated model passes.
"""

from collections.abc import Sequence

from app.modules.building.model import BuildingModel, ModelMetadata
from app.modules.building.operations.openings import (
    add_opening,
    move_opening,
    remove_element,
    resize_opening,
)
from app.modules.building.operations.rooms import rename_room, resize_room, set_room_type
from app.modules.building.operations.schemas import (
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
)
from app.modules.building.operations.wall_addition import add_wall
from app.modules.building.operations.wall_removal import remove_wall
from app.modules.building.operations.walls import move_wall

EDITED_SUFFIX = " · edited"


class BatchRejected(OperationRejected):
    """An operation of a batch was refused; `index` is its position in the batch."""

    def __init__(self, index: int, cause: OperationRejected) -> None:
        super().__init__(
            cause.code,
            cause.message,
            element_id=cause.element_id,
            related_ids=cause.related_ids,
        )
        self.index = index


def apply_operation(model: BuildingModel, op: Operation) -> BuildingModel:
    if isinstance(op, MoveWall):
        return move_wall(model, op)
    if isinstance(op, ResizeRoom):
        return resize_room(model, op)
    if isinstance(op, MoveOpening):
        return move_opening(model, op)
    if isinstance(op, AddOpening):
        return add_opening(model, op)
    if isinstance(op, RemoveElement):
        return remove_element(model, op)
    if isinstance(op, ResizeOpening):
        return resize_opening(model, op)
    if isinstance(op, RemoveWall):
        return remove_wall(model, op)
    if isinstance(op, RenameRoom):
        return rename_room(model, op)
    if isinstance(op, SetRoomType):
        return set_room_type(model, op)
    if isinstance(op, AddWall):
        return add_wall(model, op)
    raise OperationRejected("OPERATION_UNKNOWN", f"Unsupported operation {op!r}")


def apply_operations(model: BuildingModel, ops: Sequence[Operation]) -> BuildingModel:
    """Apply `ops` in order. Raises `BatchRejected` naming the first operation refused."""
    current = model
    for i, op in enumerate(ops):
        try:
            current = apply_operation(current, op)
        except OperationRejected as err:
            raise BatchRejected(i, err) from err
    if not ops:
        return model
    generator = current.metadata.generator
    if not generator.endswith(EDITED_SUFFIX):
        generator = (generator[: 200 - len(EDITED_SUFFIX)] + EDITED_SUFFIX).strip()
    edited = current.model_copy(
        update={"metadata": ModelMetadata(source="operations", generator=generator)}
    )
    return BuildingModel.model_validate(edited.model_dump(mode="json"))
