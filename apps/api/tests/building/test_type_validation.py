"""Type/assembly invariants of BuildingModel 1.1.0 (building/type_validation.py)."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.building.elements import Room, Wall
from app.modules.building.enums import SlabKind, WallKind
from app.modules.building.fixtures.demo_house import build_demo_house
from app.modules.building.model import BuildingModel
from app.modules.building.types import (
    AssemblyKind,
    AssemblySnapshot,
    Layer,
    LayerFunction,
    SlabTypeParams,
    TypeSnapshot,
    WallTypeParams,
)
from app.modules.building.validation import validate_model
from tests.building.helpers import material_ids

HASH = "0" * 64


def _assembly(total: float = 0.3, layers: list[Layer] | None = None, **kw: Any) -> AssemblySnapshot:
    return AssemblySnapshot(
        id=kw.get("id", "assembly.wall.test_300"),
        kind=kw.get("kind", AssemblyKind.WALL),
        name="Test wall",
        layers=layers
        or [Layer(function=LayerFunction.STRUCTURE, material_id=None, thickness=total)],
        total_thickness=total,
        source="test-types@1",
        content_sha256=HASH,
    )


def _wall_type(assembly_id: str | None = "assembly.wall.test_300") -> TypeSnapshot:
    return TypeSnapshot(
        id="type.wall.test_exterior",
        family="family.wall.basic",
        name="Test exterior wall",
        params=WallTypeParams(wall_kind=WallKind.EXTERIOR, load_bearing=True),
        assembly_id=assembly_id,
        source="test-types@1",
        content_sha256=HASH,
    )


def _typed(
    model: BuildingModel,
    *,
    types: list[TypeSnapshot],
    assemblies: list[AssemblySnapshot],
    ref: str | None = "type.wall.test_exterior",
    pick: str = "wall",
) -> BuildingModel:
    """Give the first exterior wall (or the first element of type `pick`) the type `ref`."""
    elements = list(model.elements)
    for i, el in enumerate(elements):
        if el.type == pick and (
            pick != "wall"
            or (isinstance(el, Wall) and el.properties.wall_kind == WallKind.EXTERIOR)
        ):
            elements[i] = el.model_copy(update={"type_ref": ref})
            break
    return model.model_copy(update={"elements": elements, "types": types, "assemblies": assemblies})


def _codes(model: BuildingModel) -> set[str]:
    return {i.code for i in validate_model(model, material_ids=material_ids())}


DEMO = build_demo_house()


def test_demo_exterior_walls_are_300() -> None:
    walls = [
        e for e in DEMO.elements if isinstance(e, Wall) and e.properties.wall_kind == "exterior"
    ]
    assert walls and all(w.dimensions.thickness == 0.3 for w in walls)


def test_a_correctly_typed_element_is_valid() -> None:
    model = _typed(DEMO, types=[_wall_type()], assemblies=[_assembly()])
    issues = validate_model(model, material_ids=material_ids())
    assert [i for i in issues if i.severity == "error"] == []
    assert not {i.code for i in issues} & {"SNAPSHOT_UNUSED", "TYPE_PARAM_MISMATCH"}


def test_unknown_type_reference() -> None:
    model = _typed(DEMO, types=[], assemblies=[], ref="type.wall.nowhere")
    assert "TYPE_REF_UNKNOWN" in _codes(model)


def test_element_type_mismatch() -> None:
    model = _typed(DEMO, types=[_wall_type()], assemblies=[_assembly()], pick="slab")
    assert "TYPE_ELEMENT_MISMATCH" in _codes(model)


def test_type_parameter_mismatch_thickness_and_kind() -> None:
    thin = _assembly(
        total=0.25, layers=[Layer(function="structure", material_id=None, thickness=0.25)]
    )
    codes = _codes(_typed(DEMO, types=[_wall_type()], assemblies=[thin]))
    assert "TYPE_PARAM_MISMATCH" in codes
    interior = _wall_type().model_copy(
        update={"params": WallTypeParams(wall_kind=WallKind.INTERIOR, load_bearing=False)}
    )
    issues = validate_model(
        _typed(DEMO, types=[interior], assemblies=[_assembly()]), material_ids=material_ids()
    )
    mismatch = [i for i in issues if i.code == "TYPE_PARAM_MISMATCH"]
    assert mismatch and "wall_kind" in mismatch[0].message and "load_bearing" in mismatch[0].message
    assert mismatch[0].element_id is not None


def test_assembly_thickness_must_add_up() -> None:
    bad = _assembly(
        total=0.3, layers=[Layer(function="structure", material_id=None, thickness=0.2)]
    )
    assert "ASSEMBLY_THICKNESS_SUM" in _codes(_typed(DEMO, types=[_wall_type()], assemblies=[bad]))


def test_layered_assembly_adds_up() -> None:
    layers = [
        Layer(function="finish", material_id="exterior_wall", thickness=0.02, side="exterior"),
        Layer(function="structure", material_id=None, thickness=0.26),
        Layer(function="finish", material_id="interior_wall", thickness=0.02, side="interior"),
        Layer(function="surface", material_id="interior_wall", thickness=0.0, side="interior"),
    ]
    model = _typed(DEMO, types=[_wall_type()], assemblies=[_assembly(0.3, layers)])
    assert not _codes(model) & {"ASSEMBLY_THICKNESS_SUM", "TYPE_PARAM_MISMATCH", "UNKNOWN_MATERIAL"}


def test_unknown_layer_material() -> None:
    layers = [Layer(function="structure", material_id="unobtainium", thickness=0.3)]
    model = _typed(DEMO, types=[_wall_type()], assemblies=[_assembly(0.3, layers)])
    assert "UNKNOWN_MATERIAL" in _codes(model)


def test_type_needs_its_assembly_kind() -> None:
    floor = _assembly(kind=AssemblyKind.FLOOR)
    assert "TYPE_ASSEMBLY_UNKNOWN" in _codes(_typed(DEMO, types=[_wall_type()], assemblies=[floor]))
    assert "TYPE_ASSEMBLY_UNKNOWN" in _codes(_typed(DEMO, types=[_wall_type(None)], assemblies=[]))


def test_unused_snapshots_are_warnings() -> None:
    slab_type = TypeSnapshot(
        id="type.slab.test_floor",
        family="family.slab.basic",
        name="Unused slab type",
        params=SlabTypeParams(slab_kind=SlabKind.FLOOR),
        assembly_id="assembly.floor.test_200",
        source="test-types@1",
        content_sha256=HASH,
    )
    floor = _assembly(0.2, id="assembly.floor.test_200", kind=AssemblyKind.FLOOR)
    orphan = _assembly(0.3, id="assembly.wall.orphan")
    model = _typed(DEMO, types=[_wall_type(), slab_type], assemblies=[_assembly(), floor, orphan])
    issues = validate_model(model, material_ids=material_ids())
    unused = [i for i in issues if i.code == "SNAPSHOT_UNUSED"]
    assert {i.severity for i in unused} == {"warning"}
    assert {i.message.split()[0] for i in unused} == {
        "type.slab.test_floor",
        "assembly.wall.orphan",
    }


def test_duplicate_snapshots() -> None:
    model = _typed(DEMO, types=[_wall_type(), _wall_type()], assemblies=[_assembly()])
    assert "TYPE_SNAPSHOT_DUPLICATE" in _codes(model)


def test_ceiling_assembly_reference() -> None:
    elements = list(DEMO.elements)
    i = next(i for i, e in enumerate(elements) if isinstance(e, Room))
    room = elements[i]
    assert isinstance(room, Room)
    elements[i] = room.model_copy(
        update={
            "properties": room.properties.model_copy(
                update={"ceiling_assembly_ref": "assembly.ceiling.test"}
            )
        }
    )
    missing = DEMO.model_copy(update={"elements": elements})
    assert "CEILING_ASSEMBLY_UNKNOWN" in _codes(missing)
    ceiling = AssemblySnapshot(
        id="assembly.ceiling.test",
        kind=AssemblyKind.CEILING,
        name="Painted ceiling",
        layers=[Layer(function="surface", material_id="interior_wall", thickness=0)],
        total_thickness=0,
        source="test-types@1",
        content_sha256=HASH,
    )
    ok = missing.model_copy(update={"assemblies": [ceiling]})
    assert not _codes(ok) & {"CEILING_ASSEMBLY_UNKNOWN", "SNAPSHOT_UNUSED"}


@pytest.mark.parametrize(
    ("function", "thickness"), [("surface", 0.01), ("structure", 0.0), ("finish", 0.0)]
)
def test_only_surface_layers_have_zero_thickness(function: str, thickness: float) -> None:
    with pytest.raises(ValidationError):
        Layer.model_validate({"function": function, "material_id": None, "thickness": thickness})
