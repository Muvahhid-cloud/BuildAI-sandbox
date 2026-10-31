"""Keep geometric relationships true after an operation changes walls or rooms.

`bounds` (wall -> room) and `adjacent_to` (room -> room) are facts of the geometry
(geometry_checks `relationship.geometry`): a wall bounds a room when its axis runs along the
room's boundary, two rooms are adjacent when their boundaries share a length. The layout engine
writes exactly these sets (checked on every fixture), so after an edit they are recomputed for
the level from the new geometry. Relationships that still hold keep their order; new ones are
appended in id order, so replaying the same operations gives the same model.
"""

import uuid
from collections.abc import Sequence

from app.modules.building.elements import Element, Relationship, Room, Wall
from app.modules.building.enums import RelationshipKind
from app.modules.building.geometry import (
    Point,
    polygon_edges,
    segment_overlap_length,
    shared_boundary_length,
    to_absolute,
    wall_axis,
)
from app.modules.building.primitives import EPS


def room_ring(room: Room) -> list[Point]:
    return to_absolute(room.properties.boundary, room.position, room.rotation)


def _with_kind(
    relationships: Sequence[Relationship], kind: RelationshipKind, targets: set[uuid.UUID]
) -> list[Relationship]:
    kept = [r for r in relationships if r.kind != kind or r.target_id in targets]
    present = {r.target_id for r in kept if r.kind == kind}
    added = [Relationship(kind=kind, target_id=t) for t in sorted(targets - present, key=str)]
    return kept + added


def refresh_level_relationships(
    elements: list[Element], level_id: uuid.UUID | None
) -> list[Element]:
    """Recompute `bounds` and `adjacent_to` for the walls and rooms of one level."""
    rooms = [e for e in elements if isinstance(e, Room) and e.level_id == level_id]
    rings = {r.id: room_ring(r) for r in rooms}
    out: list[Element] = []
    for el in elements:
        if isinstance(el, Wall) and el.level_id == level_id:
            axis = wall_axis(el)
            bounded = {
                r.id
                for r in rooms
                if max(
                    (segment_overlap_length(axis, e) for e in polygon_edges(rings[r.id])),
                    default=0.0,
                )
                > EPS
            }
            rels = _with_kind(el.relationships, RelationshipKind.BOUNDS, bounded)
            out.append(
                el if rels == el.relationships else el.model_copy(update={"relationships": rels})
            )
        elif isinstance(el, Room) and el.level_id == level_id:
            near = {
                o.id
                for o in rooms
                if o.id != el.id and shared_boundary_length(rings[el.id], rings[o.id]) > EPS
            }
            rels = _with_kind(el.relationships, RelationshipKind.ADJACENT_TO, near)
            out.append(
                el if rels == el.relationships else el.model_copy(update={"relationships": rels})
            )
        else:
            out.append(el)
    return out
