"""Design checks of a generated model against the design record it carries (K3).

Part of `validate_model`, so the layout engine's candidate search treats an error here like any
other invariant violation (the next candidate is tried) and the final model is re-checked:

* WINDOW_FACADE_CONFLICT (error) — an emphasised (large/panoramic) window on a facade the user
  excluded.
* WINDOW_PREFERENCE_UNSATISFIABLE (warning) — a preferred facade received no window of the
  requested size (reported, never hidden).
* DESIGN_OFF_SYSTEM (error) — a component or finish outside the selected design system: a type
  not resolved from its role mapping, or a generic finish/furniture material the system
  replaces.
* APPEARANCE_INVALID (error) — an exterior wall face whose display color differs from the
  model's effective facade color.
"""

import uuid
from collections import defaultdict

from app.modules.building.design import GENERIC_FINISHES, GENERIC_FURNITURE, DesignRecord
from app.modules.building.elements import Furniture, Room, Wall, Window
from app.modules.building.enums import RelationshipKind, WallKind
from app.modules.building.facades import facade_of_wall
from app.modules.building.issues import Issue, Severity
from app.modules.building.model import BuildingModel
from app.modules.building.specification import FacadeSide, WindowStyle

EMPHASISED = frozenset({WindowStyle.LARGE, WindowStyle.PANORAMIC})
_OUTDOOR_FLOORS = frozenset({"concrete", "decking"})  # garage, balconies, terraces


class _Issues:
    def __init__(self, model: BuildingModel) -> None:
        self.index = {el.id: i for i, el in enumerate(model.elements)}
        self.items: list[Issue] = []

    def add(
        self, severity: Severity, code: str, message: str, element_id: uuid.UUID | None = None
    ) -> None:
        path = f"/elements/{self.index[element_id]}" if element_id is not None else "/design"
        self.items.append(
            Issue(severity=severity, code=code, path=path, message=message, element_id=element_id)
        )


def window_facades(model: BuildingModel) -> dict[uuid.UUID, FacadeSide | None]:
    """Window id -> facade of its host wall (None: interior host)."""
    walls = {el.id: el for el in model.elements if isinstance(el, Wall)}
    out: dict[uuid.UUID, FacadeSide | None] = {}
    for el in model.elements:
        if not isinstance(el, Window):
            continue
        host = next(
            (
                walls.get(r.target_id)
                for r in el.relationships
                if r.kind == RelationshipKind.HOSTED_BY
            ),
            None,
        )
        out[el.id] = (
            facade_of_wall(host.properties.wall_kind, host.rotation.z) if host is not None else None
        )
    return out


def _windows(model: BuildingModel, design: DesignRecord, out: _Issues) -> None:
    intent = design.windows
    if intent is None:
        return
    facades = window_facades(model)
    emphasised_on: dict[FacadeSide, int] = defaultdict(int)
    for el in model.elements:
        if not isinstance(el, Window):
            continue
        side = facades.get(el.id)
        size = el.properties.size_class
        if side is None or size is None:
            continue
        if size == intent.emphasis:
            emphasised_on[side] += 1
        if size in EMPHASISED and side in intent.excluded_facades:
            out.add(
                "error",
                "WINDOW_FACADE_CONFLICT",
                f"{el.name}: {size.value} window on the {side.value} facade, which is excluded "
                f"from {intent.emphasis.value} windows",
                el.id,
            )
    for side in intent.preferred_facades:
        if emphasised_on[side] == 0:
            out.add(
                "warning",
                "WINDOW_PREFERENCE_UNSATISFIABLE",
                f"No {intent.emphasis.value} window could be placed on the {side.value} facade "
                "(no habitable room with enough free wall there)",
            )


def _system(model: BuildingModel, design: DesignRecord, out: _Issues) -> None:
    system = design.design_system
    if system is None:
        return
    allowed_types = set(system.type_ids)
    fin = system.finishes
    replaced_floors = {GENERIC_FINISHES.dry_floor, GENERIC_FINISHES.wet_floor} - {
        fin.dry_floor,
        fin.wet_floor,
    }
    replaced_walls = {GENERIC_FINISHES.interior_wall, GENERIC_FINISHES.wet_wall} - {
        fin.interior_wall,
        fin.wet_wall,
    }
    replaced_furniture = set(GENERIC_FURNITURE.model_dump().values()) - set(
        system.furniture.model_dump().values()
    )

    def off(name: str, what: str, element_id: uuid.UUID) -> None:
        out.add(
            "error",
            "DESIGN_OFF_SYSTEM",
            f"{name}: {what} is not part of the {system.name} design system",
            element_id,
        )

    for el in model.elements:
        if el.type_ref is not None and el.type_ref not in allowed_types:
            off(el.name, f"type {el.type_ref}", el.id)
        if isinstance(el, Room):
            floor = el.properties.floor_material_id
            if floor in replaced_floors and floor not in _OUTDOOR_FLOORS:
                off(el.name, f"floor finish {floor}", el.id)
        elif isinstance(el, Wall) and el.properties.wall_kind != WallKind.EXTERIOR:
            for face in (el.properties.finish_left_id, el.properties.finish_right_id):
                if face in replaced_walls:
                    off(el.name, f"wall finish {face}", el.id)
        elif isinstance(el, Furniture) and el.material_id in replaced_furniture:
            off(el.name, f"material {el.material_id}", el.id)


def _appearance(model: BuildingModel, out: _Issues) -> None:
    design = model.design
    want = design.facade_color.hex if design is not None and design.facade_color else None
    for el in model.elements:
        if not isinstance(el, Wall) or el.properties.wall_kind != WallKind.EXTERIOR:
            continue
        # Exterior walls run counter-clockwise: the right face is the outside.
        if el.properties.finish_right_color != want:
            out.add(
                "error",
                "APPEARANCE_INVALID",
                f"{el.name}: exterior face color {el.properties.finish_right_color} differs from "
                f"the model's facade color {want}",
                el.id,
            )


def check_model_design(model: BuildingModel) -> list[Issue]:
    out = _Issues(model)
    _appearance(model, out)
    if model.design is not None:
        _windows(model, model.design, out)
        _system(model, model.design, out)
    return out.items
