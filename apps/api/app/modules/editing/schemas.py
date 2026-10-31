"""Plan-editing DTOs (docs/architecture.md §4: /projects/{id}/versions/{vid}/edits)."""

import uuid

from pydantic import BaseModel, Field

from app.modules.building.issues import Issue
from app.modules.building.model import BuildingModel
from app.modules.building.operations import Operation
from app.modules.building.summary import ModelSummary

MAX_OPERATIONS = 200


class EditRequest(BaseModel):
    """Operations relative to the base version, in the order they were made."""

    operations: list[Operation] = Field(min_length=1, max_length=MAX_OPERATIONS)


class EditSaveRequest(EditRequest):
    label: str | None = Field(default=None, max_length=120)


class EditRejectionOut(BaseModel):
    code: str
    message: str
    # Which operation of the batch was refused (None: the batch as a whole).
    index: int | None
    element_id: uuid.UUID | None
    related_ids: list[uuid.UUID]
    # The validation findings that block the edit (empty when the operation itself refused).
    issues: list[Issue]


class EditPreviewOut(BaseModel):
    """The model the operations would produce, or why they cannot be applied. Nothing is saved."""

    valid: bool
    model: BuildingModel | None
    summary: ModelSummary | None
    # New non-blocking findings (warnings), for display.
    warnings: list[Issue]
    changed_ids: list[uuid.UUID]
    rejection: EditRejectionOut | None
