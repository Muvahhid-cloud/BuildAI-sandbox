"""Tier-2 (semantic) validation of a BuildingSpecification against a BuildingRulesProfile.

Pydantic already enforced types, enums and ranges (tier 1). These checks look at the spec as a
whole: references between rooms, storey indices, the room program against the rules' minimum
areas and the requested floor area. Errors block generation; warnings are shown to the user.
Feasibility of an actual plan (tier 3) is decided by the layout engine.
"""

from app.modules.building.design import check_intent
from app.modules.building.intent import check_requirements
from app.modules.building.issues import Issue, Severity, pointer
from app.modules.building.specification import (
    BuildingSpecification,
    RoomFeature,
    SpecRoomType,
)
from app.modules.rules.profile import BuildingRulesProfile

# Share of the gross floor area that rooms may take; the rest is walls and circulation.
MAX_ROOM_SHARE_OF_GFA = 0.85
OPEN_PLAN_TYPES = frozenset(
    {
        SpecRoomType.LIVING,
        SpecRoomType.DINING,
        SpecRoomType.KITCHEN,
        SpecRoomType.OPEN_KITCHEN_LIVING,
        SpecRoomType.STUDY,
    }
)
SERVICE_TYPES = frozenset(
    {
        SpecRoomType.STORAGE,
        SpecRoomType.WC,
        SpecRoomType.PLANT_ROOM,
        SpecRoomType.LAUNDRY,
        SpecRoomType.UTILITY,
        SpecRoomType.BATHROOM,
    }
)


class _Checks:
    def __init__(self, spec: BuildingSpecification, profile: BuildingRulesProfile) -> None:
        self.spec = spec
        self.profile = profile
        self.issues: list[Issue] = []
        self.keys = {r.key: r for r in spec.rooms}

    def add(
        self,
        severity: Severity,
        code: str,
        path: str,
        message: str,
        *,
        suggestion: str | None = None,
        rule: str | None = None,
    ) -> None:
        self.issues.append(
            Issue(
                severity=severity,
                code=code,
                path=path,
                message=message,
                suggestion=suggestion,
                rule_ref=self.profile.rule_ref(rule) if rule else None,
            )
        )

    def rooms(self) -> None:
        storeys = self.spec.targets.storeys
        for i, room in enumerate(self.spec.rooms):
            rule = self.profile.room(room.type)
            ref = self.profile.room_rule_ref(room.type).split(":", 1)[1]
            if room.level is not None and room.level >= storeys:
                self.add(
                    "error",
                    "SPEC_LEVEL_OUT_OF_RANGE",
                    pointer("rooms", i, "level"),
                    f"{room.key}: level {room.level} does not exist in a {storeys}-storey house",
                    suggestion=f"Use a level between 0 and {storeys - 1}, or add storeys.",
                )
            if room.target_area_m2 is not None and room.target_area_m2 < rule.min_area_m2:
                self.add(
                    "error",
                    "SPEC_AREA_BELOW_MINIMUM",
                    pointer("rooms", i, "target_area_m2"),
                    f"{room.key}: target area {room.target_area_m2} m² is below the "
                    f"{rule.min_area_m2} m² minimum for a {room.type}",
                    suggestion=f"Use at least {rule.min_area_m2} m².",
                    rule=f"{ref}.min_area_m2",
                )
            if room.max_area_m2 is not None and room.max_area_m2 < rule.min_area_m2:
                self.add(
                    "error",
                    "SPEC_AREA_BELOW_MINIMUM",
                    pointer("rooms", i, "max_area_m2"),
                    f"{room.key}: maximum area {room.max_area_m2} m² is below the "
                    f"{rule.min_area_m2} m² minimum for a {room.type}",
                    suggestion=f"Allow at least {rule.min_area_m2} m².",
                    rule=f"{ref}.min_area_m2",
                )
            if (
                room.min_area_m2 is not None
                and room.target_area_m2 is not None
                and room.min_area_m2 > room.target_area_m2
            ):
                self.add(
                    "error",
                    "SPEC_MIN_ABOVE_TARGET",
                    pointer("rooms", i, "min_area_m2"),
                    f"{room.key}: minimum area is larger than the target area",
                )
            for field in ("adjacent_to", "open_to"):
                for j, other in enumerate(getattr(room, field)):
                    if other == room.key or other not in self.keys:
                        self.add(
                            "error",
                            "SPEC_UNKNOWN_ROOM_KEY",
                            pointer("rooms", i, field, j),
                            f"{room.key}: {field} refers to unknown room {other!r}",
                        )
            for j, other in enumerate(room.open_to):
                target = self.keys.get(other)
                if target and not {room.type, target.type} <= OPEN_PLAN_TYPES:
                    self.add(
                        "error",
                        "SPEC_OPEN_PLAN_TYPES",
                        pointer("rooms", i, "open_to", j),
                        f"{room.key}: open plan is only supported between living, dining, "
                        "kitchen and study spaces",
                    )
            if room.features and room.type != SpecRoomType.BEDROOM:
                self.add(
                    "error",
                    "SPEC_FEATURE_NOT_ALLOWED",
                    pointer("rooms", i, "features"),
                    f"{room.key}: en-suites and walk-in closets can only belong to bedrooms",
                )
            if len(set(room.features)) != len(room.features):
                self.add(
                    "error",
                    "SPEC_DUPLICATE_FEATURE",
                    pointer("rooms", i, "features"),
                    f"{room.key}: duplicate room feature",
                )

    def program(self) -> None:
        types = {r.type for r in self.spec.rooms}
        has_en_suite = any(RoomFeature.EN_SUITE in r.features for r in self.spec.rooms)
        if SpecRoomType.BATHROOM not in types and not has_en_suite:
            self.add(
                "error",
                "SPEC_NO_BATHROOM",
                "/rooms",
                "A house needs at least one bathroom",
                suggestion="Add a room of type bathroom.",
            )
        if not types & {SpecRoomType.KITCHEN, SpecRoomType.OPEN_KITCHEN_LIVING}:
            self.add("warning", "SPEC_NO_KITCHEN", "/rooms", "The program has no kitchen")
        if SpecRoomType.BEDROOM not in types:
            self.add("warning", "SPEC_NO_BEDROOM", "/rooms", "The program has no bedroom")

        gfa = self.spec.targets.gross_floor_area_m2
        if gfa is None:
            return
        minimum = sum(
            max(r.target_area_m2 or 0, r.min_area_m2 or 0, self.profile.room(r.type).min_area_m2)
            * r.count
            for r in self.spec.rooms
        )
        if minimum > MAX_ROOM_SHARE_OF_GFA * gfa:
            self.add(
                "error",
                "SPEC_PROGRAM_EXCEEDS_AREA",
                "/targets/gross_floor_area_m2",
                f"The rooms need at least {minimum:.0f} m², but only "
                f"{MAX_ROOM_SHARE_OF_GFA * gfa:.0f} m² of the {gfa:.0f} m² gross floor area can "
                "be rooms (the rest is walls and circulation)",
                suggestion=f"Increase the area to about {minimum / MAX_ROOM_SHARE_OF_GFA:.0f} m² "
                "or reduce the number or size of rooms.",
                rule="rooms",
            )

    def structure(self, floor_structure_m: float) -> None:
        clear = self.spec.targets.floor_to_floor_height_m - floor_structure_m
        ceiling = self.profile.ceiling
        if clear < ceiling.min_clear_height_m:
            self.add(
                "error",
                "SPEC_CEILING_TOO_LOW",
                "/targets/floor_to_floor_height_m",
                f"A {self.spec.targets.floor_to_floor_height_m} m floor-to-floor height leaves "
                f"{clear:.2f} m clear height; habitable rooms need {ceiling.min_clear_height_m} m",
                suggestion=f"Use at least {ceiling.min_clear_height_m + floor_structure_m:.2f} m.",
                rule="ceiling.min_clear_height_m",
            )
        if self.spec.targets.storeys > 1:
            stairs = self.profile.stairs
            risers_needed = self.spec.targets.floor_to_floor_height_m / stairs.riser_m.max
            if risers_needed > stairs.max_risers_per_flight + 1e-9:
                self.add(
                    "error",
                    "SPEC_STAIR_TOO_HIGH",
                    "/targets/floor_to_floor_height_m",
                    "The floor-to-floor height needs more risers than one straight flight allows",
                    suggestion=f"Use at most "
                    f"{stairs.max_risers_per_flight * stairs.riser_m.max:.2f} m.",
                    rule="stairs.max_risers_per_flight",
                )

    def features(self) -> None:
        storeys = self.spec.targets.storeys
        for i, balcony in enumerate(self.spec.features.balconies):
            if balcony.level >= storeys:
                self.add(
                    "error",
                    "SPEC_BALCONY_LEVEL",
                    pointer("features", "balconies", i, "level"),
                    f"Balcony on level {balcony.level} needs an upper floor that does not exist",
                    suggestion="Balconies need at least two storeys.",
                )
            self._attached(balcony.attached_to, pointer("features", "balconies", i), balcony.level)
        terrace = self.spec.features.terrace
        if terrace is not None:
            self._attached(terrace.attached_to, "/features/terrace", 0)

    def _attached(self, key: str | None, path: str, level: int) -> None:
        if key is None:
            return
        room = self.keys.get(key)
        if room is None:
            self.add(
                "error",
                "SPEC_UNKNOWN_ROOM_KEY",
                path + "/attached_to",
                f"attached_to refers to unknown room {key!r}",
            )
        elif room.level is not None and room.level != level:
            self.add(
                "error",
                "SPEC_ATTACHED_LEVEL",
                path + "/attached_to",
                f"{key} is on level {room.level}, not level {level}",
            )
        elif room.type in SERVICE_TYPES:
            self.add(
                "warning",
                "SPEC_ATTACHED_SERVICE_ROOM",
                path + "/attached_to",
                f"{key} is a service room; the engine will attach the feature to a living "
                "space or bedroom instead",
            )

    def site(self, floor_area_per_storey: float | None) -> None:
        site = self.spec.site
        if site is None or site.plot_width_m is None or site.plot_depth_m is None:
            return
        width = site.plot_width_m - 2 * site.setback_side_m
        depth = site.plot_depth_m - site.setback_front_m - site.setback_rear_m
        if width <= 0 or depth <= 0:
            self.add(
                "error",
                "SPEC_NO_BUILDABLE_AREA",
                "/site",
                "The setbacks leave no buildable area on the plot",
            )
            return
        if floor_area_per_storey is not None and width * depth < floor_area_per_storey:
            self.add(
                "error",
                "SPEC_PLOT_TOO_SMALL",
                "/site",
                f"Each storey needs about {floor_area_per_storey:.0f} m², but the buildable "
                f"part of the plot is {width * depth:.0f} m²",
                suggestion="Add a storey, reduce the area or reduce the setbacks.",
            )


def check_spec(
    spec: BuildingSpecification, profile: BuildingRulesProfile, *, floor_structure_m: float
) -> list[Issue]:
    """Semantic issues of `spec` under `profile`. `floor_structure_m` is the floor build-up
    (slab) thickness the layout engine will use, needed to derive clear heights."""
    checks = _Checks(spec, profile)
    checks.rooms()
    checks.program()
    checks.structure(floor_structure_m)
    checks.features()
    gfa = spec.targets.gross_floor_area_m2
    checks.site(gfa / spec.targets.storeys if gfa is not None else None)
    # Design intent that is invalid on its own (K3). The selected design system is checked
    # against the catalog by the caller (building.design.check_design; rules has no catalog).
    # Requirement traces, separation requests and area ranges (spec 1.2.0).
    return checks.issues + check_intent(spec) + check_requirements(spec)
