import math
import uuid

import pytest
from pydantic import ValidationError

from app.modules.building.elements import (
    Relationship,
    Room,
    RoomDimensions,
    StairDimensions,
    WallDimensions,
)
from app.modules.building.enums import RelationshipKind
from app.modules.building.fixtures.demo_house import build_demo_house
from app.modules.building.model import BuildingModel
from app.modules.building.primitives import Vec2, Vec3
from app.modules.building.validation import ModelIssue, errors, validate_model
from tests.building.helpers import find, material_ids, with_element


def _codes(model: BuildingModel) -> set[str]:
    issues: list[ModelIssue] = validate_model(model, material_ids=material_ids())
    return {i.code for i in errors(issues)}


@pytest.fixture(scope="module")
def model() -> BuildingModel:
    return build_demo_house()


def test_duplicate_id(model: BuildingModel) -> None:
    _, other = find(model, "wall:G-S")
    assert "DUPLICATE_ID" in _codes(with_element(model, "wall:G-E", id=other.id))


def test_dangling_relationship(model: BuildingModel) -> None:
    rel = Relationship(kind=RelationshipKind.LOCATED_IN, target_id=uuid.uuid4())
    assert "DANGLING_RELATIONSHIP" in _codes(
        with_element(model, "furniture:sofa", relationships=[rel])
    )


def test_opening_outside_wall(model: BuildingModel) -> None:
    moved = with_element(model, "window:kitchen_s", position=Vec3(x=11.5, y=0, z=0.95))
    assert "OPENING_OUTSIDE_WALL" in _codes(moved)


def test_opening_taller_than_wall(model: BuildingModel) -> None:
    _, win = find(model, "window:living_n")
    taller = win.dimensions.model_copy(update={"height": 3.0})
    assert "OPENING_TOO_TALL" in _codes(with_element(model, "window:living_n", dimensions=taller))


def test_overlapping_openings(model: BuildingModel) -> None:
    _, door = find(model, "door:front")
    moved = with_element(model, "window:ent", position=door.position)
    assert "OPENINGS_OVERLAP" in _codes(moved)


def test_opening_must_have_a_wall_host(model: BuildingModel) -> None:
    assert "HOST_NOT_FOUND" in _codes(with_element(model, "window:ent", relationships=[]))


def test_overlapping_rooms(model: BuildingModel) -> None:
    moved = with_element(model, "room:dining", position=Vec3(x=6.0, y=6.0, z=0))
    assert "ROOMS_OVERLAP" in _codes(moved)


def test_room_area_must_match_boundary(model: BuildingModel) -> None:
    dims = RoomDimensions(area=99.0, perimeter=17.4, height=2.8)
    assert "ROOM_AREA_MISMATCH" in _codes(with_element(model, "room:living", dimensions=dims))


def test_clockwise_boundary_rejected(model: BuildingModel) -> None:
    _, room = find(model, "room:living")
    assert isinstance(room, Room)
    cw = room.properties.model_copy(update={"boundary": list(reversed(room.properties.boundary))})
    assert "POLYGON_ORIENTATION" in _codes(with_element(model, "room:living", properties=cw))


def test_non_rectilinear_room_rejected(model: BuildingModel) -> None:
    _, room = find(model, "room:living")
    assert isinstance(room, Room)
    pts = [Vec2(x=0, y=0), Vec2(x=7.4, y=0), Vec2(x=6.0, y=4.0), Vec2(x=0, y=4.0)]
    props = room.properties.model_copy(update={"boundary": pts})
    assert "POLYGON_NOT_RECTILINEAR" in _codes(with_element(model, "room:living", properties=props))


def test_stair_rise_mismatch(model: BuildingModel) -> None:
    dims = StairDimensions(width=1.1, run_length=3.9, rise_total=3.5)
    assert "STAIR_RISE" in _codes(with_element(model, "stair:main", dimensions=dims))


def test_wall_taller_than_level(model: BuildingModel) -> None:
    dims = WallDimensions(length=12, thickness=0.3, height=3.5)
    assert "WALL_TOO_TALL" in _codes(with_element(model, "wall:G-S", dimensions=dims))


def test_unknown_material(model: BuildingModel) -> None:
    assert "UNKNOWN_MATERIAL" in _codes(with_element(model, "wall:G-S", material_id="adamantium"))


def test_habitable_room_without_window_is_a_warning(model: BuildingModel) -> None:
    kept = [
        el
        for el in model.elements
        if not el.semantic_key.startswith(("window:bed2", "door:bedroom2"))
    ]
    issues = validate_model(model.model_copy(update={"elements": kept}))
    assert any(
        i.code == "HABITABLE_ROOM_WITHOUT_WINDOW" and i.severity == "warning" for i in issues
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"dimensions": {"length": math.nan, "thickness": 0.3, "height": 2.8}},
        {"dimensions": {"length": -1, "thickness": 0.3, "height": 2.8}},
        {"unexpected_field": 1},
        {"type": "chimney"},
    ],
)
def test_schema_rejects_invalid_input(model: BuildingModel, patch: dict[str, object]) -> None:
    doc = model.model_dump(mode="json")
    wall = next(e for e in doc["elements"] if e["type"] == "wall")
    wall.update(patch)
    with pytest.raises(ValidationError):
        BuildingModel.model_validate(doc)


def test_lengths_are_rounded_to_millimetres() -> None:
    dims = WallDimensions(length=1.23456, thickness=0.30004, height=2.8)
    assert (dims.length, dims.thickness) == (1.235, 0.3)
