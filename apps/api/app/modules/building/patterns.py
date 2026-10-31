"""Layout patterns: reusable arrangement recipes (Design Intelligence V1, docs/knowledge.md §3.6).

Plain building-level data, like `building.types` and `building.design`: the catalog turns
pattern records of a knowledge pack into `LayoutPattern` snapshots, the generation pipeline
passes a `PatternLibrary` to the layout engine, and the engine decides which patterns apply to
a specification (`layout/patterns.py`). Nothing here reads the catalog or decides geometry.

A pattern is a SOFT heuristic. Its recipe only changes the preferences the candidate search
scores (which band a room type likes, which room types like to be neighbours or apart, which
footprint proportions suit the arrangement). It never creates, relaxes or overrides a user
requirement or a rules-profile limit. Draft patterns may be applied under this policy and are
always reported with their status (CLAUDE.md, knowledge notes).
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.building.enums import RoomType
from app.modules.building.primitives import Frozen
from app.modules.building.types import ContentHash, SourceRef

PatternId = Annotated[str, Field(pattern=r"^pattern\.[a-z0-9_]+$", max_length=64)]
PatternText = Annotated[str, Field(min_length=1, max_length=500)]
PatternStatus = Literal["draft", "extracted", "needs_verification", "reviewed", "approved"]


class PatternTrigger(StrEnum):
    """Spec conditions a pattern answers (detected deterministically in layout/patterns.py)."""

    GARDEN_FOCUS = "garden_focus"  # rooms facing the rear, rear glazing, terrace, garden priority
    NARROW_SITE = "narrow_site"  # the plot/footprint limit forces a deep, narrow footprint
    OPEN_PLAN = "open_plan"  # open kitchen-living space, open_to pairs or the open-plan priority
    COMPACT_PROGRAM = "compact_program"  # small storeys or the compactness priority
    PRIVACY_ZONING = "privacy_zoning"  # separate_from requests or the privacy priority
    COURTYARD = "courtyard"  # an enclosed outdoor room (no engine support yet)


class EngineSupport(StrEnum):
    """How much of the pattern the current (double-loaded corridor) engine can realise."""

    FULL = "full"
    PARTIAL = "partial"  # some aspects are realised; `limitations` names the rest
    NONE = "none"  # documented only; never applied


class StatementKind(StrEnum):
    """Kind of a pattern statement. Kept apart so a general principle is never presented as a
    source-backed rule, and an experimental heuristic never as either."""

    PRINCIPLE = "principle"  # widely taught design principle, stated without a source claim
    SOURCE_RULE = "source_rule"  # backed by a cited, reviewed source (none yet)
    HEURISTIC = "heuristic"  # BuildAI's own experimental rule of thumb (the recipe values)


class PatternStatement(Frozen):
    kind: StatementKind
    text: PatternText


Side = Literal["garden", "street", "wing"]  # wing: the private wing of an L footprint


class BandPreference(Frozen):
    """Room types that should reach the garden (rear) or street (front) facade."""

    room_types: list[RoomType] = Field(min_length=1)
    side: Side
    weight: float = Field(gt=0, le=3)  # penalty when placed on the other side


class RoomTypePair(Frozen):
    a: RoomType
    b: RoomType
    weight: float = Field(gt=0, le=3)


class PatternRecipe(Frozen):
    """What the layout engine reads. All of it is scored, nothing is enforced."""

    # A footprint topology to consider IN ADDITION to the rectangular one: its candidates
    # compete with rectangular ones in the evaluation; it never replaces them (V1.1).
    topology: Literal["l_shape"] | None = None
    # Preferred footprint width/depth (x along the street); penalised outside the range.
    footprint_aspect: tuple[float, float] | None = None
    band_preferences: list[BandPreference] = Field(default_factory=list)
    affinities: list[RoomTypePair] = Field(default_factory=list)  # like to share a wall
    separations: list[RoomTypePair] = Field(default_factory=list)  # should not share a wall

    @model_validator(mode="after")
    def _range(self) -> "PatternRecipe":
        if self.footprint_aspect is not None:
            low, high = self.footprint_aspect
            if not 0 < low <= high:
                raise ValueError("footprint_aspect must be (low, high) with 0 < low <= high")
        return self


class PatternApplicability(Frozen):
    triggers: list[PatternTrigger] = Field(min_length=1)  # applies when any one is present
    required_triggers: list[PatternTrigger] = Field(default_factory=list)  # ... and all these
    # Below this storey area (m²) the pattern does not apply (classification threshold).
    min_floor_area_per_storey_m2: float | None = Field(default=None, gt=0, le=1000)
    # COMPACT_PROGRAM also fires for storeys up to this area (m²); a classification threshold
    # of the heuristic, not a dimensional rule of the design.
    max_floor_area_per_storey_m2: float | None = Field(default=None, gt=0, le=1000)
    storeys: list[int] = Field(default_factory=lambda: [1, 2, 3])


class LayoutPattern(Frozen):
    """A pattern as the engine and reports see it (snapshot of a catalog record)."""

    id: PatternId
    name: Annotated[str, Field(min_length=1, max_length=120)]
    source: SourceRef  # catalog pack ref, e.g. "buildai-layout-patterns@1"
    status: PatternStatus
    content_sha256: ContentHash
    intent: PatternText  # intended use
    context: PatternText  # suitable building context
    relationships: PatternText  # room relationships / adjacency graph in words
    circulation: PatternText
    privacy: PatternText
    daylight: PatternText
    facade: PatternText
    tradeoffs: list[PatternText] = Field(default_factory=list)
    limitations: list[PatternText] = Field(default_factory=list)
    statements: list[PatternStatement] = Field(min_length=1)
    engine_support: EngineSupport
    applicability: PatternApplicability
    recipe: PatternRecipe


class PatternLibrary(Frozen):
    """The patterns generation may draw on (sorted by id)."""

    patterns: list[LayoutPattern] = Field(default_factory=list)

    def get(self, pattern_id: str) -> LayoutPattern | None:
        return next((p for p in self.patterns if p.id == pattern_id), None)
