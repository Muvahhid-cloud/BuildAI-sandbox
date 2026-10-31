"""`add_wall` (Phase 3.6 D2.4, docs/building-model.md §5.5): divide a room with a new interior
wall, judged by the editing check like every edit."""

import json
import uuid
from functools import cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from shapely.geometry import Polygon as ShapelyPolygon

from app.modules.building.elements import Door, Element, Room, Wall
from app.modules.building.enums import RoomType
from app.modules.building.migrations import load_model
from app.modules.building.model import BuildingModel
from app.modules.building.operations import (
    AddWall,
    BatchRejected,
    Operation,
    RemoveWall,
    apply_operations,
)
from app.modules.building.operations.openings import door_rooms, host_of
from app.modules.building.operations.relationships import room_ring
from app.modules.building.validation import errors, validate_model
from app.modules.editing.evaluate import EditOutcome, evaluate_edits
from app.shared.data_files import material_ids, rules_profile

DATA = Path(__file__).resolve().parents[4] / "data"
PROFILE = rules_profile(DATA, "generic-residential@1")
MATERIALS = material_ids(DATA)


@cache
def fixture(name: str = "demo-house") -> BuildingModel:
    raw = json.loads((DATA / "fixtures" / f"{name}.model.json").read_text(encoding="utf-8"))
    return load_model(raw)


def el(model: BuildingModel, key: str) -> Element:
    return next(e for e in model.elements if e.semantic_key == key)


def room(model: BuildingModel, key: str) -> Room:
    r = el(model, key)
    assert isinstance(r, Room)
    return r


def check(ops: list[Operation], model: BuildingModel | None = None) -> EditOutcome:
    return evaluate_edits(model or fixture(), ops, PROFILE, MATERIALS)


def split(
    key: str,
    direction: str,
    x: float,
    y: float,
    *,
    new_type: RoomType | None = RoomType.STORAGE,
    door: bool = True,
) -> AddWall:
    return AddWall.model_validate(
        {
            "room_id": str(room(fixture(), key).id),
            "direction": direction,
            "x_m": x,
            "y_m": y,
            "new_room_type": new_type,
            **({"door_width_m": 0.8, "door_height_m": 2.1} if door else {}),
        }
    )


def rejected(ops: list[Operation]) -> tuple[str, str]:
    out = check(ops)
    assert out.model is None and out.rejection is not None
    if out.rejection.code == "EDIT_INVALID":
        return out.rejection.issues[0].code, out.rejection.message
    return out.rejection.code, out.rejection.message


def test_a_new_wall_divides_a_room_into_two_with_a_door() -> None:
    base = fixture()
    entrance = room(base, "room:entrance")  # 3.4 x 4.8
    out = check([split("room:entrance", "north_south", 1.02, 1.44)])
    assert out.model is not None, out.rejection
    kept = room(out.model, "room:entrance")
    new = room(out.model, "room:edit:1")
    assert kept.id == entrance.id and kept.name == entrance.name
    assert kept.properties.room_type == entrance.properties.room_type
    assert new.properties.room_type == RoomType.STORAGE and new.properties.zone == "service"
    assert new.name == "New room 1" and new.level_id == entrance.level_id
    assert kept.dimensions.area + new.dimensions.area == pytest.approx(
        entrance.dimensions.area, abs=0.02
    )
    assert kept.dimensions.area > new.dimensions.area  # the larger part keeps the room
    wall = el(out.model, "wall:edit:1")
    assert isinstance(wall, Wall)
    assert wall.properties.wall_kind == "interior" and wall.origin == "user"
    assert wall.position.x == 1.02 and wall.rotation.z == pytest.approx(1.570796)
    door = el(out.model, "door:edit:1")
    assert isinstance(door, Door) and host_of(out.model, door) == wall
    connects = {r.target_id for r in door.relationships if r.kind == "connects"}
    assert connects == {kept.id, new.id}
    assert {wall.id, new.id, door.id, entrance.id} <= set(out.changed_ids)
    assert not errors(validate_model(out.model, material_ids=MATERIALS))


def test_ids_are_deterministic_and_replays_identical() -> None:
    op = split("room:entrance", "north_south", 1.02, 1.44)
    a, b = check([op]), check([op])
    assert a.model is not None and a.model == b.model
    assert el(a.model, "wall:edit:1").id == uuid.uuid5(fixture().id, "edit:wall:edit:1")


def test_doors_into_the_room_are_reconnected_to_the_part_they_open_into() -> None:
    out = check([split("room:entrance", "north_south", 1.02, 1.44)])
    assert out.model is not None
    for e in out.model.elements:
        if isinstance(e, Door):
            host = host_of(out.model, e)
            assert host is not None
            span = (e.position.x, e.position.x + e.dimensions.width)
            connects = {r.target_id for r in e.relationships if r.kind == "connects"}
            assert connects == set(door_rooms(out.model, host, span)), e.name


@pytest.mark.parametrize(
    ("args", "code", "phrase"),
    [
        (("room:entrance", "east_west", 0.34, 0.48), "WALL_END_OPEN", "open boundary"),
        (("room:entrance", "north_south", 0.34, 0.48), "WALL_END_ON_OPENING", "WN-G01"),
        (("room:bath_g", "east_west", 5.06, 2.64), "FURNITURE_IN_THE_WAY", "Basin"),
        (("room:staircase", "east_west", 3.54, 0.48), "ROOM_TYPE_UNSUPPORTED", "staircase"),
        (("room:entrance", "north_south", 9.0, 9.0), "POINT_OUTSIDE_ROOM", "not inside"),
        (("room:entrance", "north_south", 2.72, 3.84), "RULE_ROOM_WIDTH", "clear width"),
        (("room:storage", "east_west", 5.06, 0.24), "RULE_ROOM_AREA", "minimum"),
    ],
)
def test_walls_that_cannot_be_added_are_refused_with_the_reason(
    args: tuple[str, str, float, float], code: str, phrase: str
) -> None:
    got, message = rejected([split(*args)])
    assert got == code and phrase in message


def test_a_new_room_must_stay_reachable() -> None:
    out = check([split("room:entrance", "north_south", 1.02, 1.44, door=False)])
    assert out.rejection is not None
    assert any(i.code == "ROOM_UNREACHABLE" for i in out.rejection.issues)


def test_a_new_room_type_that_is_tied_to_the_building_is_refused() -> None:
    got, _ = rejected([split("room:entrance", "north_south", 1.02, 1.44, new_type=RoomType.GARAGE)])
    assert got == "ROOM_TYPE_UNSUPPORTED"


def test_door_size_comes_in_pairs() -> None:
    with pytest.raises(ValueError):
        AddWall(room_id=uuid.uuid4(), direction="east_west", x_m=1, y_m=1, door_width_m=0.8)


def test_removing_the_new_wall_and_merging_gives_the_room_back() -> None:
    base = fixture()
    added = apply_operations(base, [split("room:entrance", "north_south", 1.02, 1.44)])
    wall = el(added, "wall:edit:1")
    out = check([RemoveWall(wall_id=wall.id, merge_rooms=True)], added)
    assert out.model is not None, out.rejection
    back = room(out.model, "room:entrance")
    assert back.dimensions.area == room(base, "room:entrance").dimensions.area
    assert all(e.semantic_key not in ("room:edit:1", "door:edit:1") for e in out.model.elements)


def test_a_refused_wall_leaves_the_model_unchanged() -> None:
    base = fixture()
    snapshot = base.model_dump(mode="json")
    with pytest.raises(BatchRejected):
        apply_operations(base, [split("room:bath_g", "east_west", 5.06, 2.64)])
    assert base.model_dump(mode="json") == snapshot


@cache
def _rooms(name: str) -> list[tuple[uuid.UUID, tuple[float, float, float, float]]]:
    return [
        (e.id, ShapelyPolygon(room_ring(e)).bounds)
        for e in fixture(name).elements
        if isinstance(e, Room)
    ]


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    name=st.sampled_from(["demo-house", "generated-house", "generated-l-house"]),
    pick=st.integers(min_value=0, max_value=10_000),
    tx=st.floats(min_value=0.05, max_value=0.95),
    ty=st.floats(min_value=0.05, max_value=0.95),
    direction=st.sampled_from(["east_west", "north_south"]),
)
def test_every_new_wall_is_refused_or_consistent(
    name: str, pick: int, tx: float, ty: float, direction: str
) -> None:
    base = fixture(name)
    rooms = _rooms(name)
    room_id, (x0, y0, x1, y1) = rooms[pick % len(rooms)]
    op = AddWall.model_validate(
        {
            "room_id": str(room_id),
            "direction": direction,
            "x_m": x0 + (x1 - x0) * tx,
            "y_m": y0 + (y1 - y0) * ty,
            "door_width_m": 0.8,
            "door_height_m": 2.1,
            "new_room_type": "storage",
        }
    )
    out = check([op], base)
    if out.model is None:
        assert out.rejection is not None and out.rejection.message
        return
    assert not errors(validate_model(out.model, material_ids=MATERIALS))
    before = [e for e in base.elements if isinstance(e, Room)]
    after = [e for e in out.model.elements if isinstance(e, Room)]
    assert len(after) == len(before) + 1
    old = next(r for r in before if r.id == room_id)
    parts = [r for r in after if r.id == room_id or r.semantic_key == "room:edit:1"]
    assert sum(r.dimensions.area for r in parts) == pytest.approx(old.dimensions.area, abs=0.03)
