"""Door and window operations (docs/building-model.md §5.3, §5.4): `move_opening`, `add_opening`
and `remove_element` (doors and windows only; Phase 3.6 D2.3), and `resize_opening` (D2.4).

Openings are host-relative (hosting.py): (host wall, offset of the start edge, width, sill,
height). The walls are built around their hosted openings (panel decomposition), so placing,
moving or removing an opening changes the wall in the plan and in 3D without touching the wall
element itself; removing one closes the wall over it.

Checked here, with the reason: the element and the wall exist, the wall is on the opening's
level, the opening kind suits the wall (windows and entrance / sliding / garage doors only in
exterior walls), it stays inside the wall, it does not overlap another opening of the wall and
does not reach into the body of a joining wall (the same interval arithmetic as the validator,
hosting.py). Everything that needs the rules profile or the whole plan — minimum sizes, the
clearance from corners and other openings, reachability of rooms, daylight, MUST requirements —
is judged by the editing service on the result, never here.
"""

import uuid

from app.modules.building.elements import Door, Element, Relationship, Room, Wall, Window
from app.modules.building.enums import (
    DoorKind,
    DoorSwing,
    Origin,
    RelationshipKind,
    WallKind,
    WindowKind,
)
from app.modules.building.geometry import (
    Point,
    polygon_edges,
    segment_overlap_length,
    wall_axis,
    wall_frame,
)
from app.modules.building.hosting import Interval, junction_zones, overlap
from app.modules.building.model import BuildingModel
from app.modules.building.operations.relationships import room_ring
from app.modules.building.operations.schemas import (
    AddOpening,
    MoveOpening,
    OperationRejected,
    RemoveElement,
    ResizeOpening,
)
from app.modules.building.primitives import EPS, Rotation, Vec3
from app.modules.building.type_validation import fixed_param_differences

Opening = Door | Window

#: Door kinds that open to the outside: only exterior walls can host them (as windows).
EXTERIOR_DOORS = frozenset({DoorKind.ENTRANCE, DoorKind.SLIDING, DoorKind.GARAGE})
#: Leaf thickness of a new door when the model has no door to take it from (m). A build-up
#: default like LayoutConfig.door_thickness, not a design rule; never thicker than the wall.
FALLBACK_DOOR_THICKNESS = 0.06
FALLBACK_MATERIALS = {"door": "wood", "exterior_door": "wood_dark", "glazed": "glass"}
FRAME_MATERIAL = "window_frame"


def _r(v: float) -> float:
    return round(v, 3) + 0.0


def host_of(model: BuildingModel, opening: Opening) -> Wall | None:
    ids = [r.target_id for r in opening.relationships if r.kind == RelationshipKind.HOSTED_BY]
    host = next((e for e in model.elements if ids and e.id == ids[0]), None)
    return host if isinstance(host, Wall) else None


def wall_zones(model: BuildingModel, wall: Wall) -> list[Interval]:
    """Stretches of the wall's axis taken by the bodies of the walls that join or cross it."""
    frame = wall_frame(wall)
    return junction_zones(
        wall_axis(wall),
        (frame.v0, frame.v1),
        [
            (wall_axis(w), w.dimensions.thickness)
            for w in model.elements
            if isinstance(w, Wall) and w.level_id == wall.level_id and w.id != wall.id
        ],
    )


def hosted(model: BuildingModel, wall: Wall) -> list[Opening]:
    out: list[Opening] = []
    for e in model.elements:
        if isinstance(e, Door | Window) and any(
            r.kind == RelationshipKind.HOSTED_BY and r.target_id == wall.id for r in e.relationships
        ):
            out.append(e)
    return out


def _label(kind: str, door_kind: DoorKind | None, window_kind: WindowKind | None) -> str:
    if kind == "window":
        return f"a {window_kind.value} window" if window_kind else "a window"
    if door_kind == DoorKind.ENTRANCE:
        return "an entrance door"
    return f"a {door_kind.value} door" if door_kind else "a door"


def _wall(model: BuildingModel, wall_id: uuid.UUID) -> Wall:
    el = next((e for e in model.elements if e.id == wall_id), None)
    if el is None:
        raise OperationRejected("HOST_NOT_FOUND", "The wall for the opening is not in this design.")
    if not isinstance(el, Wall):
        raise OperationRejected(
            "HOST_INCOMPATIBLE",
            f"{el.name} is a {el.type}; doors and windows go in walls.",
            element_id=el.id,
        )
    return el


def _check_compatible(
    wall: Wall, kind: str, door_kind: DoorKind | None, window_kind: WindowKind | None
) -> None:
    exterior_only = kind == "window" or door_kind in EXTERIOR_DOORS
    if exterior_only and wall.properties.wall_kind != WallKind.EXTERIOR:
        what = _label(kind, door_kind, window_kind)
        raise OperationRejected(
            "OPENING_WALL_INCOMPATIBLE",
            f"{wall.name} is an interior wall; {what} goes in an exterior wall.",
            element_id=wall.id,
        )


def _check_fits(
    model: BuildingModel,
    wall: Wall,
    name: str,
    span: Interval,
    rise: Interval,
    own_id: uuid.UUID | None,
) -> None:
    """Inside the wall, not over another opening, clear of the joining walls."""
    length = wall.dimensions.length
    if span[0] < -EPS or span[1] > length + EPS:
        raise OperationRejected(
            "OPENING_OUTSIDE_WALL",
            f"{name} would reach past the end of {wall.name} (the wall is {length:.2f} m long, "
            f"the opening would run from {span[0]:.2f} to {span[1]:.2f} m).",
            element_id=own_id,
            related_ids=[wall.id],
        )
    if rise[1] > wall.dimensions.height + EPS:
        raise OperationRejected(
            "OPENING_TOO_TALL",
            f"{name} would reach {rise[1]:.2f} m, above the top of {wall.name} "
            f"({wall.dimensions.height:.2f} m).",
            element_id=own_id,
            related_ids=[wall.id],
        )
    for other in sorted(hosted(model, wall), key=lambda o: o.position.x):
        if other.id == own_id:
            continue
        o_span = (other.position.x, other.position.x + other.dimensions.width)
        if overlap(span, o_span) > EPS:
            raise OperationRejected(
                "OPENINGS_OVERLAP",
                f"{name} would overlap {other.name} in {wall.name}.",
                element_id=own_id,
                related_ids=[other.id, wall.id],
            )
    for lo, hi in wall_zones(model, wall):
        if overlap(span, (lo, hi)) > EPS:
            raise OperationRejected(
                "OPENING_IN_WALL_JUNCTION",
                f"{name} would cut into the wall that joins {wall.name} at "
                f"{lo:.2f}-{hi:.2f} m along it.",
                element_id=own_id,
                related_ids=[wall.id],
            )


def door_rooms(model: BuildingModel, wall: Wall, span: Interval) -> list[uuid.UUID]:
    """Rooms a door at `span` of `wall` opens into: those whose boundary runs along the door
    (room boundaries lie on wall axes), ordered by semantic key like the layout engine."""
    frame = wall_frame(wall)
    seg: tuple[Point, Point] = (frame.at(span[0]), frame.at(span[1]))
    rooms = [
        e
        for e in model.elements
        if isinstance(e, Room)
        and e.level_id == wall.level_id
        and max(
            (segment_overlap_length(seg, edge) for edge in polygon_edges(room_ring(e))),
            default=0.0,
        )
        > EPS
    ]
    return [r.id for r in sorted(rooms, key=lambda r: r.semantic_key)]


def _relationships(
    opening: Opening, model: BuildingModel, wall: Wall, span: Interval
) -> list[Relationship]:
    """hosted_by the wall and, for a door, `connects` the rooms it opens into. Relationships
    that still hold keep their place; new ones are appended (as refresh_level_relationships)."""
    want: list[Relationship] = [Relationship(kind=RelationshipKind.HOSTED_BY, target_id=wall.id)]
    if isinstance(opening, Door):
        want += [
            Relationship(kind=RelationshipKind.CONNECTS, target_id=room_id)
            for room_id in door_rooms(model, wall, span)
        ]
    managed = (RelationshipKind.HOSTED_BY, RelationshipKind.CONNECTS)
    kept = [r for r in opening.relationships if r.kind not in managed or r in want]
    return kept + [r for r in want if r not in kept]


def _replace(model: BuildingModel, el: Element) -> BuildingModel:
    return model.model_copy(
        update={"elements": [el if e.id == el.id else e for e in model.elements]}
    )


def _opening(model: BuildingModel, opening_id: uuid.UUID) -> Opening:
    el = next((e for e in model.elements if e.id == opening_id), None)
    if not isinstance(el, Door | Window):
        raise OperationRejected("OPENING_NOT_FOUND", "The door or window is not in this design.")
    if el.locked:
        raise OperationRejected(
            "ELEMENT_LOCKED", f"{el.name} is locked and cannot be changed.", element_id=el.id
        )
    return el


def move_opening(model: BuildingModel, op: MoveOpening) -> BuildingModel:
    opening = _opening(model, op.opening_id)
    current = host_of(model, opening)
    wall = _wall(model, op.host_wall_id) if op.host_wall_id else current
    if wall is None:
        raise OperationRejected(
            "HOST_NOT_FOUND", f"{opening.name} has no host wall.", element_id=opening.id
        )
    if wall.level_id != opening.level_id:
        raise OperationRejected(
            "OPENING_LEVEL",
            f"{wall.name} is on another floor than {opening.name}.",
            element_id=opening.id,
            related_ids=[wall.id],
        )
    offset = _r(op.offset_m)
    if current is not None and wall.id == current.id:
        if abs(offset - opening.position.x) < 0.001:
            raise OperationRejected(
                "NO_CHANGE", f"{opening.name} would move by less than 1 mm.", element_id=opening.id
            )
    else:
        door_kind = opening.properties.door_kind if isinstance(opening, Door) else None
        window_kind = opening.properties.window_kind if isinstance(opening, Window) else None
        _check_compatible(wall, opening.type, door_kind, window_kind)
    span = (offset, offset + opening.dimensions.width)
    rise = (opening.position.z, opening.position.z + opening.dimensions.height)
    _check_fits(model, wall, opening.name, span, rise, opening.id)
    moved = opening.model_copy(
        update={
            "position": opening.position.model_copy(update={"x": offset}),
            "relationships": _relationships(opening, model, wall, span),
            "origin": Origin.USER,
        }
    )
    return _replace(model, moved)


def _template(model: BuildingModel, kind: str, sub: DoorKind | WindowKind) -> Opening | None:
    """The model's first opening of that kind (same sub-kind preferred): materials and leaf
    thickness of a new opening follow it."""
    same: list[Opening] = []
    any_: list[Opening] = []
    for e in model.elements:
        if kind == "door" and isinstance(e, Door):
            (same if e.properties.door_kind == sub else any_).append(e)
        elif kind == "window" and isinstance(e, Window):
            (same if e.properties.window_kind == sub else any_).append(e)
    found = same or any_
    return found[0] if found else None


def _new_key(model: BuildingModel, kind: str) -> tuple[str, int]:
    taken = {e.semantic_key for e in model.elements}
    n = 1
    while f"{kind}:edit:{n}" in taken:
        n += 1
    return f"{kind}:edit:{n}", n


def add_opening(model: BuildingModel, op: AddOpening) -> BuildingModel:
    wall = _wall(model, op.host_wall_id)
    door_kind = (op.door_kind or DoorKind.INTERIOR) if op.kind == "door" else None
    window_kind = (op.window_kind or WindowKind.CASEMENT) if op.kind == "window" else None
    _check_compatible(wall, op.kind, door_kind, window_kind)
    offset, width, height, sill = _r(op.offset_m), _r(op.width_m), _r(op.height_m), _r(op.sill_m)
    if op.kind == "door" and sill != 0:
        raise OperationRejected(
            "INVALID_HOST_POSITION", "A door stands on the floor: its sill must be 0."
        )
    key, n = _new_key(model, op.kind)
    name = f"New {op.kind} {n}"
    span, rise = (offset, offset + width), (sill, sill + height)
    _check_fits(model, wall, name, span, rise, None)
    new_id = uuid.uuid5(model.id, f"edit:{key}")
    common = {
        "id": new_id,
        "name": name,
        "level_id": wall.level_id,
        "position": Vec3(x=offset, y=0, z=sill),
        "rotation": Rotation(),
        "origin": Origin.USER,
        "semantic_key": key,
    }
    template = _template(model, op.kind, door_kind or window_kind)  # type: ignore[arg-type]
    el: Opening
    if door_kind is not None:
        tpl = template if isinstance(template, Door) else None
        glazed = door_kind == DoorKind.SLIDING
        fallback = (
            FALLBACK_MATERIALS["glazed"]
            if glazed
            else FALLBACK_MATERIALS["exterior_door" if door_kind in EXTERIOR_DOORS else "door"]
        )
        same_kind = tpl is not None and tpl.properties.door_kind == door_kind
        thickness = tpl.dimensions.thickness if tpl else FALLBACK_DOOR_THICKNESS
        swing = op.swing or (DoorSwing.SLIDING if glazed else DoorSwing.LEFT)
        el = Door.model_validate(
            {
                **common,
                "type": "door",
                "layer": tpl.layer if tpl else "architecture",
                "material_id": tpl.material_id if tpl and same_kind else fallback,
                "relationships": [],
                "dimensions": {
                    "width": width,
                    "height": height,
                    "thickness": min(thickness, wall.dimensions.thickness),
                },
                "properties": {
                    "door_kind": door_kind,
                    "swing": swing,
                    "frame_material_id": (
                        tpl.properties.frame_material_id if tpl else FRAME_MATERIAL
                    ),
                },
            }
        )
    else:
        tpl_w = template if isinstance(template, Window) else None
        pane = (
            tpl_w.dimensions.width / (tpl_w.properties.mullions + 1) if tpl_w is not None else None
        )
        mullions = max(0, min(12, round(width / pane) - 1)) if pane else 0
        el = Window.model_validate(
            {
                **common,
                "type": "window",
                "layer": tpl_w.layer if tpl_w else "architecture",
                "material_id": tpl_w.material_id if tpl_w else FALLBACK_MATERIALS["glazed"],
                "relationships": [],
                "dimensions": {"width": width, "height": height},
                "properties": {
                    "window_kind": window_kind,
                    "frame_material_id": (
                        tpl_w.properties.frame_material_id if tpl_w else FRAME_MATERIAL
                    ),
                    "mullions": mullions,
                },
            }
        )
    el = el.model_copy(update={"relationships": _relationships(el, model, wall, span)})
    # After the wall's last opening, so model order stays "walls, then their openings".
    on_wall = {wall.id} | {o.id for o in hosted(model, wall)}
    last = max(i for i, e in enumerate(model.elements) if e.id in on_wall)
    elements = [*model.elements[: last + 1], el, *model.elements[last + 1 :]]
    return model.model_copy(update={"elements": elements})


def remove_element(model: BuildingModel, op: RemoveElement) -> BuildingModel:
    el = next((e for e in model.elements if e.id == op.element_id), None)
    if el is None:
        raise OperationRejected("ELEMENT_NOT_FOUND", "The element to remove is not in this design.")
    if not isinstance(el, Door | Window):
        raise OperationRejected(
            "ELEMENT_NOT_REMOVABLE",
            f"{el.name} is a {el.type}; remove_element removes doors and windows "
            "(walls: remove_wall).",
            element_id=el.id,
        )
    if el.locked:
        raise OperationRejected(
            "ELEMENT_LOCKED", f"{el.name} is locked and cannot be removed.", element_id=el.id
        )
    elements = [
        e
        if not any(r.target_id == el.id for r in e.relationships)
        else e.model_copy(
            update={"relationships": [r for r in e.relationships if r.target_id != el.id]}
        )
        for e in model.elements
        if e.id != el.id
    ]
    return model.model_copy(update={"elements": elements})


def _mullions(window: Window, width: float) -> int:
    """Glazing bars of a resized window: the panes keep about their width."""
    pane = window.dimensions.width / (window.properties.mullions + 1)
    return max(0, min(12, round(width / pane) - 1))


def resize_opening(model: BuildingModel, op: ResizeOpening) -> BuildingModel:
    opening = _opening(model, op.opening_id)
    wall = host_of(model, opening)
    if wall is None:
        raise OperationRejected(
            "HOST_NOT_FOUND", f"{opening.name} has no host wall.", element_id=opening.id
        )
    width, height = _r(op.width_m), _r(op.height_m)
    sill = opening.position.z if op.sill_m is None else _r(op.sill_m)
    if isinstance(opening, Door) and sill != 0:
        raise OperationRejected(
            "INVALID_HOST_POSITION",
            f"{opening.name} is a door: it stands on the floor, its sill must be 0.",
            element_id=opening.id,
        )
    old_x, old_w = opening.position.x, opening.dimensions.width
    if op.offset_m is not None:
        offset = _r(op.offset_m)
    else:
        # Keep the centre; shift only as far as needed to stay inside the wall.
        offset = _r(old_x + (old_w - width) / 2)
        offset = _r(min(max(offset, 0.0), max(wall.dimensions.length - width, 0.0)))
    if (
        abs(width - old_w) < 0.001
        and abs(height - opening.dimensions.height) < 0.001
        and abs(sill - opening.position.z) < 0.001
        and abs(offset - old_x) < 0.001
    ):
        raise OperationRejected(
            "NO_CHANGE", f"{opening.name} already has this size.", element_id=opening.id
        )
    span, rise = (offset, offset + width), (sill, sill + height)
    _check_fits(model, wall, opening.name, span, rise, opening.id)
    update: dict[str, object] = {
        "position": opening.position.model_copy(update={"x": offset, "z": sill}),
        "dimensions": opening.dimensions.model_copy(update={"width": width, "height": height}),
        "relationships": _relationships(opening, model, wall, span),
        "origin": Origin.USER,
    }
    if isinstance(opening, Window):
        update["properties"] = opening.properties.model_copy(
            update={"mullions": _mullions(opening, width)}
        )
    resized = opening.model_copy(update=update)
    if resized.type_ref is not None:
        # A size its catalog type fixes otherwise (e.g. a door type's height) makes it a
        # custom opening: it no longer claims to be an instance of that type.
        snapshot = next((t for t in model.types if t.id == resized.type_ref), None)
        if snapshot is not None and fixed_param_differences(resized, snapshot, None):
            resized = resized.model_copy(update={"type_ref": None})
    return _replace(model, resized)
