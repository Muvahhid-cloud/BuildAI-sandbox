"""Type and assembly snapshots carried by a BuildingModel (schema 1.1.0).

See docs/building-model.md §3.5.

A model is self-contained: every type or assembly an element refers to (`type_ref`,
`ceiling_assembly_ref`) is copied into `BuildingModel.types` / `assemblies` when the model is
generated, with the catalog record it came from (`source`) and that record's content hash. The
catalog can move on; a stored version keeps exactly what it was built with.

Type parameters are either FIXED (every element of the type must match them; checked by
`validation.py`) or DEFAULTS (`default_*`, `glazing_ratio`, `mullion_spacing`,
`width_per_car`): the design values the layout engine starts from, which an element may differ
from (e.g. a door narrowed to fit a short wall, a window lowered under a lintel).
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.building.enums import DoorKind, RailingKind, SlabKind, StairType, WallKind
from app.modules.building.primitives import (
    Frozen,
    MaterialId,
    NonNegativeMeters,
    PositiveMeters,
)

TYPE_ID_PATTERN = r"^type\.[a-z0-9_]+(\.[a-z0-9_]+)*$"
ASSEMBLY_ID_PATTERN = r"^assembly\.[a-z0-9_]+(\.[a-z0-9_]+)*$"
SOURCE_PATTERN = r"^[a-z][a-z0-9-]*@[1-9][0-9]*$"

TypeId = Annotated[str, Field(pattern=TYPE_ID_PATTERN, max_length=96)]
AssemblyId = Annotated[str, Field(pattern=ASSEMBLY_ID_PATTERN, max_length=96)]
SourceRef = Annotated[str, Field(pattern=SOURCE_PATTERN, max_length=80)]
ContentHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class LayerFunction(StrEnum):
    STRUCTURE = "structure"
    INSULATION = "insulation"
    MEMBRANE = "membrane"
    AIR_GAP = "air_gap"
    SCREED = "screed"
    FINISH = "finish"
    SURFACE = "surface"  # a coating/face finish whose thickness is not modelled (0)


class LayerSide(StrEnum):
    EXTERIOR = "exterior"
    INTERIOR = "interior"
    TOP = "top"
    BOTTOM = "bottom"


class AssemblyKind(StrEnum):
    WALL = "wall"
    FLOOR = "floor"
    ROOF = "roof"
    CEILING = "ceiling"


class Layer(Frozen):
    function: LayerFunction
    # Construction-material id (catalog); None = unspecified (e.g. the structural material of a
    # generic wall is not decided by the specification).
    material_id: MaterialId | None
    thickness: NonNegativeMeters
    side: LayerSide | None = None

    @model_validator(mode="after")
    def _thickness(self) -> "Layer":
        if (self.function == LayerFunction.SURFACE) != (self.thickness == 0):
            raise ValueError("only surface layers have zero thickness, and they always do")
        return self


class AssemblySnapshot(Frozen):
    """Layered build-up. Walls list layers exterior→interior; floors/roofs/ceilings top→bottom."""

    id: AssemblyId
    kind: AssemblyKind
    name: str = Field(min_length=1, max_length=120)
    layers: list[Layer] = Field(min_length=1)
    total_thickness: NonNegativeMeters  # = sum of layer thicknesses (checked by validation)
    source: SourceRef
    content_sha256: ContentHash


# --- Type parameters, one shape per element type --------------------------------------------


class WallTypeParams(Frozen):
    element_type: Literal["wall"] = "wall"
    wall_kind: WallKind  # fixed
    load_bearing: bool  # fixed


class SlabTypeParams(Frozen):
    element_type: Literal["slab"] = "slab"
    slab_kind: SlabKind  # fixed


class RoofTypeParams(Frozen):
    element_type: Literal["roof"] = "roof"  # thickness fixed through the assembly


class DoorTypeParams(Frozen):
    element_type: Literal["door"] = "door"
    door_kind: DoorKind  # fixed
    height: PositiveMeters  # fixed
    thickness: PositiveMeters  # fixed
    material_id: MaterialId | None  # fixed (leaf)
    frame_material_id: MaterialId | None  # fixed
    default_width: PositiveMeters | None = None  # engine preference; may narrow to fit
    width_per_car: PositiveMeters | None = None  # garage doors: width = cars x this


class WindowTypeParams(Frozen):
    element_type: Literal["window"] = "window"
    material_id: MaterialId | None  # fixed (glazing)
    frame_material_id: MaterialId | None  # fixed
    default_sill: NonNegativeMeters
    default_height: PositiveMeters
    default_width: PositiveMeters | None = None  # fixed-size windows (service, stair: None)
    glazing_ratio: float | None = Field(default=None, gt=0, le=1)  # target glazing/floor area
    mullion_spacing: PositiveMeters | None = None


class StairTypeParams(Frozen):
    element_type: Literal["stair"] = "stair"
    stair_type: StairType  # fixed
    width: PositiveMeters  # fixed
    material_id: MaterialId | None  # fixed


class RailingTypeParams(Frozen):
    element_type: Literal["railing"] = "railing"
    railing_kind: RailingKind  # fixed
    height: PositiveMeters  # fixed
    post_spacing: PositiveMeters  # fixed
    material_id: MaterialId | None  # fixed


TypeParams = Annotated[
    WallTypeParams
    | SlabTypeParams
    | RoofTypeParams
    | DoorTypeParams
    | WindowTypeParams
    | StairTypeParams
    | RailingTypeParams,
    Field(discriminator="element_type"),
]

# Roles the layout engine fills with a type, and the element type each role holds. A role
# mapping (catalog) assigns one type per role; K3 design systems will be alternative mappings.
TYPE_ROLES: dict[str, str] = {
    "wall.exterior": "wall",
    "wall.interior": "wall",
    "slab.ground": "slab",
    "slab.floor": "slab",
    "slab.balcony": "slab",
    "slab.terrace": "slab",
    "roof.main": "roof",
    "roof.garage": "roof",
    "door.entrance": "door",
    "door.interior": "door",
    "door.wet_room": "door",
    "door.sliding": "door",
    "door.garage": "door",
    "window.standard": "window",
    "window.large": "window",
    "window.panoramic": "window",
    "window.service": "window",
    "window.stair": "window",
    "stair.main": "stair",
    "railing.stair": "railing",
    "railing.balcony": "railing",
}

# Element types whose type must name an assembly, and the assembly kind it must be.
ASSEMBLY_KIND_FOR: dict[str, AssemblyKind] = {
    "wall": AssemblyKind.WALL,
    "slab": AssemblyKind.FLOOR,
    "roof": AssemblyKind.ROOF,
}


class TypeSnapshot(Frozen):
    id: TypeId
    family: Annotated[str, Field(pattern=r"^family\.[a-z0-9_]+(\.[a-z0-9_]+)*$", max_length=96)]
    name: str = Field(min_length=1, max_length=120)
    params: TypeParams
    assembly_id: AssemblyId | None
    source: SourceRef
    content_sha256: ContentHash

    @property
    def element_type(self) -> str:
        return self.params.element_type


class TypeSet(Frozen):
    """What the layout engine receives: the approved type for each role, plus assemblies.

    Produced by the catalog resolver (catalog/types/resolver.py) and passed by the generation
    pipeline; the layout engine never reads the catalog itself.
    """

    source: SourceRef  # the type pack
    mapping: str = Field(min_length=1, max_length=96)  # the role mapping used
    roles: dict[str, TypeId]
    types: list[TypeSnapshot]
    assemblies: list[AssemblySnapshot]

    def type_for(self, role: str) -> TypeSnapshot | None:
        type_id = self.roles.get(role)
        return next((t for t in self.types if t.id == type_id), None)

    def assembly(self, assembly_id: str | None) -> AssemblySnapshot | None:
        return next((a for a in self.assemblies if a.id == assembly_id), None)
