"""V3 architectural design quality in the layout engine (layout@1.8.0).

Checked on the generated BuildingModel: facade zoning (finishes only, wall cores unchanged),
roof coverings per roof type, the entrance canopy (BuildingModel 1.3.0) and that every
reference house stays valid.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.modules.building.elements import Door, Roof, Slab, Wall
from app.modules.building.enums import DoorKind, RoofType, SlabKind, WallKind
from app.modules.building.model import BuildingModel
from app.modules.building.specification import BuildingSpecification
from app.modules.building.validation import errors, validate_model
from app.modules.catalog.design_systems import resolve_design
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.engine import generate_layout
from tests.building.helpers import material_ids
from tests.catalog.helpers import approved_design_registry
from tests.layout.helpers import NAMESPACE, PROFILE, SPEC_PATHS, generate, load_spec, reference


def exterior(model: BuildingModel) -> list[Wall]:
    return [
        el
        for el in model.elements
        if isinstance(el, Wall) and el.properties.wall_kind == WallKind.EXTERIOR
    ]


def spec_01(**style: Any) -> dict[str, Any]:
    spec = load_spec("01-family-house-280.spec.json").model_dump(mode="json")
    spec["style"].update(style)
    return spec


def test_modern_house_clads_the_garage_volume_and_keeps_the_wall_cores() -> None:
    result = reference("01-family-house-280.spec.json")
    walls = exterior(result.model)
    garage = [w for w in walls if w.semantic_key.startswith("wall:garage:")]
    house = [w for w in walls if not w.semantic_key.startswith("wall:garage:")]
    assert garage and house
    assert {w.properties.finish_right_id for w in garage} == {"cladding_timber"}
    assert {w.properties.finish_right_id for w in house} == {"exterior_wall"}
    # Appearance only: the wall cores keep the requested facade material.
    assert {w.material_id for w in walls} == {"exterior_wall"}
    assert any("garage clad in cladding timber" in n for n in result.notes)


def test_contemporary_two_storey_house_gets_a_brick_plinth_storey() -> None:
    result = generate(spec_01(architectural_style="contemporary"))
    levels: dict[UUID | None, int] = {lvl.id: lvl.index for lvl in result.model.levels}
    house = [w for w in exterior(result.model) if not w.semantic_key.startswith("wall:garage:")]
    ground = {w.properties.finish_right_id for w in house if levels[w.level_id] == 0}
    upper = {w.properties.finish_right_id for w in house if levels[w.level_id] > 0}
    assert ground == {"brick"}
    assert upper == {"exterior_wall"}
    assert any("ground storey in brick" in n for n in result.notes)


def test_a_requested_facade_color_covers_the_whole_facade_without_zones() -> None:
    spec = spec_01(architectural_style="contemporary")
    spec["design"] = {"facade_color": "#e8c547"}
    result = generate(spec)
    walls = exterior(result.model)
    assert {w.properties.finish_right_id for w in walls} == {"exterior_wall"}
    assert {w.properties.finish_right_color for w in walls} == {"#e8c547"}
    assert not any("zoning" in n.lower() for n in result.notes)


def test_zoning_follows_the_design_system_style() -> None:
    # classic-brick has no default colour; the spec's explicit render wins over its default
    # brick, and its style tag (classic) puts a brick plinth under the render.
    spec = spec_01(architectural_style="modern", facade_material="render")
    spec["style"]["design_system"] = "classic-brick"
    resolution = resolve_design(approved_design_registry(), "classic-brick")
    assert resolution.snapshot is not None and resolution.types is not None
    result = generate_layout(
        BuildingSpecification.model_validate(spec),
        PROFILE,
        id_namespace=NAMESPACE,
        material_ids=material_ids(),
        type_set=resolution.types.type_set,
        design_system=resolution.snapshot,
    )
    levels: dict[UUID | None, int] = {lvl.id: lvl.index for lvl in result.model.levels}
    ground = {
        w.properties.finish_right_id
        for w in exterior(result.model)
        if levels[w.level_id] == 0 and not w.semantic_key.startswith("wall:garage:")
    }
    assert ground == {"brick"}


def test_timber_facades_read_as_cladding_boards_on_a_timber_core() -> None:
    walls = exterior(reference("02-compact-bungalow-90.spec.json").model)
    assert {w.material_id for w in walls} == {"wood"}
    assert {w.properties.finish_right_id for w in walls} == {"cladding_timber"}


@pytest.mark.parametrize(
    "name", ["01-family-house-280.spec.json", "04-narrow-plot-townhouse.spec.json"]
)
def test_roof_coverings_follow_the_roof_type(name: str) -> None:
    roofs = [el for el in reference(name).model.elements if isinstance(el, Roof)]
    assert roofs
    for roof in roofs:
        assert roof.material_id == DEFAULT_CONFIG.roof_materials[roof.properties.roof_type]
        if roof.properties.roof_type == RoofType.FLAT:
            assert roof.material_id == "roof_membrane"


@pytest.mark.parametrize("path", SPEC_PATHS, ids=lambda p: p.name.split(".")[0])
def test_every_reference_house_has_a_valid_entrance_canopy(path: Path) -> None:
    model = reference(path.name).model
    canopies = [
        el
        for el in model.elements
        if isinstance(el, Slab) and el.properties.slab_kind == SlabKind.CANOPY
    ]
    entrances = [
        el
        for el in model.elements
        if isinstance(el, Door) and el.properties.door_kind == DoorKind.ENTRANCE
    ]
    assert len(canopies) == len(entrances) == 1
    canopy, door = canopies[0], entrances[0]
    assert canopy.level_id == door.level_id
    assert canopy.position.z - canopy.dimensions.thickness > door.dimensions.height
    assert canopy.type_ref is None  # untyped (no canopy role yet)
    issues = validate_model(model, material_ids=material_ids())
    assert errors(issues) == []
    assert not [i for i in issues if i.code == "CANOPY_PLACEMENT_INVALID"]


def test_a_misplaced_canopy_is_reported() -> None:
    model = reference("01-family-house-280.spec.json").model
    i, canopy = next(
        (i, el)
        for i, el in enumerate(model.elements)
        if isinstance(el, Slab) and el.properties.slab_kind == SlabKind.CANOPY
    )
    low = canopy.model_copy(update={"position": canopy.position.model_copy(update={"z": 1.5})})
    away = canopy.model_copy(
        update={"position": canopy.position.model_copy(update={"x": canopy.position.x + 30})}
    )
    for broken in (low, away):
        elements = list(model.elements)
        elements[i] = broken
        issues = validate_model(model.model_copy(update={"elements": elements}))
        assert any(i.code == "CANOPY_PLACEMENT_INVALID" for i in issues)
