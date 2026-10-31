import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.building.evaluation import DesignEvaluation
from app.modules.building.issues import Issue
from app.modules.building.model import BuildingModel
from app.modules.building.specification import BuildingSpecification
from app.modules.building.summary import ModelSummary


class GenerationProvenance(BaseModel):
    """Which AI generation produced a version (absent for spec-form and fixture versions)."""

    generation_id: uuid.UUID
    generation_type: Literal["building_generation"] = "building_generation"
    provider: str
    model: str
    prompt_version: str


class PatternUse(BaseModel):
    """A layout pattern applied as a soft heuristic, with its review status."""

    id: str
    name: str
    source: str
    status: str  # draft = unreviewed, experimental
    engine_support: str
    reasons: list[str]


class CandidateOut(BaseModel):
    order: int
    plan_score: float
    design_score: float
    must_met: bool
    footprint_m: tuple[float, float]
    chosen: bool


class TopologyOut(BaseModel):
    """Footprint topology of the version: measured on the validated model, and why (V1.1)."""

    generated: str  # rectangular | l_shape | t_shape | u_shape | courtyard | other
    requested: str | None
    mandatory: bool
    searched: list[str]
    reason: str
    explanation: str
    candidates: dict[str, int]
    built_valid: dict[str, int]
    # Why the requested shape cannot be generated at all (no generator yet / storey limit), V1.3.
    limitation: str | None = None


class GenerationReport(BaseModel):
    """What the layout engine (and, for AI versions, the interpreter) reported at generation."""

    warnings: list[Issue] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    generation: GenerationProvenance | None = None
    # Design Intelligence V1 (absent on older reports): how the chosen candidate answers the
    # spec, the layout patterns that steered it, and the other valid candidates it beat.
    evaluation: DesignEvaluation | None = None
    patterns: list[PatternUse] = Field(default_factory=list)
    candidates: list[CandidateOut] = Field(default_factory=list)
    topology: TopologyOut | None = None


class VersionSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    parent_version_id: uuid.UUID | None
    number: int
    label: str
    source: str
    schema_version: str
    engine_version: str
    rules_profile: str
    seed: int | None
    model_hash: str
    summary: ModelSummary
    created_at: datetime


class VersionList(BaseModel):
    items: list[VersionSummaryOut]


class VersionOut(VersionSummaryOut):
    prompt: str | None
    spec: BuildingSpecification | None
    model: BuildingModel
    report: GenerationReport | None
    # Evaluated on read against the version's rules profile + model invariants (warnings).
    issues: list[Issue]
