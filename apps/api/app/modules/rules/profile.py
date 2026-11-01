"""BuildingRulesProfile schema (docs/building-model.md §10).

Dimensional rules are data, not code: the layout engine and the evaluators read every
minimum/maximum from the active profile. Profiles perform conceptual checks only.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.building.enums import RoomType


class RulesModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoomRule(RulesModel):
    min_area_m2: float = Field(ge=0)
    min_width_m: float = Field(gt=0)
    requires_window: bool = False
    per_car_area_m2: float | None = Field(default=None, gt=0)  # garages only


class CeilingRules(RulesModel):
    min_clear_height_m: float = Field(gt=0)
    min_clear_height_service_m: float = Field(gt=0)


class CorridorRules(RulesModel):
    min_width_m: float = Field(gt=0)
    min_width_accessible_m: float = Field(gt=0)


class DoorRule(RulesModel):
    min_width_m: float = Field(gt=0)
    min_height_m: float = Field(gt=0)


class GarageDoorRule(RulesModel):
    min_width_per_car_m: float = Field(gt=0)
    min_height_m: float = Field(gt=0)


class DoorRules(RulesModel):
    entrance: DoorRule
    interior: DoorRule
    bathroom: DoorRule
    garage: GarageDoorRule


class WindowRules(RulesModel):
    min_glazing_to_floor_ratio: float = Field(ge=0, le=1)
    min_sill_height_m: float = Field(ge=0)
    guard_required_below_sill_m: float = Field(ge=0)
    min_width_m: float = Field(gt=0)
    min_height_m: float = Field(gt=0)


class Range(RulesModel):
    min: float
    max: float

    @model_validator(mode="after")
    def _ordered(self) -> "Range":
        if self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class ComfortRule(Range):
    formula: Literal["2R+T"]


class StairRules(RulesModel):
    min_width_m: float = Field(gt=0)
    riser_m: Range
    tread_m: Range
    comfort_rule: ComfortRule
    min_headroom_m: float = Field(gt=0)
    max_risers_per_flight: int = Field(ge=2)
    landing_min_depth_m: float = Field(gt=0)


class OpeningRules(RulesModel):
    """Plan-edit placement of doors and windows (Phase 3.6 D2.3): a moved or added opening keeps
    this much solid wall to a wall corner/junction, to the end of its wall and to the next
    opening of the wall. Applied by the editing service to the openings an edit places, not to
    generated models (the layout engine places openings with its own, larger margins)."""

    min_clearance_m: float = Field(ge=0)


class WallRules(RulesModel):
    """Plan-edit wall properties (Phase 3.6 D2.5): the thickness range of exterior and interior
    walls and the lowest wall (a half-height partition). Checked on every model by
    rules.model_checks; generated walls lie inside these ranges."""

    exterior_thickness_m: Range
    interior_thickness_m: Range
    min_height_m: float = Field(gt=0)


class RailingRules(RulesModel):
    min_height_m: float = Field(gt=0)
    balcony_min_height_m: float = Field(gt=0)


class AccessibilityRules(RulesModel):
    enabled: bool = False
    step_free_entrance: Literal["off", "warning", "error"] = "warning"
    turning_circle_diameter_m: float = Field(gt=0)
    accessible_door_clear_width_m: float = Field(gt=0)


class BuildingRulesProfile(RulesModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$", max_length=64)
    version: int = Field(ge=1)
    name: str
    extends: str | None = None  # "id@version" of the parent profile (resolved by the loader)
    disclaimer: str
    units: Literal["m"]
    rooms: dict[str, RoomRule]
    ceiling: CeilingRules
    corridors: CorridorRules
    doors: DoorRules
    windows: WindowRules
    openings: OpeningRules | None = None  # None: no clearance rule (profiles before D2.3)
    walls: WallRules | None = None  # None: no wall thickness/height rules (before D2.5)
    stairs: StairRules
    railings: RailingRules
    accessibility: AccessibilityRules

    @model_validator(mode="after")
    def _room_keys(self) -> "BuildingRulesProfile":
        if "default" not in self.rooms:
            raise ValueError("rooms.default is required")
        known = {t.value for t in RoomType}
        unknown = sorted(k for k in self.rooms if k != "default" and k not in known)
        if unknown:
            raise ValueError(f"unknown room types in rooms: {', '.join(unknown)}")
        return self

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    def room(self, room_type: RoomType | str) -> RoomRule:
        return self.rooms.get(str(room_type), self.rooms["default"])

    def room_rule_ref(self, room_type: RoomType | str) -> str:
        key = str(room_type) if str(room_type) in self.rooms else "default"
        return self.rule_ref(f"rooms.{key}")

    def rule_ref(self, path: str) -> str:
        return f"{self.ref}:{path}"
