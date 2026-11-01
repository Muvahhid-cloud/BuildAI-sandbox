"""Wall properties (Phase 3.6 D2.5): thickness, face finishes, height.

- `set_wall_thickness`: the axis stays (room boundaries stay on wall axes); an exterior wall
  changes on every storey of its facade and the envelope follows its outer face
  (`envelope.set_facade_thickness`). The design range is the rules profile's
  (`walls.*_thickness_m`, checked by rules.model_checks in the editing service).
- `set_wall_finish`: a material-library id on one or both faces; the id is checked against the
  library by `validate_model` in the editing service. A chosen material replaces a display
  colour on that face.
- `set_wall_height`: only walls that carry nothing (no `supports`) and only down from the
  storey's structural wall height; openings must stay below the new top
  (`walls.min_height_m` is the profile's lowest wall).
"""

from app.modules.building.elements import Door, Wall, Window
from app.modules.building.enums import Origin, RelationshipKind, WallKind
from app.modules.building.model import BuildingModel
from app.modules.building.operations.envelope import set_facade_thickness
from app.modules.building.operations.schemas import (
    OperationRejected,
    SetWallFinish,
    SetWallHeight,
    SetWallThickness,
)
from app.modules.building.primitives import EPS


def _wall(model: BuildingModel, wall_id: object) -> Wall:
    wall = next((e for e in model.elements if e.id == wall_id), None)
    if not isinstance(wall, Wall):
        raise OperationRejected("WALL_NOT_FOUND", "The wall is not in this design.")
    return wall


def _replace(model: BuildingModel, el: Wall) -> BuildingModel:
    return model.model_copy(
        update={"elements": [el if e.id == el.id else e for e in model.elements]}
    )


def set_wall_thickness(model: BuildingModel, op: SetWallThickness) -> BuildingModel:
    wall = _wall(model, op.wall_id)
    thickness = round(op.thickness_m, 3)
    if abs(thickness - wall.dimensions.thickness) < 0.001:
        raise OperationRejected(
            "NO_CHANGE", f"{wall.name} is already {thickness:.3f} m thick.", element_id=wall.id
        )
    if wall.properties.wall_kind == WallKind.EXTERIOR:
        return set_facade_thickness(model, wall, thickness)
    return _replace(
        model,
        wall.model_copy(
            update={
                "dimensions": wall.dimensions.model_copy(update={"thickness": thickness}),
                "origin": Origin.USER,
            }
        ),
    )


def set_wall_finish(model: BuildingModel, op: SetWallFinish) -> BuildingModel:
    wall = _wall(model, op.wall_id)
    props = wall.properties
    update: dict[str, object] = {}
    if op.face in ("left", "both"):
        update |= {"finish_left_id": op.material_id, "finish_left_color": None}
    if op.face in ("right", "both"):
        update |= {"finish_right_id": op.material_id, "finish_right_color": None}
    new = props.model_copy(update=update)
    if new == props:
        raise OperationRejected(
            "NO_CHANGE",
            f"{wall.name} already has {op.material_id} on that face.",
            element_id=wall.id,
        )
    return _replace(model, wall.model_copy(update={"properties": new, "origin": Origin.USER}))


def set_wall_height(model: BuildingModel, op: SetWallHeight) -> BuildingModel:
    wall = _wall(model, op.wall_id)
    height = round(op.height_m, 3)
    if any(r.kind == RelationshipKind.SUPPORTS for r in wall.relationships):
        raise OperationRejected(
            "WALL_HEIGHT_FIXED",
            f"{wall.name} carries a slab or the roof; its height is the storey's and changes "
            "only with the storey.",
            element_id=wall.id,
        )
    if abs(height - wall.dimensions.height) < 0.001:
        raise OperationRejected(
            "NO_CHANGE", f"{wall.name} is already {height:.2f} m high.", element_id=wall.id
        )
    storey = max(
        (
            e.dimensions.height
            for e in model.elements
            if isinstance(e, Wall)
            and e.level_id == wall.level_id
            and any(r.kind == RelationshipKind.SUPPORTS for r in e.relationships)
        ),
        default=wall.dimensions.height,
    )
    if height > storey + EPS:
        raise OperationRejected(
            "WALL_HEIGHT_EXCEEDS_STOREY",
            f"{wall.name} cannot be higher than the storey's walls ({storey:.2f} m): it would "
            "run into the slab or roof above.",
            element_id=wall.id,
        )
    for el in model.elements:
        if not isinstance(el, Door | Window):
            continue
        if not any(
            r.kind == RelationshipKind.HOSTED_BY and r.target_id == wall.id
            for r in el.relationships
        ):
            continue
        head = el.position.z + el.dimensions.height
        if head > height + EPS:
            raise OperationRejected(
                "OPENING_ABOVE_WALL_TOP",
                f"{el.name} reaches {head:.2f} m, above the new top of {wall.name} "
                f"({height:.2f} m). Lower or remove it first.",
                element_id=wall.id,
                related_ids=[el.id],
            )
    return _replace(
        model,
        wall.model_copy(
            update={
                "dimensions": wall.dimensions.model_copy(update={"height": height}),
                "origin": Origin.USER,
            }
        ),
    )
