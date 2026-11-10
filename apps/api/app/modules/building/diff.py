"""What changed between two BuildingModels, measured on them (docs/building-model.md §5.7).

Used for the change summary of an AI modification preview and for comparing two versions. Every
number comes from the models themselves (room areas and extents, opening sizes, the summary's
gross floor area) — never from a plan, an AI answer or a drawing. Pure and deterministic.
"""

import math
import uuid
from typing import Literal

from pydantic import Field

from app.modules.building.elements import Door, Element, Room, Wall, Window
from app.modules.building.geometry import to_absolute
from app.modules.building.model import BuildingModel
from app.modules.building.operations.openings import door_rooms, host_of
from app.modules.building.primitives import EPS, Frozen
from app.modules.building.summary import summarize

ChangeKind = Literal[
    "room_added",
    "room_removed",
    "room_resized",
    "room_renamed",
    "room_retyped",
    "opening_added",
    "opening_removed",
    "opening_resized",
    "opening_moved",
    "walls",
    "floor_area",
]


class ChangeLine(Frozen):
    kind: ChangeKind
    text: str
    element_id: uuid.UUID | None = None


class ModelDiff(Frozen):
    """Element ids that exist only in `after` (added), only in `before` (removed) or in both
    with different stored data (changed), and readable, measured lines about them."""

    added: list[uuid.UUID] = Field(default_factory=list)
    removed: list[uuid.UUID] = Field(default_factory=list)
    changed: list[uuid.UUID] = Field(default_factory=list)
    lines: list[ChangeLine] = Field(default_factory=list)


def room_extent(room: Room) -> tuple[float, float]:
    """Width (x) and depth (y) of the room's bounding box, in meters."""
    pts = to_absolute(room.properties.boundary, room.position, room.rotation)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return max(xs) - min(xs), max(ys) - min(ys)


def _type_label(room: Room) -> str:
    return room.properties.room_type.value.replace("_", " ")


def _opening_rooms(model: BuildingModel, opening: Door | Window) -> str:
    wall = host_of(model, opening)
    if wall is None:
        return ""
    span = (opening.position.x, opening.position.x + opening.dimensions.width)
    by_id = {e.id: e for e in model.elements}
    names = [by_id[i].name for i in door_rooms(model, wall, span) if i in by_id]
    return f" ({', '.join(names)})" if names else ""


def _size(opening: Door | Window) -> str:
    return f"{opening.dimensions.width:.2f} x {opening.dimensions.height:.2f} m"


def _kind(opening: Door | Window) -> str:
    return "Window" if isinstance(opening, Window) else "Door"


def _label(opening: Door | Window) -> str:
    kind = _kind(opening)
    return (
        opening.name if opening.name.lower().startswith(kind.lower()) else f"{kind} {opening.name}"
    )


def diff_models(before: BuildingModel, after: BuildingModel) -> ModelDiff:
    old: dict[uuid.UUID, Element] = {e.id: e for e in before.elements}
    new: dict[uuid.UUID, Element] = {e.id: e for e in after.elements}
    added = sorted((i for i in new if i not in old), key=str)
    removed = sorted((i for i in old if i not in new), key=str)
    changed = sorted((i for i in new if i in old and old[i] != new[i]), key=str)
    lines: list[ChangeLine] = []

    # Rooms (in the after model's order, then removed ones).
    for el in after.elements:
        if not isinstance(el, Room):
            continue
        prev = old.get(el.id)
        w, d = room_extent(el)
        if not isinstance(prev, Room):
            lines.append(
                ChangeLine(
                    kind="room_added",
                    element_id=el.id,
                    text=f"{el.name} ({_type_label(el)}) added: {el.dimensions.area:.1f} m², "
                    f"{w:.2f} x {d:.2f} m",
                )
            )
            continue
        if prev.name != el.name:
            lines.append(
                ChangeLine(
                    kind="room_renamed",
                    element_id=el.id,
                    text=f"{prev.name} renamed to {el.name}",
                )
            )
        if prev.properties.room_type != el.properties.room_type:
            lines.append(
                ChangeLine(
                    kind="room_retyped",
                    element_id=el.id,
                    text=f"{el.name}: {_type_label(prev)} → {_type_label(el)}",
                )
            )
        if abs(prev.dimensions.area - el.dimensions.area) > 0.005:
            pw, pd = room_extent(prev)
            lines.append(
                ChangeLine(
                    kind="room_resized",
                    element_id=el.id,
                    text=f"{el.name}: {prev.dimensions.area:.1f} m² → {el.dimensions.area:.1f} m² "
                    f"({pw:.2f} x {pd:.2f} m → {w:.2f} x {d:.2f} m)",
                )
            )
    for i in removed:
        prev = old[i]
        if isinstance(prev, Room):
            lines.append(
                ChangeLine(
                    kind="room_removed",
                    element_id=i,
                    text=f"{prev.name} ({_type_label(prev)}, {prev.dimensions.area:.1f} m²) "
                    "removed",
                )
            )

    # Doors and windows.
    for el in after.elements:
        if not isinstance(el, Door | Window):
            continue
        prev = old.get(el.id)
        if not isinstance(prev, Door | Window):
            lines.append(
                ChangeLine(
                    kind="opening_added",
                    element_id=el.id,
                    text=f"{_label(el)}{_opening_rooms(after, el)} added: {_size(el)}",
                )
            )
            continue
        resized = (
            abs(prev.dimensions.width - el.dimensions.width) > EPS
            or abs(prev.dimensions.height - el.dimensions.height) > EPS
            or abs(prev.position.z - el.position.z) > EPS
        )
        if resized:
            sill = (
                f", sill {prev.position.z:.2f} → {el.position.z:.2f} m"
                if isinstance(el, Window) and abs(prev.position.z - el.position.z) > EPS
                else ""
            )
            lines.append(
                ChangeLine(
                    kind="opening_resized",
                    element_id=el.id,
                    text=f"{_label(el)}{_opening_rooms(after, el)}: {_size(prev)} → {_size(el)}"
                    f"{sill}",
                )
            )
        elif _host_id(before, prev) != _host_id(after, el) or (
            abs(prev.position.x - el.position.x) > EPS and _moved_in_plan(before, prev, after, el)
        ):
            lines.append(
                ChangeLine(
                    kind="opening_moved",
                    element_id=el.id,
                    text=f"{_label(el)}{_opening_rooms(after, el)} moved",
                )
            )
    for i in removed:
        prev = old[i]
        if isinstance(prev, Door | Window):
            lines.append(
                ChangeLine(
                    kind="opening_removed",
                    element_id=i,
                    text=f"{_label(prev)}{_opening_rooms(before, prev)} removed ({_size(prev)})",
                )
            )

    # Walls, aggregated: a facade move changes many of them.
    walls_added = sum(1 for i in added if isinstance(new[i], Wall))
    walls_removed = sum(1 for i in removed if isinstance(old[i], Wall))
    walls_changed = sum(1 for i in changed if isinstance(new[i], Wall))
    if walls_added or walls_removed or walls_changed:
        parts = [
            f"{n} {what}"
            for n, what in (
                (walls_added, "added"),
                (walls_removed, "removed"),
                (walls_changed, "moved or changed"),
            )
            if n
        ]
        lines.append(ChangeLine(kind="walls", text=f"Walls: {', '.join(parts)}"))

    gfa0 = summarize(before).gross_floor_area_m2
    gfa1 = summarize(after).gross_floor_area_m2
    if abs(gfa0 - gfa1) > 0.05:
        lines.append(
            ChangeLine(
                kind="floor_area",
                text=f"Gross floor area: {gfa0:.1f} m² → {gfa1:.1f} m²",
            )
        )
    return ModelDiff(added=added, removed=removed, changed=changed, lines=lines)


def _moved_in_plan(
    before: BuildingModel, prev: Door | Window, after: BuildingModel, el: Door | Window
) -> bool:
    """An opening whose offset changed only because its wall's start moved stays put in plan."""
    w0, w1 = host_of(before, prev), host_of(after, el)
    if w0 is None or w1 is None:
        return True
    c0 = math.cos(w0.rotation.z), math.sin(w0.rotation.z)
    c1 = math.cos(w1.rotation.z), math.sin(w1.rotation.z)
    p0 = (w0.position.x + c0[0] * prev.position.x, w0.position.y + c0[1] * prev.position.x)
    p1 = (w1.position.x + c1[0] * el.position.x, w1.position.y + c1[1] * el.position.x)
    return math.dist(p0, p1) > EPS


def _host_id(model: BuildingModel, opening: Door | Window) -> uuid.UUID | None:
    wall = host_of(model, opening)
    return wall.id if wall else None
