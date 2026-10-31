"""Units, precision and small value types shared by every building element.

Conventions (docs/building-model.md §1): SI meters, radians, right-handed Z-up.
Lengths are rounded to 1 mm and angles to 1e-6 rad on validation, so serialized models are
stable and comparisons can use EPS.
"""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

EPS = 1e-4  # meters; geometric comparison tolerance
LENGTH_DECIMALS = 3  # 1 mm
AREA_DECIMALS = 2
ANGLE_DECIMALS = 6

MATERIAL_ID_PATTERN = r"^[a-z][a-z0-9_]*$"


def _round_length(v: float) -> float:
    return round(v, LENGTH_DECIMALS) + 0.0  # "+ 0.0" normalizes -0.0


def _round_area(v: float) -> float:
    return round(v, AREA_DECIMALS) + 0.0


def _round_angle(v: float) -> float:
    return round(v, ANGLE_DECIMALS) + 0.0


Meters = Annotated[float, Field(allow_inf_nan=False), AfterValidator(_round_length)]
PositiveMeters = Annotated[float, Field(gt=0, allow_inf_nan=False), AfterValidator(_round_length)]
NonNegativeMeters = Annotated[
    float, Field(ge=0, allow_inf_nan=False), AfterValidator(_round_length)
]
SquareMeters = Annotated[float, Field(ge=0, allow_inf_nan=False), AfterValidator(_round_area)]
Radians = Annotated[float, Field(allow_inf_nan=False), AfterValidator(_round_angle)]
MaterialId = Annotated[str, Field(pattern=MATERIAL_ID_PATTERN, max_length=64)]
# sRGB display color, lower-case "#rrggbb". Visual only: never a construction property.
HexColor = Annotated[str, Field(pattern=r"^#[0-9a-f]{6}$")]


class Frozen(BaseModel):
    """Base for all building-model value objects: immutable, no unknown fields.

    `json_schema_serialization_defaults_required` makes fields with defaults *required* in the
    exported (serialization) JSON Schema, because serialized models always contain them.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_serialization_defaults_required=True,
    )


class Vec2(Frozen):
    x: Meters
    y: Meters


class Vec3(Frozen):
    x: Meters
    y: Meters
    z: Meters


class Rotation(Frozen):
    """Euler angles in radians, XYZ order. Most elements only use `z` (yaw, CCW from +X)."""

    x: Radians = 0.0
    y: Radians = 0.0
    z: Radians = 0.0
