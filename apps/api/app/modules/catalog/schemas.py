"""Knowledge-pack document schemas (docs/knowledge.md §3).

Units: building quantities are SI (meters, m², degrees only where a source states angles);
drawing quantities are paper-space millimetres. Every numeric parameter must say which, through
the unit suffix of its own key or of an enclosing key (checked by `integrity.py`).
"""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, JsonValue, StringConstraints, model_validator

from app.modules.building.enums import RelationshipKind, RoomType
from app.modules.catalog.provenance import (
    Confidence,
    KnowledgeModel,
    Paraphrase,
    Provenanced,
    ShortText,
    SourceId,
    Status,
    Usage,
)

DOTTED_ID = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$"
PACK_ID = r"^[a-z][a-z0-9-]*$"
PACK_REF = r"^[a-z][a-z0-9-]*@[1-9][0-9]*$"

ItemId = Annotated[str, StringConstraints(pattern=DOTTED_ID, max_length=96)]
PackId = Annotated[str, StringConstraints(pattern=PACK_ID, max_length=64)]
PackRef = Annotated[str, StringConstraints(pattern=PACK_REF, max_length=80)]
Locale = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")]
Params = dict[str, JsonValue]


# --- Knowledge items ---------------------------------------------------------------------


class KnowledgeCategory(StrEnum):
    BUILDING_MODEL = "building_model"
    LAYOUT = "layout"
    DRAWING = "drawing"
    STRUCTURAL_DRAWING = "structural_drawing"
    MEP = "mep"
    REFERENCE = "reference"


class ItemKind(StrEnum):
    PRINCIPLE = "principle"  # a design/modelling principle (e.g. modular coordination)
    CONVENTION = "convention"  # a drawing or naming convention
    DEFINITION = "definition"  # what a concept means
    CODE_LIST = "code_list"  # letter/number codes and their meanings
    CONTENT_LIST = "content_list"  # what a drawing/set must contain
    DIMENSION_TABLE = "dimension_table"  # tabulated sizes (reference data, not rules)
    SYMBOL_SET = "symbol_set"  # symbol meanings and parameters (never the glyphs)
    EXAMPLE = "example"  # values shown in a worked example; never a rule
    REFERENCE = "reference"  # bibliographic or contextual information


class KnowledgeItem(Provenanced):
    id: ItemId
    kind: ItemKind
    category: KnowledgeCategory
    concept: ShortText
    statement: Paraphrase  # paraphrased, never quoted
    params: Params = Field(default_factory=dict)
    inferences: list[Paraphrase] = Field(default_factory=list)  # parts NOT stated in the source
    confidence: Confidence
    usage: Usage = Usage.RUNTIME_CANDIDATE
    intended_use: list[ItemId] = Field(default_factory=list)
    related: list[ItemId] = Field(default_factory=list)  # ontology classes / glossary terms


# --- Ontology ----------------------------------------------------------------------------


class ClassKind(StrEnum):
    BUILDING = "building"
    STOREY = "storey"
    ELEMENT = "element"
    SPACE = "space"
    GRID = "grid"
    SYSTEM = "system"


class ModelBinding(KnowledgeModel):
    """Link from an ontology class to the canonical BuildingModel vocabulary.

    The Pydantic building schema stays canonical (CLAUDE.md rule 7): bindings point at it and
    tests enforce that every element type, room type and relationship kind is bound once.
    """

    element_type: ShortText | None = None
    room_type: RoomType | None = None
    building_type: ShortText | None = None
    level: bool = False
    discriminator: ShortText | None = None  # optional property name, e.g. wall_kind
    value: str | bool | None = None

    @model_validator(mode="after")
    def _one_target(self) -> "ModelBinding":
        targets = [
            self.element_type is not None,
            self.room_type is not None,
            self.building_type is not None,
            self.level,
        ]
        if sum(targets) != 1:
            raise ValueError("bind exactly one of element_type, room_type, building_type or level")
        if (self.discriminator is None) != (self.value is None):
            raise ValueError("discriminator and value go together")
        if self.discriminator is not None and self.element_type is None:
            raise ValueError("discriminators only apply to element_type bindings")
        return self

    @property
    def is_primary(self) -> bool:
        return self.discriminator is None


class IfcMapping(KnowledgeModel):
    entity: Annotated[str, StringConstraints(pattern=r"^Ifc[A-Za-z]+$")]
    predefined_type: Annotated[str, StringConstraints(pattern=r"^[A-Z_]+$")] | None = None


class OntologyClass(Provenanced):
    id: ItemId  # class.<name>
    label: ShortText  # canonical English label
    kind: ClassKind
    parent: ItemId | None = None
    model_binding: ModelBinding | None = None
    ifc: IfcMapping | None = None
    in_scope_v1: bool = True  # residential, rectilinear, <= 3 storeys (CLAUDE.md rule 15)
    usage: Usage = Usage.RUNTIME_CANDIDATE


class Cardinality(KnowledgeModel):
    min: int = Field(ge=0)
    max: int | None = Field(default=None, ge=1)  # None = unbounded

    @model_validator(mode="after")
    def _ordered(self) -> "Cardinality":
        if self.max is not None and self.max < self.min:
            raise ValueError("max must be >= min")
        return self


class RelationshipDefinition(Provenanced):
    id: ItemId  # rel.<kind>
    label: ShortText
    model_binding: RelationshipKind
    source_classes: list[ItemId] = Field(min_length=1)
    target_classes: list[ItemId] = Field(min_length=1)
    per_source: Cardinality
    reserved: bool = False  # defined for a later phase (e.g. MEP); not produced yet


class OntologyDocument(KnowledgeModel):
    classes: list[OntologyClass] = Field(default_factory=list)
    relationships: list[RelationshipDefinition] = Field(default_factory=list)


# --- Glossary ----------------------------------------------------------------------------


class Term(Provenanced):
    """A canonical, language-neutral concept with its English wording (core pack)."""

    id: ItemId  # term.<name>
    preferred: ShortText
    synonyms: list[ShortText] = Field(default_factory=list)
    definition: Paraphrase | None = None
    class_ref: ItemId | None = None


class LocalizedTerm(Provenanced):
    """The wording of a canonical term in one locale (e.g. Russian terms from a source)."""

    term_id: ItemId
    locale: Locale
    preferred: ShortText
    synonyms: list[ShortText] = Field(default_factory=list)
    abbreviations: list[ShortText] = Field(default_factory=list)
    codes: dict[str, ShortText] = Field(default_factory=dict)  # e.g. {"spds_letter": "ПР"}


class GlossaryDocument(KnowledgeModel):
    terms: list[Term] = Field(default_factory=list)
    localized: list[LocalizedTerm] = Field(default_factory=list)


# --- Drawing profiles --------------------------------------------------------------------


class DrawingTopic(StrEnum):
    SETS = "sets"
    SHEETS = "sheets"
    SCALES = "scales"
    LINES = "lines"
    FONTS = "fonts"
    HATCHING = "hatching"
    DIMENSIONS = "dimensions"
    LEVEL_MARKS = "level_marks"
    AXES = "axes"
    CALLOUTS = "callouts"
    TITLES = "titles"
    VIEWS = "views"
    SYMBOLS = "symbols"
    SITE = "site"


class DrawingProfile(Provenanced):
    """A drawing-convention profile: a named, versioned grouping of drawing knowledge.

    Conventions are profile-scoped (e.g. `spds`), never global: another practice (ISO, a
    regional standard) is a different profile over different knowledge items.
    """

    id: PackId
    version: int = Field(ge=1)
    name: ShortText
    basis: list[ShortText] = Field(default_factory=list)
    era: ShortText | None = None
    description: Paraphrase
    topics: dict[DrawingTopic, list[ItemId]]

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


class DrawingProfilesDocument(KnowledgeModel):
    profiles: list[DrawingProfile] = Field(min_length=1)


# --- Region profiles ---------------------------------------------------------------------


class MeasurementSystem(StrEnum):
    METRIC = "metric"  # imperial display/input conversion arrives with K5


class Measurement(KnowledgeModel):
    internal: str = Field(default="si", pattern=r"^si$")  # always SI internally
    display: MeasurementSystem = MeasurementSystem.METRIC


class RegionProfile(KnowledgeModel):
    """Composes region-specific choices by reference; contains no rules or knowledge itself."""

    id: PackId
    version: int = Field(ge=1)
    name: ShortText
    status: Status
    description: Paraphrase
    region_codes: list[Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$")]]
    locales: list[Locale] = Field(min_length=1)
    measurement: Measurement = Field(default_factory=Measurement)
    rules_profile: PackRef
    drawing_profile: PackRef | None = None
    knowledge_packs: list[PackRef] = Field(min_length=1)

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


# --- Packs -------------------------------------------------------------------------------


class PackScopeKind(StrEnum):
    GLOBAL = "global"  # region- and practice-independent
    DRAWING_CONVENTION_PROFILE = "drawing_convention_profile"  # one drawing practice
    REGIONAL = "regional"  # one jurisdiction


class PackScope(KnowledgeModel):
    kind: PackScopeKind
    drawing_profile: PackId | None = None
    jurisdiction_context: list[Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]] = Field(
        default_factory=list
    )
    era: ShortText | None = None
    note: Paraphrase | None = None

    @model_validator(mode="after")
    def _checks(self) -> "PackScope":
        if self.kind == PackScopeKind.DRAWING_CONVENTION_PROFILE and self.drawing_profile is None:
            raise ValueError("a drawing-convention pack names its drawing_profile")
        return self


class PackContents(KnowledgeModel):
    items: list[ShortText] = Field(default_factory=list)
    ontology: list[ShortText] = Field(default_factory=list)
    glossary: list[ShortText] = Field(default_factory=list)
    drawing_profiles: list[ShortText] = Field(default_factory=list)
    components: list[ShortText] = Field(default_factory=list)  # families/types/assemblies (K2)
    patterns: list[ShortText] = Field(default_factory=list)  # layout patterns (Design Intel. V1)

    def files(self) -> list[str]:
        return [
            *self.items,
            *self.ontology,
            *self.glossary,
            *self.drawing_profiles,
            *self.components,
            *self.patterns,
        ]


class PackManifest(KnowledgeModel):
    id: PackId
    version: int = Field(ge=1)
    name: ShortText
    description: Paraphrase
    status: Status
    scope: PackScope
    sources: list[SourceId] = Field(min_length=1)
    depends_on: list[PackRef] = Field(default_factory=list)
    contents: PackContents

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


class ItemsDocument(KnowledgeModel):
    items: list[KnowledgeItem] = Field(min_length=1)
