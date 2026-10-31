"""Check a resolved TypeSet against the active BuildingRulesProfile (Phase 3.5 K2).

Types are knowledge/catalog data, rules are the only enforceable constraints: a type whose
values fall below a profile minimum is refused (the generation fails with the reasons) and is
never resized to fit. Checked are the values the layout engine would otherwise raise to the
rule minimum: door sizes by role, garage door width per car and height, stair width, railing
heights, and fixed-size window defaults.
"""

from app.modules.building.issues import Issue, pointer
from app.modules.building.types import (
    DoorTypeParams,
    RailingTypeParams,
    StairTypeParams,
    TypeSet,
    WindowTypeParams,
)
from app.modules.rules.profile import BuildingRulesProfile

TOLERANCE = 1e-4


def check_type_set(type_set: TypeSet, profile: BuildingRulesProfile) -> list[Issue]:
    issues: list[Issue] = []

    def need(role: str, field: str, value: float | None, minimum: float, rule: str) -> None:
        if value is not None and value + TOLERANCE < minimum:
            issues.append(
                Issue(
                    severity="error",
                    code="TYPE_RULE_VIOLATION",
                    path=pointer("roles", role, field),
                    message=(
                        f"{role}: type {type_set.roles[role]} has {field} {value} m, "
                        f"the rules profile requires at least {minimum} m"
                    ),
                    suggestion="Choose or approve a type that meets the rules profile.",
                    rule_ref=profile.rule_ref(rule),
                )
            )

    doors = profile.doors
    door_rules = {
        "door.entrance": (doors.entrance, "doors.entrance"),
        "door.interior": (doors.interior, "doors.interior"),
        "door.wet_room": (doors.bathroom, "doors.bathroom"),
    }
    for role in sorted(type_set.roles):
        t = type_set.type_for(role)
        if t is None:
            continue
        p = t.params
        if isinstance(p, DoorTypeParams):
            if role in door_rules:
                rule, path = door_rules[role]
                need(
                    role, "default_width", p.default_width, rule.min_width_m, f"{path}.min_width_m"
                )
                need(role, "height", p.height, rule.min_height_m, f"{path}.min_height_m")
            elif role == "door.garage":
                need(
                    role,
                    "width_per_car",
                    p.width_per_car,
                    doors.garage.min_width_per_car_m,
                    "doors.garage.min_width_per_car_m",
                )
                need(
                    role, "height", p.height, doors.garage.min_height_m, "doors.garage.min_height_m"
                )
        elif isinstance(p, StairTypeParams):
            need(role, "width", p.width, profile.stairs.min_width_m, "stairs.min_width_m")
        elif isinstance(p, RailingTypeParams):
            if role == "railing.balcony":
                minimum, rule_path = profile.railings.balcony_min_height_m, "balcony_min_height_m"
            else:
                minimum, rule_path = profile.railings.min_height_m, "min_height_m"
            need(role, "height", p.height, minimum, f"railings.{rule_path}")
        elif isinstance(p, WindowTypeParams) and p.default_width is not None:
            w = profile.windows
            need(role, "default_width", p.default_width, w.min_width_m, "windows.min_width_m")
            need(role, "default_height", p.default_height, w.min_height_m, "windows.min_height_m")
    return issues
