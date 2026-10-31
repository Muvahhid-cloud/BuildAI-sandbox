"""BuildingSpecification: what the client wants (intent), not geometry (docs/building-model.md §2).

Produced by a form today and by the AI interpreter later; consumed by the layout engine.
It never contains coordinates, wall geometry or element ids. Every vocabulary is closed (enums)
so both people and models can only ask for things the engine knows how to build.

Tier-1 validation (types, enums, ranges, required fields) is this Pydantic schema. Tier-2
(semantic, against the active BuildingRulesProfile) lives in `app.modules.rules.spec_checks`,
tier-3 (feasibility) in the layout engine.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.building.enums import RoofType

SPEC_SCHEMA_VERSION = "1.2.0"
# 1.2.0 (Design Intelligence V1, additive): rooms[].max_area_m2 (permissible area range),
# rooms[].separate_from, design.priorities, requirements[] (priority + origin of spec values),
# design.footprint_shape (V1.1, added before 1.2.0 was released; values t_shape, u_shape and
# courtyard added in V1.3, still before release - additive enum values).
# 1.1.0 (K3, additive): style.design_system, design (facade color, window intent), rooms[].faces.
# Every added field is optional / empty by default with "not requested" meaning, so an older
# document is a valid newer document with unchanged meaning.
SUPPORTED_SPEC_VERSIONS = ("1.0.0", "1.1.0", "1.2.0")

KEY_PATTERN = r"^[a-z][a-z0-9_]*$"
SpecKey = Annotated[str, Field(pattern=KEY_PATTERN, min_length=1, max_length=40)]
# Design-system id, e.g. "modern-minimal" (catalog record; availability is checked in tier 2).
DesignSystemRef = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", min_length=2, max_length=64)
]
# A palette color name ("yellow", "warm_beige") or "#rrggbb". The name is resolved against the
# fixed palette in building/appearance.py by tier-2 checks (APPEARANCE_INVALID otherwise).
ColorValue = Annotated[str, Field(pattern=r"^(#[0-9a-f]{6}|[a-z][a-z_]{1,30})$")]


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArchitecturalStyle(StrEnum):
    MODERN = "modern"
    MINIMALIST = "minimalist"
    CONTEMPORARY = "contemporary"
    CLASSIC = "classic"
    TRADITIONAL = "traditional"
    SCANDINAVIAN = "scandinavian"
    INDUSTRIAL = "industrial"
    MEDITERRANEAN = "mediterranean"
    LUXURY = "luxury"


class InteriorStyle(StrEnum):
    MINIMALIST = "minimalist"
    MODERN = "modern"
    CLASSIC = "classic"
    SCANDINAVIAN = "scandinavian"
    INDUSTRIAL = "industrial"
    LUXURY = "luxury"
    COZY = "cozy"


class WindowStyle(StrEnum):
    STANDARD = "standard"
    LARGE = "large"
    PANORAMIC = "panoramic"


class FacadeMaterial(StrEnum):
    """High-level facade choice; the layout engine maps it to material-library ids."""

    RENDER = "render"
    BRICK = "brick"
    CONCRETE = "concrete"
    TIMBER = "timber"


class FinishLevel(StrEnum):
    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"


class SpecRoomType(StrEnum):
    """Room types a specification may request. Circulation (entrance hall, corridors, stair
    core), the garage, balconies and terraces are produced by the engine from `features`."""

    BEDROOM = "bedroom"
    BATHROOM = "bathroom"
    WC = "wc"
    KITCHEN = "kitchen"
    LIVING = "living"
    DINING = "dining"
    OPEN_KITCHEN_LIVING = "open_kitchen_living"
    STUDY = "study"
    LAUNDRY = "laundry"
    UTILITY = "utility"
    STORAGE = "storage"
    PLANT_ROOM = "plant_room"


class FacadeSide(StrEnum):
    """Semantic facade of the house (building/facades.py). The street is on the model's south
    side (-y): front = street/entrance side, rear = garden/backyard side, left/right as seen
    from the street."""

    FRONT = "front"
    REAR = "rear"
    LEFT = "left"
    RIGHT = "right"


class RoomFeature(StrEnum):
    """Rooms attached to a bedroom and reached through it."""

    EN_SUITE = "en_suite"
    WALK_IN_CLOSET = "walk_in_closet"


class DesignPriority(StrEnum):
    """What the client cares about most (1.2.0). Each one raises the weight of the matching
    criterion in candidate evaluation (building/evaluation.py) and can select layout patterns;
    none of them is a hard requirement."""

    DAYLIGHT = "daylight"  # habitable rooms on facades, glazing
    PRIVACY = "privacy"  # bedrooms away from living spaces and the street
    GARDEN_CONNECTION = "garden_connection"  # living spaces on the garden (rear) side
    COMPACTNESS = "compactness"  # compact footprint, little circulation
    OPEN_PLAN = "open_plan"  # living, dining and kitchen as one connected space


class FootprintShape(StrEnum):
    """Footprint topology the client asks for (1.2.0). Recording a shape does not mean the
    engine can build it: what each shape needs and whether a generator exists is in
    building/footprint.py CAPABILITIES (docs/3d-engine.md §16.12). An unsupported shape is
    still recorded, so it is reported honestly instead of being dropped."""

    RECTANGULAR = "rectangular"
    L_SHAPE = "l_shape"
    T_SHAPE = "t_shape"  # one wing from the middle of the main bar (V1.3)
    U_SHAPE = "u_shape"  # two wings, one at each end, around a garden court (not generated)
    COURTYARD = "courtyard"  # rooms around an enclosed inner courtyard (not generated)


class Priority(StrEnum):
    """MUST = mandatory: a candidate that misses it is rejected and generation fails with the
    reason rather than relaxing it. SHOULD = preference: scored, reported when missed."""

    MUST = "must"
    SHOULD = "should"


class RequirementOrigin(StrEnum):
    USER_TEXT = "user_text"  # stated in the request
    FORM = "form"  # set in a form field
    ASSUMPTION = "assumption"  # inferred (see assumptions[])


class RequirementTrace(SpecModel):
    """Priority and origin of one spec value (1.2.0), so each design decision can be traced
    back to the request. `path` is a JSON pointer to a value that exists in the spec: a room's
    target_area_m2, an adjacent_to/open_to/separate_from entry, faces, or design.windows."""

    path: str = Field(pattern=r"^(/[a-z0-9_]+)+$", max_length=200)
    priority: Priority = Priority.SHOULD
    origin: RequirementOrigin = RequirementOrigin.USER_TEXT
    quote: str | None = Field(default=None, min_length=1, max_length=200)  # the user's words


class Targets(SpecModel):
    # Measured on wall centerlines over all storeys; excludes the attached garage, balconies
    # and terraces. None = derived from the room program by the layout engine.
    gross_floor_area_m2: float | None = Field(default=None, ge=20, le=2000)
    storeys: int = Field(ge=1, le=3)
    floor_to_floor_height_m: float = Field(default=3.0, ge=2.4, le=4.0)
    max_footprint_width_m: float | None = Field(default=None, gt=0, le=200)
    max_footprint_depth_m: float | None = Field(default=None, gt=0, le=200)


class Site(SpecModel):
    """Plot and setbacks. The street is on the model's south side (-y)."""

    plot_width_m: float | None = Field(default=None, gt=0, le=1000)
    plot_depth_m: float | None = Field(default=None, gt=0, le=1000)
    setback_front_m: float = Field(default=0, ge=0, le=100)
    setback_rear_m: float = Field(default=0, ge=0, le=100)
    setback_side_m: float = Field(default=0, ge=0, le=100)
    region_code: str | None = Field(default=None, min_length=2, max_length=16)


class RoofSpec(SpecModel):
    type: RoofType = RoofType.HIP
    pitch_deg: float | None = Field(default=None, ge=5, le=45)  # pitched roofs; None = default


class Style(SpecModel):
    architectural_style: ArchitecturalStyle = ArchitecturalStyle.MODERN
    interior_style: InteriorStyle | None = None
    roof: RoofSpec = RoofSpec()
    # Building-wide default window size; `design.windows` can emphasise chosen facades.
    window_style: WindowStyle = WindowStyle.STANDARD
    facade_material: FacadeMaterial = FacadeMaterial.RENDER
    interior_finish_level: FinishLevel = FinishLevel.STANDARD
    # Coherent set of components, finishes and palette (catalog, K3). Explicit values in this
    # spec always win over the system's defaults; values outside its allow-lists are conflicts.
    design_system: DesignSystemRef | None = None


class WindowIntent(SpecModel):
    """Where the emphasised (large/panoramic) windows go. Facades not listed keep
    `style.window_style`; excluded facades never get emphasised windows (standard ones)."""

    emphasis: WindowStyle = WindowStyle.PANORAMIC
    preferred_facades: list[FacadeSide] = Field(min_length=1, max_length=4)
    excluded_facades: list[FacadeSide] = Field(default_factory=list, max_length=3)


class DesignIntent(SpecModel):
    """Explicit visual/directional design requests (1.1.0). Null = not requested."""

    # Display color of the exterior wall faces (render appearance, not a material change).
    facade_color: ColorValue | None = None
    windows: WindowIntent | None = None
    # What matters most to the client (1.2.0); ordered, no duplicates.
    priorities: list[DesignPriority] = Field(default_factory=list, max_length=5)
    # Footprint topology asked for (1.2.0); null = the engine chooses (rectangular by default).
    footprint_shape: FootprintShape | None = None

    @model_validator(mode="after")
    def _unique_priorities(self) -> "DesignIntent":
        if len(set(self.priorities)) != len(self.priorities):
            raise ValueError("design priorities must not repeat")
        return self


class RoomRequirement(SpecModel):
    key: SpecKey  # stable semantic key, unique in the spec (used for ID stability)
    type: SpecRoomType
    name: str | None = Field(default=None, min_length=1, max_length=80)
    count: int = Field(default=1, ge=1, le=12)
    target_area_m2: float | None = Field(default=None, ge=1, le=200)  # per room
    min_area_m2: float | None = Field(default=None, ge=1, le=200)  # per room, on top of rules
    # Upper end of the permissible range (1.2.0): with min_area_m2 it bounds the delivered area.
    max_area_m2: float | None = Field(default=None, ge=1, le=200)  # per room
    level: int | None = Field(default=None, ge=0, le=2)  # 0 = ground floor; None = engine picks
    adjacent_to: list[SpecKey] = Field(default_factory=list, max_length=8)  # share a wall
    open_to: list[SpecKey] = Field(default_factory=list, max_length=4)  # open plan (no wall)
    features: list[RoomFeature] = Field(default_factory=list, max_length=2)
    # Facade the room should face (1.1.0). The double-loaded plan honours front and rear.
    faces: FacadeSide | None = None
    # Rooms that must not share a wall or an opening with this one (1.2.0), e.g. bedrooms
    # kept apart from the living room.
    separate_from: list[SpecKey] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _area_range(self) -> "RoomRequirement":
        low, high = self.min_area_m2, self.max_area_m2
        if low is not None and high is not None and low > high:
            raise ValueError(f"{self.key}: min_area_m2 is larger than max_area_m2")
        if high is not None and self.target_area_m2 is not None and self.target_area_m2 > high:
            raise ValueError(f"{self.key}: target_area_m2 is larger than max_area_m2")
        return self


class Garage(SpecModel):
    cars: int = Field(ge=1, le=3)


class Balcony(SpecModel):
    level: int = Field(ge=1, le=2)
    attached_to: SpecKey | None = None  # room key; None = engine picks a room on that level
    side: Literal["garden", "street"] = "garden"
    width_m: float | None = Field(default=None, ge=1.2, le=12)
    depth_m: float = Field(default=1.5, ge=0.8, le=3.0)


class Terrace(SpecModel):
    """Ground-level terrace on the garden side, reached from a living space."""

    attached_to: SpecKey | None = None
    width_m: float | None = Field(default=None, ge=2, le=20)
    depth_m: float = Field(default=3.0, ge=1.5, le=8)


class Features(SpecModel):
    garage: Garage | None = None
    balconies: list[Balcony] = Field(default_factory=list, max_length=4)
    terrace: Terrace | None = None


class Budget(SpecModel):
    """A constraint recorded with the spec. Nothing is costed from it in Phase 2."""

    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


JsonScalar = str | int | float | bool | None


class Assumption(SpecModel):
    """Something that was inferred rather than stated (shown to the user)."""

    path: str = Field(max_length=200)  # JSON pointer into the spec
    value: JsonScalar = None
    reason: str = Field(max_length=500)


class BuildingSpecification(SpecModel):
    schema_version: Literal["1.0.0", "1.1.0", "1.2.0"] = "1.2.0"
    building_type: Literal["single_family_house"] = "single_family_house"
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    targets: Targets
    site: Site | None = None
    style: Style = Style()
    rooms: list[RoomRequirement] = Field(min_length=1, max_length=40)
    features: Features = Features()
    design: DesignIntent = DesignIntent()
    budget: Budget | None = None
    # Priority and origin of individual values (1.2.0). Values without a trace are SHOULD.
    requirements: list[RequirementTrace] = Field(default_factory=list, max_length=60)
    assumptions: list[Assumption] = Field(default_factory=list, max_length=50)
    open_questions: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _unique_keys(self) -> "BuildingSpecification":
        keys = [r.key for r in self.rooms]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        if duplicates:
            raise ValueError(f"room keys must be unique: {', '.join(duplicates)}")
        paths = [t.path for t in self.requirements]
        repeated = sorted({p for p in paths if paths.count(p) > 1})
        if repeated:
            raise ValueError(f"requirements must not repeat a path: {', '.join(repeated)}")
        return self

    def priority_of(self, path: str) -> Priority:
        """MUST or SHOULD for the value at `path` (SHOULD when it has no trace)."""
        trace = self.trace(path)
        return trace.priority if trace is not None else Priority.SHOULD

    def trace(self, path: str) -> RequirementTrace | None:
        return next((t for t in self.requirements if t.path == path), None)
