"""What an AI provider must return for building generation, and the user's structured options.

`SpecificationDraft` is the *only* shape a model can answer with (it is the JSON Schema of the
structured output). It wraps a `BuildingSpecification` — intent, no
geometry — plus what the model understood, what it could not represent and what it needs to
ask. Everything in it is untrusted until Pydantic and the rules checks have accepted it.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.building.specification import ArchitecturalStyle, Budget, BuildingSpecification

MAX_SEED = 2**31 - 1

ShortText = Annotated[str, Field(min_length=1, max_length=300)]


class InterpretationOutcome(StrEnum):
    SPECIFICATION = "specification"
    CLARIFICATION = "clarification"


class SpecificationDraft(BaseModel):
    """Structured output of the interpreter model (validated like any untrusted input)."""

    model_config = ConfigDict(extra="forbid")

    outcome: InterpretationOutcome = Field(
        description="'specification' when the request is specific enough (use safe defaults "
        "and record them as assumptions); 'clarification' only when a missing or conflicting "
        "requirement would materially change the design."
    )
    understanding: str = Field(
        min_length=1,
        max_length=600,
        description="One or two sentences restating the building the user asked for.",
    )
    specification: BuildingSpecification | None = Field(
        default=None, description="Required when outcome is 'specification'."
    )
    clarification_questions: list[ShortText] = Field(
        default_factory=list,
        max_length=5,
        description="Required when outcome is 'clarification': at most 5 short questions.",
    )
    conflicts: list[ShortText] = Field(
        default_factory=list,
        max_length=10,
        description="Explicit requirements that conflict with each other or with the "
        "supported scope, explained in plain language. Never resolve them silently.",
    )
    unsupported_requests: list[ShortText] = Field(
        default_factory=list,
        max_length=10,
        description="Requested things the specification cannot express (e.g. a swimming "
        "pool, a basement, a sauna). They are reported to the user, not built.",
    )

    @model_validator(mode="after")
    def _outcome_payload(self) -> "SpecificationDraft":
        if self.outcome is InterpretationOutcome.SPECIFICATION and self.specification is None:
            raise ValueError("specification is required when outcome is 'specification'")
        if self.outcome is InterpretationOutcome.CLARIFICATION and not self.clarification_questions:
            raise ValueError("clarification_questions are required when outcome is 'clarification'")
        return self


class GenerationOptions(BaseModel):
    """Optional structured fields next to the prompt. They are explicit user requirements:
    the interpreter must honour them, and the generation service verifies that it did."""

    model_config = ConfigDict(extra="forbid")

    gross_floor_area_m2: float | None = Field(default=None, ge=20, le=2000)
    storeys: int | None = Field(default=None, ge=1, le=3)
    architectural_style: ArchitecturalStyle | None = None
    budget: Budget | None = None
    region_code: str | None = Field(default=None, min_length=2, max_length=16)
    seed: int = Field(default=0, ge=0, le=MAX_SEED)  # layout seed (not sent to the AI)
