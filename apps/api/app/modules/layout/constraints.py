"""Local geometric constraints of the layout engine (Phase 3.5 K2.5, docs/3d-engine.md §16.7).

The engine prefers generating valid geometry to discovering invalid geometry afterwards:

    spec + effective config -> opening_fit_issues   (before the search: fixed door sizes vs the
                                                     storey's walls; user-fixable, INFEASIBLE)
    skeleton                -> flights_fit_lanes    (in the seeded search: impossible skeletons
                                                     are skipped, the search continues)
    opening placement       -> WallPlan.place       (building.hosting: inside the wall segment,
                                                     clear of other openings and wall junctions)
    built candidate         -> validate_model       (every model invariant incl. the geometric
                                                     checks; the first valid candidate wins)

Every check here is a geometric necessity for the plan scheme of the engine; enforceable
minimums still come only from the rules profile.
"""

from app.modules.building.constraints import CONSTRAINTS
from app.modules.building.issues import Issue, Measure, pointer
from app.modules.building.specification import BuildingSpecification
from app.modules.building.types import TypeSet
from app.modules.layout.build import door_sizes
from app.modules.layout.config import LayoutConfig
from app.modules.layout.plan import EPS, Skeleton, StairDesign, lane_faces, rnd
from app.modules.layout.program import WET, Program
from app.modules.rules.profile import BuildingRulesProfile

DOOR_NAMES = {
    "door.entrance": "entrance door",
    "door.interior": "interior doors",
    "door.wet_room": "wet-room doors",
    "door.sliding": "sliding balcony/terrace doors",
    "door.garage": "garage door",
}


def flights_fit_lanes(sk: Skeleton, stair: StairDesign, config: LayoutConfig) -> bool:
    """Every flight, centred between the faces of the walls that bound its lane, keeps the stair
    clearance on both sides. On the facade a lane is bounded by the exterior wall, thicker than
    the interior lane walls the lane width is designed for; skeletons() widens such lanes, and a
    skeleton whose flights still do not fit is not buildable."""
    for flight in range(sk.lanes):
        west, east, _ = lane_faces(
            sk, flight, config.exterior_wall_thickness, config.interior_wall_thickness
        )
        if (east - west - stair.width) / 2 < config.stair_clearance - EPS:
            return False
    return True


def opening_fit_issues(
    spec: BuildingSpecification,
    program: Program,
    profile: BuildingRulesProfile,
    config: LayoutConfig,
    type_set: TypeSet | None,
) -> list[Issue]:
    """Doors the building needs whose fixed size cannot fit its walls: taller than the walls of
    the requested storey height, or thicker than the walls that host them. Door heights and
    thicknesses are fixed (by the component type, or by the engine defaults the generic types
    mirror), so the engine cannot shrink them; the user can raise the storey height."""
    wall_height = rnd(spec.targets.floor_to_floor_height_m - config.floor_slab_thickness)
    sizes = door_sizes(config, profile)
    hosts = {
        "door.entrance": ["exterior"],
        "door.interior": ["interior", "exterior"],  # incl. the garage-to-house door
        "door.wet_room": ["interior"],
        "door.sliding": ["exterior"],
        "door.garage": ["exterior"],
    }
    thickness = {
        "exterior": config.exterior_wall_thickness,
        "interior": config.interior_wall_thickness,
    }
    required = ["door.entrance", "door.interior"]
    if any(r.type in WET for r in program.rooms):
        required.append("door.wet_room")
    if spec.features.balconies or spec.features.terrace is not None:
        required.append("door.sliding")
    if spec.features.garage is not None:
        required.append("door.garage")
    c = CONSTRAINTS["type.fits_storey"]
    issues: list[Issue] = []
    for role in required:
        t = type_set.type_for(role) if type_set is not None else None
        source = f"type {t.id}" if t is not None else "engine default"
        height = sizes[role][1]
        if height > wall_height + EPS:
            slab = config.floor_slab_thickness
            issues.append(
                Issue(
                    severity=c.severity,
                    code=c.code,
                    path="/targets/floor_to_floor_height_m",
                    message=(
                        f"The {DOOR_NAMES[role]} ({height:.2f} m high, {source}) do not fit the "
                        f"{wall_height:.2f} m walls of a {spec.targets.floor_to_floor_height_m} m "
                        "storey"
                    ),
                    suggestion=(
                        f"Raise the floor-to-floor height to at least {rnd(height + slab)} m."
                    ),
                    constraint=c.id,
                    measure=Measure(
                        quantity="door_height", actual=height, limit=wall_height, unit="m"
                    ),
                )
            )
        for kind in hosts[role]:
            if config.door_thickness > thickness[kind] + EPS:
                issues.append(
                    Issue(
                        severity=c.severity,
                        code=c.code,
                        path=pointer("roles", role),
                        message=(
                            f"The {DOOR_NAMES[role]} ({config.door_thickness:.3f} m thick, "
                            f"{source}) are thicker than the {kind} walls "
                            f"({thickness[kind]:.3f} m)"
                        ),
                        constraint=c.id,
                        measure=Measure(
                            quantity="door_thickness",
                            actual=config.door_thickness,
                            limit=thickness[kind],
                            unit="m",
                        ),
                    )
                )
    return issues
