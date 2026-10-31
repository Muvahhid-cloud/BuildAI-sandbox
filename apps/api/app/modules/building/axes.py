"""Coordination axes derived from wall geometry (Phase 3.5 K2.5, docs/building-model.md §4.1).

v1 models are rectilinear, so every wall axis lies on a line x = c or y = c. The derived axes
are those lines, building-wide, each with the walls (on any level) that run along it. They are
*derived*, never stored: the wall axes are the source of truth, and axes cannot drift from
them. The geometric checks use them to find collinear walls; drawing output (labels, bubbles,
dimension chains) and persistent grid elements are later work. No labelling convention is
applied — the SPDS axis conventions of the K1 knowledge pack are unreviewed and not consumed.
"""

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from app.modules.building.elements import Wall
from app.modules.building.geometry import is_axis_aligned, wall_axis
from app.modules.building.model import BuildingModel

AXIS_DECIMALS = 3  # 1 mm, like every stored coordinate
_Member = tuple[float, float, str, uuid.UUID]  # (level elevation, start along the axis, id)


@dataclass(frozen=True)
class CoordinationAxis:
    """The line `x = coord` (direction "y": walls running north-south) or `y = coord`
    (direction "x")."""

    direction: Literal["x", "y"]
    coord: float
    wall_ids: tuple[uuid.UUID, ...]  # sorted by (level elevation, start along the axis, id)

    @property
    def key(self) -> str:
        return f"{'y' if self.direction == 'x' else 'x'}={self.coord:.3f}"


def wall_direction(wall: Wall) -> Literal["x", "y"] | None:
    """Direction of an axis-aligned wall; None for oblique walls (outside v1 scope)."""
    if not is_axis_aligned(wall.rotation.z):
        return None
    return "x" if abs(math.cos(wall.rotation.z)) > 0.5 else "y"


def derive_axes(model: BuildingModel) -> list[CoordinationAxis]:
    """All coordination axes of the model's walls, sorted by direction then coordinate."""
    elevation = {lvl.id: lvl.elevation for lvl in model.levels}
    groups: dict[tuple[Literal["x", "y"], float], list[_Member]] = defaultdict(list)
    for el in model.elements:
        if not isinstance(el, Wall):
            continue
        direction = wall_direction(el)
        if direction is None:
            continue
        (sx, sy), (ex, ey) = wall_axis(el)
        coord = round(sy if direction == "x" else sx, AXIS_DECIMALS) + 0.0
        along = min(sx, ex) if direction == "x" else min(sy, ey)
        level_z = elevation.get(el.level_id, 0.0) if el.level_id else 0.0
        groups[(direction, coord)].append((level_z, along, str(el.id), el.id))
    return [
        CoordinationAxis(direction, coord, tuple(w[3] for w in sorted(walls)))
        for (direction, coord), walls in sorted(groups.items())
    ]
