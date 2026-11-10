"""Natural-language modification DTOs (docs/architecture.md §4: .../versions/{vid}/modify).

The client sends the request text plus the operations already in its editing session; the server
answers with a plan: the AI's interpretation, one entry per requested change with its typed
operations (or a question, or the reason it cannot be done), the candidate model and a measured
change summary. Nothing is stored; applying the plan is a normal edit save.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ai.schemas.modification import ChangeAction, ModificationDraft, UnsupportedRequest
from app.modules.building.diff import ModelDiff
from app.modules.building.operations import Operation
from app.modules.editing.schemas import MAX_OPERATIONS, EditPreviewOut

MAX_MODIFY_PROMPT_CHARS = 2000


class ModifyAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=120)


class ModifyPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=3, max_length=MAX_MODIFY_PROMPT_CHARS)
    # Operations of the client's editing session that are not saved yet (the plan builds on them).
    operations: list[Operation] = Field(default_factory=list, max_length=MAX_OPERATIONS)


class ModifyResolveRequest(ModifyPlanRequest):
    """Resolve an earlier interpretation again with the user's answers (no AI call)."""

    draft: ModificationDraft
    answers: list[ModifyAnswer] = Field(default_factory=list, max_length=60)


class QuestionOption(BaseModel):
    value: str
    label: str


class ClarificationQuestion(BaseModel):
    id: str  # "<change index>.<field>"
    change_index: int
    field: str
    text: str
    input: Literal["choice", "number", "text"]
    options: list[QuestionOption] = Field(default_factory=list)


ChangeStatus = Literal["planned", "needs_clarification", "refused", "unsupported"]


class PlannedChange(BaseModel):
    index: int
    quote: str
    action: ChangeAction
    status: ChangeStatus
    summary: str
    operations: list[Operation] = Field(default_factory=list)
    reason: str | None = None


PlanStatus = Literal["ready", "partial", "needs_clarification", "nothing_to_apply"]


class ModifyPlanOut(BaseModel):
    status: PlanStatus
    prompt: str
    understanding: str
    draft: ModificationDraft
    answers: list[ModifyAnswer]
    changes: list[PlannedChange]
    unsupported: list[UnsupportedRequest]
    questions: list[ClarificationQuestion]
    # The new operations, in order, to append to the editing session.
    operations: list[Operation]
    # The session's operations plus `operations`, validated like every edit (nothing stored).
    preview: EditPreviewOut | None
    # Measured changes from the session's current model to the candidate.
    diff: ModelDiff | None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
