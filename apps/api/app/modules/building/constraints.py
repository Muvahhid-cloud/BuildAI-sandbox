"""Catalog of the geometric constraints checked by building/geometry_checks.py (Phase 3.5 K2.5).

A geometric constraint is a mathematical or structural-consistency property of the model
itself — an opening lies inside its host wall, a flight passes through a slab opening, a roof
bears on the walls that support it. Constraints are neither architectural knowledge
(catalog/, descriptive and source-attributed) nor rules (rules/ profiles, the only place for
enforceable minimums and maximums): nothing here is a dimensional requirement, and no value in
this module comes from a knowledge pack.

Every finding carries its constraint id (`Issue.constraint`); `code` is the finding code the UI
and the layout engine react to. Several constraints may share a code when they are one kind of
problem (e.g. an opening beyond either end of its wall, or below its base). docs/building-model.md
§4.1 lists every constraint (a test keeps the two in sync).
"""

from dataclasses import dataclass

from app.modules.building.issues import Severity


@dataclass(frozen=True)
class GeometryConstraint:
    id: str
    code: str
    severity: Severity
    statement: str  # what must hold (documentation; UI fallback text)


_ALL = [
    # --- hosting and openings ---
    GeometryConstraint(
        "host.exists",
        "HOST_NOT_FOUND",
        "error",
        "A door or window has a hosted_by relationship to an element of the model.",
    ),
    GeometryConstraint(
        "host.unique",
        "HOST_AMBIGUOUS",
        "error",
        "A door or window has exactly one host.",
    ),
    GeometryConstraint(
        "host.is_wall",
        "HOST_INCOMPATIBLE",
        "error",
        "The host of a door or window is a wall.",
    ),
    GeometryConstraint(
        "host.same_level",
        "OPENING_LEVEL",
        "error",
        "An opening is on the level of its host wall.",
    ),
    GeometryConstraint(
        "host.local_position",
        "INVALID_HOST_POSITION",
        "error",
        "An opening is placed in host-wall coordinates: position.y = 0 and no rotation; a door "
        "stands on the wall base (position.z = 0).",
    ),
    GeometryConstraint(
        "opening.within_length",
        "OPENING_OUTSIDE_WALL",
        "error",
        "0 <= offset and offset + width <= host wall length.",
    ),
    GeometryConstraint(
        "opening.above_base",
        "OPENING_OUTSIDE_WALL",
        "error",
        "The sill is not below the base of the host wall.",
    ),
    GeometryConstraint(
        "opening.within_height",
        "OPENING_TOO_TALL",
        "error",
        "sill + height <= host wall height.",
    ),
    GeometryConstraint(
        "opening.clear_of_junctions",
        "OPENING_IN_WALL_JUNCTION",
        "error",
        "An opening does not reach into the body of another wall that joins or crosses its "
        "host (L-corner, T-junction or crossing).",
    ),
    GeometryConstraint(
        "opening.within_thickness",
        "OPENING_THICKER_THAN_WALL",
        "error",
        "A door leaf is not thicker than its host wall.",
    ),
    GeometryConstraint(
        "opening.no_overlap",
        "OPENINGS_OVERLAP",
        "error",
        "Openings in the same wall do not overlap along the wall (touching is allowed).",
    ),
    # --- walls ---
    GeometryConstraint(
        "wall.within_level_height",
        "WALL_TOO_TALL",
        "error",
        "A wall is not taller than its level's floor-to-floor height.",
    ),
    GeometryConstraint(
        "wall.orientation",
        "INVALID_WALL_GEOMETRY",
        "error",
        "A wall is vertical (no tilt) and axis-aligned (v1 models are rectilinear).",
    ),
    GeometryConstraint(
        "wall.no_overlap",
        "WALLS_OVERLAP",
        "error",
        "Walls on the same level and coordination axis do not overlap along it.",
    ),
    GeometryConstraint(
        "wall.connected",
        "WALL_UNCONNECTED",
        "error",
        "Each end of an exterior wall meets another wall (the envelope is closed).",
    ),
    GeometryConstraint(
        "wall.on_slab",
        "WALL_NOT_ON_SLAB",
        "error",
        "A wall stands on the slabs of its level (not over a slab opening or beyond the slab).",
    ),
    # --- rooms and connectivity ---
    GeometryConstraint(
        "room.enclosed",
        "INVALID_ROOM_BOUNDARY",
        "error",
        "Every edge of an indoor room runs along a wall, along another room (an open "
        "boundary) or along a slab opening (a stair arrival).",
    ),
    GeometryConstraint(
        "room.not_crossed",
        "ROOM_CROSSED_BY_WALL",
        "error",
        "No wall axis runs through the inside of a room.",
    ),
    GeometryConstraint(
        "room.attached",
        "ROOM_DETACHED",
        "warning",
        "An outdoor room (balcony, terrace) touches the building: a wall or an indoor room.",
    ),
    GeometryConstraint(
        "door.opens_to_rooms",
        "DOOR_TO_NOWHERE",
        "error",
        "A door has a room on at least one side; a door in an interior wall on both sides.",
    ),
    GeometryConstraint(
        "relationship.kinds",
        "RELATIONSHIP_INVALID",
        "error",
        "A relationship joins the element types its kind allows (docs/building-model.md §3.4).",
    ),
    GeometryConstraint(
        "relationship.geometry",
        "RELATIONSHIP_INCONSISTENT",
        "error",
        "A bounds, adjacent_to, connects or located_in relationship is true of the geometry "
        "(same level; the wall runs along the room, the rooms share an edge, the door opens "
        "into the room, the element lies in the room).",
    ),
    # --- levels and stairs ---
    GeometryConstraint(
        "level.stacking",
        "LEVEL_ELEVATION_MISMATCH",
        "error",
        "Level 0 is at elevation 0 and each level starts where the one below ends "
        "(elevation + floor-to-floor height).",
    ),
    GeometryConstraint(
        "stair.orientation",
        "STAIR_GEOMETRY_INVALID",
        "error",
        "A flight is untilted and axis-aligned.",
    ),
    GeometryConstraint(
        "stair.in_rooms",
        "STAIR_OUTSIDE_ROOMS",
        "error",
        "A flight lies within the rooms of its starting level.",
    ),
    GeometryConstraint(
        "stair.clear_of_walls",
        "STAIR_INTERSECTS_WALL",
        "error",
        "A flight does not intersect the walls of its starting level.",
    ),
    GeometryConstraint(
        "stair.access",
        "STAIR_ACCESS_INVALID",
        "error",
        "A flight starts from a room on its starting level and arrives in a room on its "
        "arrival level.",
    ),
    GeometryConstraint(
        "stair.slab_opening",
        "STAIR_SLAB_CONFLICT",
        "error",
        "Where a flight rises above the underside of the arrival level's slab, it passes "
        "through a slab opening.",
    ),
    # --- slabs and roofs ---
    GeometryConstraint(
        "slab.no_overlap",
        "SLABS_OVERLAP",
        "error",
        "Slabs of the same level do not overlap.",
    ),
    GeometryConstraint(
        "support.slab",
        "SLAB_RELATIONSHIP_INVALID",
        "error",
        "A wall that supports a slab lies under the slab and its top meets the slab's underside.",
    ),
    GeometryConstraint(
        "roof.shape",
        "ROOF_GEOMETRY_INVALID",
        "error",
        "A flat roof has no pitch; a pitched roof has a pitch and no parapet; roofs are untilted.",
    ),
    GeometryConstraint(
        "roof.covers_supports",
        "ROOF_FOOTPRINT_INVALID",
        "error",
        "A roof's outline covers the walls that support it.",
    ),
    GeometryConstraint(
        "roof.overhang",
        "ROOF_OVERHANG_MISMATCH",
        "error",
        "A roof's outline extends exactly its declared overhang beyond the walls that "
        "support it, on every side.",
    ),
    GeometryConstraint(
        "support.roof",
        "ROOF_SUPPORT_INVALID",
        "error",
        "A roof bears on its supporting walls: its underside meets their tops and does not "
        "cut into them.",
    ),
    GeometryConstraint(
        "roof.supported",
        "ROOF_UNSUPPORTED",
        "warning",
        "At least one wall supports each roof.",
    ),
    # --- component types ---
    GeometryConstraint(
        "type.fits_host",
        "TYPE_GEOMETRY_MISMATCH",
        "error",
        "The fixed dimensions of an opening's type fit its host wall (height, thickness).",
    ),
    GeometryConstraint(
        "type.fits_storey",
        "TYPE_GEOMETRY_MISMATCH",
        "error",
        "The fixed dimensions of the types in a type set fit the walls the layout engine "
        "builds with it (checked before generation).",
    ),
]

CONSTRAINTS: dict[str, GeometryConstraint] = {c.id: c for c in _ALL}
