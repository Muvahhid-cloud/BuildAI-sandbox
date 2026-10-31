"""HTTP contracts of AI generation. Exported to packages/schema (`pnpm schema`) so the web app
uses generated types and validators instead of a hand-written copy."""

import uuid
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ai.schemas.generation import GenerationOptions
from app.modules.building.issues import Issue
from app.modules.building.requirements import RequirementCheck
from app.modules.building.specification import Assumption, BuildingSpecification
from app.modules.building.summary import ModelSummary

MAX_PROMPT_CHARS = 4000

GenerationStatus = Literal["queued", "running", "completed", "needs_clarification", "failed"]
# Real backend stages, in order ("repairing" only happens when the first answer was invalid).
GenerationStage = Literal[
    "queued",
    "interpreting",
    "validating",
    "repairing",
    "layout",
    "checking",
    "saving",
    "done",
]
GENERATION_STAGES: tuple[str, ...] = get_args(GenerationStage)


class AIGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None: create a new project for this design (named after the interpreted specification).
    project_id: uuid.UUID | None = None
    prompt: str = Field(min_length=3, max_length=MAX_PROMPT_CHARS)
    options: GenerationOptions = GenerationOptions()


class GenerationErrorOut(BaseModel):
    code: str
    message: str
    details: list[Issue] = Field(default_factory=list)


class AIGenerationSummaryOut(BaseModel):
    """One entry of a project's generation history."""

    id: uuid.UUID
    project_id: uuid.UUID
    status: GenerationStatus
    stage: GenerationStage | None
    prompt: str
    provider: str
    model: str
    understanding: str | None
    version_id: uuid.UUID | None
    version_number: int | None
    clarification_questions: list[str]
    error: GenerationErrorOut | None
    repair_count: int
    duration_ms: int | None
    created_at: datetime
    finished_at: datetime | None


class AIGenerationOut(AIGenerationSummaryOut):
    """Full generation record: what was asked, what the AI understood, what was built."""

    options: GenerationOptions
    prompt_version: str
    seed: int
    rules_profile: str
    engine_version: str | None
    specification: BuildingSpecification | None
    assumptions: list[Assumption]
    # Everything that deviates from the request: AI conflicts/unsupported requests/repairs,
    # spec warnings, layout deviations and rules findings at generation time.
    warnings: list[Issue]
    summary: ModelSummary | None  # of the generated version
    checks: list[RequirementCheck]  # requested vs delivered
    input_tokens: int
    output_tokens: int
    started_at: datetime | None


class AIGenerationList(BaseModel):
    items: list[AIGenerationSummaryOut]
