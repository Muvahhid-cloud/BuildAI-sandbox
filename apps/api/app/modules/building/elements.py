"""Building elements. Canonical schema — TS types and Zod validators are generated from these.

Every element carries: id, type, name, layer, level_id, position, rotation, dimensions,
material_id, properties, relationships, origin, locked, semantic_key (CLAUDE.md rule 3), and
since schema 1.1.0 an optional `type_ref` into `BuildingModel.types` (building/types.py).

`position` is an element-local anchor whose meaning is defined per type (see each class);
absolute elevation = level.elevation + position.z. Polygon properties (room boundary, slab and
roof outlines) are expressed relative to `position`, rotated by `rotation.z`.
"""

import uuid
from typing import Annotated, Literal

from pydantic import Field

from app.modules.building.enums import (
    DoorKind,
    DoorSwing,
    FurnitureKind,
    Layer,
    Origin,
    RailingKind,
    RelationshipKind,
    RoofType,
    RoomType,
    SlabKind,
    StairType,
    WallAlignment,
    WallKind,
    WindowKind,
    Zone,
)
from app.modules.building.primitives import (
    Frozen,
    HexColor,
    MaterialId,
    Meters,
    NonNegativeMeters,
    PositiveMeters,
    Rotation,
    SquareMeters,
    Vec2,
    Vec3,
)
from app.modules.building.specification import WindowStyle
from app.modules.building.types import AssemblyId, TypeId

Polygon = Annotated[list[Vec2], Field(min_length=3)]


class Relationship(Frozen):
    kind: RelationshipKind
    target_id: uuid.UUID


class ElementBase(Frozen):
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    layer: Layer
    level_id: uuid.UUID | None
    position: Vec3
    rotation: Rotation
    material_id: MaterialId | None
    relationships: list[Relationship]
    origin: Origin
    locked: bool = False
    semantic_key: str = Field(min_length=1, max_length=200)
    type_ref: TypeId | None = None  # id of a TypeSnapshot in BuildingModel.types (1.1.0)


# --- Wall ----------------------------------------------------------------------------------


class WallDimensions(Frozen):
    length: PositiveMeters
    thickness: PositiveMeters
    height: PositiveMeters


class WallProperties(Frozen):
    wall_kind: WallKind
    alignment: WallAlignment = WallAlignment.CENTER
    load_bearing: bool
    # Face finishes. "left" is the +normal side of the axis (normal = (-sin θ, cos θ)).
    # For exterior walls authored counter-clockwise, left = interior, right = exterior.
    finish_left_id: MaterialId | None
    finish_right_id: MaterialId | None
    # Display colors of the faces (1.2.0, K3 appearance intent): the finish material is drawn in
    # this color. Visual only; the finish material (and anything derived from it) is unchanged.
    finish_left_color: HexColor | None = None
    finish_right_color: HexColor | None = None


class Wall(ElementBase):
    """Straight wall. position = axis start point; rotation.z = axis direction."""

    type: Literal["wall"] = "wall"
    dimensions: WallDimensions
    properties: WallProperties


# --- Openings --------------------------------------------------------------------------------


class DoorDimensions(Frozen):
    width: PositiveMeters
    height: PositiveMeters
    thickness: PositiveMeters


class DoorProperties(Frozen):
    door_kind: DoorKind
    swing: DoorSwing
    frame_material_id: MaterialId | None


class Door(ElementBase):
    """Door hosted by a wall (relationship hosted_by).

    position is in HOST-WALL-LOCAL coordinates: x = offset of the opening's start edge from the
    wall start along the axis, y = 0, z = 0 (door sill). rotation is unused (zeros).
    """

    type: Literal["door"] = "door"
    dimensions: DoorDimensions
    properties: DoorProperties


class WindowDimensions(Frozen):
    width: PositiveMeters
    height: PositiveMeters


class WindowProperties(Frozen):
    window_kind: WindowKind
    frame_material_id: MaterialId | None
    mullions: int = Field(ge=0, le=12)  # vertical glazing bars; panes = mullions + 1
    # Design size class the engine chose it as (1.2.0): standard | large | panoramic for the
    # main windows of habitable rooms; None for service/stair windows and older models.
    size_class: WindowStyle | None = None


class Window(ElementBase):
    """Window hosted by a wall. position (host-wall-local): x = start offset, z = sill height."""

    type: Literal["window"] = "window"
    dimensions: WindowDimensions
    properties: WindowProperties


# --- Spaces and horizontal elements -----------------------------------------------------------


class RoomDimensions(Frozen):
    area: SquareMeters  # of `boundary`
    perimeter: PositiveMeters
    height: PositiveMeters  # clear height


class RoomProperties(Frozen):
    room_type: RoomType
    zone: Zone
    boundary: Polygon  # CCW, rectilinear in v1, wall centerlines, relative to position
    floor_material_id: MaterialId | None
    ceiling_assembly_ref: AssemblyId | None = None  # AssemblySnapshot of kind ceiling (1.1.0)


class Room(ElementBase):
    """A space (not a solid). position = origin of `boundary`."""

    type: Literal["room"] = "room"
    dimensions: RoomDimensions
    properties: RoomProperties


class SlabDimensions(Frozen):
    thickness: PositiveMeters
    area: SquareMeters  # outline minus holes


class SlabProperties(Frozen):
    slab_kind: SlabKind
    outline: Polygon  # CCW, relative to position
    holes: list[Polygon]


class Slab(ElementBase):
    """Structural slab. position = outline origin; the TOP face is at position.z (slab hangs
    down by `thickness`)."""

    type: Literal["slab"] = "slab"
    dimensions: SlabDimensions
    properties: SlabProperties


class StairDimensions(Frozen):
    width: PositiveMeters
    run_length: PositiveMeters
    rise_total: PositiveMeters


class StairProperties(Frozen):
    stair_type: StairType
    risers: int = Field(ge=2, le=40)
    riser_height: PositiveMeters
    tread_depth: PositiveMeters
    from_level_id: uuid.UUID
    to_level_id: uuid.UUID


class Stair(ElementBase):
    """Straight flight. position = bottom corner at the first riser; the flight runs along local
    +x (rotation.z) and spans local +y by `width`. n risers, n-1 treads."""

    type: Literal["stair"] = "stair"
    dimensions: StairDimensions
    properties: StairProperties


class RoofDimensions(Frozen):
    thickness: PositiveMeters
    overhang: NonNegativeMeters


class RoofProperties(Frozen):
    roof_type: RoofType
    outline: Polygon  # eaves outline (incl. overhang), rectangle for pitched roofs in v1
    pitch_deg: float = Field(ge=0, le=60)
    ridge_axis: Literal["x", "y"]
    parapet_height: NonNegativeMeters  # flat roofs only


class Roof(ElementBase):
    """Roof. position = outline origin; position.z = top of the roof covering at the eaves."""

    type: Literal["roof"] = "roof"
    dimensions: RoofDimensions
    properties: RoofProperties


class RailingDimensions(Frozen):
    length: PositiveMeters
    height: PositiveMeters


class RailingProperties(Frozen):
    railing_kind: RailingKind
    rise: Meters  # vertical rise over `length` (0 = level; stairs are sloped)
    post_spacing: PositiveMeters


class Railing(ElementBase):
    """Guard rail. position = start of its base line; runs along local +x."""

    type: Literal["railing"] = "railing"
    dimensions: RailingDimensions
    properties: RailingProperties


class FurnitureDimensions(Frozen):
    width: PositiveMeters  # local x
    depth: PositiveMeters  # local y; the front faces local -y
    height: PositiveMeters


class FurnitureProperties(Frozen):
    furniture_kind: FurnitureKind
    # Catalog id of a real GLB/glTF asset. null = procedural placeholder geometry.
    asset_id: str | None


class Furniture(ElementBase):
    """Furniture/fixture placeholder. position = base center on the floor."""

    type: Literal["furniture"] = "furniture"
    dimensions: FurnitureDimensions
    properties: FurnitureProperties


Element = Annotated[
    Wall | Door | Window | Room | Slab | Stair | Roof | Railing | Furniture,
    Field(discriminator="type"),
]

ElementType = Literal[
    "wall", "door", "window", "room", "slab", "stair", "roof", "railing", "furniture"
]
