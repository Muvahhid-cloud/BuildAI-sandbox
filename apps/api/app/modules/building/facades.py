"""Semantic facades: front / rear / left / right (K3, docs/building-model.md §2.2).

Deterministic and derived from geometry — nothing is stored. The generated plan puts the street
on the model's south side (-y) (`Site`, layout planner), so:

    front = street / entrance side      outward normal -y   (plan side "S")
    rear  = garden / backyard side      outward normal +y   (plan side "N")
    left  = left as seen from the street outward normal -x  (plan side "W")
    right = right as seen from the street outward normal +x (plan side "E")

An exterior wall's facade is the direction of its outward normal. Exterior walls are authored
counter-clockwise around the building, so the outward (right-hand) normal of a wall with axis
direction θ is (sin θ, -cos θ). The camera is never involved.

Natural-language words map to facades through one fixed table (`FACADE_SYNONYMS`), used by the
mock interpreter and documented in the AI prompt vocabulary.
"""

import math

from app.modules.building.enums import WallKind
from app.modules.building.specification import FacadeSide

FACADE_SYNONYMS: dict[str, FacadeSide] = {
    "front": FacadeSide.FRONT,
    "street": FacadeSide.FRONT,
    "entrance": FacadeSide.FRONT,
    "road": FacadeSide.FRONT,
    "rear": FacadeSide.REAR,
    "back": FacadeSide.REAR,
    "backyard": FacadeSide.REAR,
    "back yard": FacadeSide.REAR,
    "garden": FacadeSide.REAR,
    "yard": FacadeSide.REAR,
    "left": FacadeSide.LEFT,
    "right": FacadeSide.RIGHT,
}

# Plan sides used by the layout engine (compass letters of the rectangular footprint).
PLAN_SIDE: dict[FacadeSide, str] = {
    FacadeSide.FRONT: "S",
    FacadeSide.REAR: "N",
    FacadeSide.LEFT: "W",
    FacadeSide.RIGHT: "E",
}
FACADE_OF_PLAN_SIDE: dict[str, FacadeSide] = {v: k for k, v in PLAN_SIDE.items()}


def normalize_facade(word: str) -> FacadeSide | None:
    """The facade a word or short phrase names ("backyard" -> rear), or None."""
    key = " ".join(word.lower().replace("-", " ").split())
    if key in FACADE_SYNONYMS:
        return FACADE_SYNONYMS[key]
    return FACADE_SYNONYMS.get(key.removesuffix(" facade").removesuffix(" side"))


def facade_of_normal(nx: float, ny: float) -> FacadeSide:
    """Facade of an outward normal (the dominant axis decides; ties go to front/rear)."""
    if abs(ny) >= abs(nx):
        return FacadeSide.FRONT if ny < 0 else FacadeSide.REAR
    return FacadeSide.LEFT if nx < 0 else FacadeSide.RIGHT


def facade_of_wall(wall_kind: WallKind, rotation_z: float) -> FacadeSide | None:
    """Facade an exterior wall belongs to; None for interior walls and partitions."""
    if wall_kind != WallKind.EXTERIOR:
        return None
    return facade_of_normal(math.sin(rotation_z), -math.cos(rotation_z))
