from app.modules.building.fixtures.demo_house import build_demo_house
from app.modules.building.summary import summarize
from app.modules.building.validation import validate_model
from tests.building.helpers import find


def test_demo_house_rooms_are_all_reachable() -> None:
    issues = validate_model(build_demo_house())
    assert [i for i in issues if i.code in {"ROOM_UNREACHABLE", "NO_ENTRANCE"}] == []


def test_removing_the_only_door_strands_a_room() -> None:
    model = build_demo_house()
    _, door = find(model, "door:study")
    model = model.model_copy(update={"elements": [el for el in model.elements if el.id != door.id]})
    _, study = find(model, "room:study")
    unreachable = [i for i in validate_model(model) if i.code == "ROOM_UNREACHABLE"]
    assert [i.element_id for i in unreachable] == [study.id]
    assert unreachable[0].severity == "warning"


def test_upper_floor_is_reached_through_the_stair() -> None:
    model = build_demo_house()
    _, stair = find(model, "stair:main")
    model = model.model_copy(
        update={"elements": [el for el in model.elements if el.id != stair.id]}
    )
    unreachable = {i.element_id for i in validate_model(model) if i.code == "ROOM_UNREACHABLE"}
    upper = {
        el.id for el in model.elements if el.type == "room" and el.level_id == model.levels[1].id
    }
    assert unreachable == upper


def test_demo_house_summary() -> None:
    s = summarize(build_demo_house())
    assert s.storeys == 2
    assert s.gross_floor_area_m2 == 240.0  # 12 x 10 m on wall centerlines, two floors
    assert s.bedrooms == 3
    assert s.bathrooms == 2
    assert s.garage is False
    assert s.balconies == 1
    assert s.walls == 21
    assert s.doors == 13
    assert s.windows == 21
