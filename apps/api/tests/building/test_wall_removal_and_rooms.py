"""`remove_wall`, `rename_room` and `set_room_type` (Phase 3.6 D2.4, docs/building-model.md §5.4)
and how the editing check judges them."""

import json
import uuid
from functools import cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.building.elements import Door, Element, Room, Wall
from app.modules.building.enums import RoomType, Zone
from app.modules.building.geometry import signed_area, to_absolute
from app.modules.building.migrations import load_model
from app.modules.building.model import BuildingModel
from app.modules.building.operations import (
    BatchRejected,
    Operation,
    RemoveElement,
    RemoveWall,
    RenameRoom,
    SetRoomType,
    apply_operations,
)
from app.modules.building.operations.rooms import room_zone
from app.modules.building.operations.wall_removal import rooms_along
from app.modules.building.specification import BuildingSpecification
from app.modules.building.validation import errors, validate_model
from app.modules.editing.evaluate import EditOutcome, evaluate_edits
from app.modules.layout.program import zone_of
from app.shared.data_files import material_ids, rules_profile

DATA = Path(__file__).resolve().parents[4] / "data"
PROFILE = rules_profile(DATA, "generic-residential@1")
MATERIALS = material_ids(DATA)


@cache
def fixture(name: str = "demo-house") -> BuildingModel:
    raw = json.loads((DATA / "fixtures" / f"{name}.model.json").read_text(encoding="utf-8"))
    return load_model(raw)


@cache
def spec01() -> BuildingSpecification:
    path = DATA / "fixtures" / "specs" / "01-family-house-280.spec.json"
    return BuildingSpecification.model_validate_json(path.read_text(encoding="utf-8"))


def el(model: BuildingModel, key: str) -> Element:
    return next(e for e in model.elements if e.semantic_key == key)


def room(model: BuildingModel, key: str) -> Room:
    r = el(model, key)
    assert isinstance(r, Room)
    return r


def check(
    ops: list[Operation],
    model: BuildingModel | None = None,
    spec: BuildingSpecification | None = None,
) -> EditOutcome:
    return evaluate_edits(model or fixture(), ops, PROFILE, MATERIALS, spec=spec)


def remove(key: str, merge: bool = False, name: str = "demo-house") -> RemoveWall:
    return RemoveWall(wall_id=el(fixture(name), key).id, merge_rooms=merge)


def rejected(ops: list[Operation], model: BuildingModel | None = None) -> tuple[str, str]:
    out = check(ops, model)
    assert out.model is None and out.rejection is not None
    return out.rejection.code, out.rejection.message


def ring_area(r: Room) -> float:
    return abs(signed_area(to_absolute(r.properties.boundary, r.position, r.rotation)))


# --- remove_wall: open the rooms into each other ---------------------------------------------


def test_removing_a_wall_opens_the_rooms_and_takes_its_door_along() -> None:
    base = fixture()
    wall = el(base, "wall:G-I1")  # corridor | entrance, hosts door:ent_corr
    door = el(base, "door:ent_corr")
    out = check([remove("wall:G-I1")])
    assert out.model is not None, out.rejection
    ids = {e.id for e in out.model.elements}
    assert wall.id not in ids and door.id not in ids
    # No relationship points at a removed element (no orphaned openings).
    for e in out.model.elements:
        assert all(r.target_id in ids for r in e.relationships), e.name
    # The rooms keep their outlines and areas and are now open to each other.
    for key in ("room:corridor_g", "room:entrance"):
        assert room(out.model, key) == room(base, key).model_copy(
            update={"relationships": room(out.model, key).relationships}
        )
    assert not errors(validate_model(out.model, material_ids=MATERIALS))
    codes = {i.code for i in validate_model(out.model, material_ids=MATERIALS)}
    assert "ROOM_UNREACHABLE" not in codes
    assert wall.id in out.changed_ids and door.id in out.changed_ids


# --- remove_wall: merge the rooms ------------------------------------------------------------


def test_merging_two_rooms_keeps_the_larger_room_with_the_union_outline() -> None:
    base = fixture()
    entrance, corridor = room(base, "room:entrance"), room(base, "room:corridor_g")
    out = check([remove("wall:G-I1", merge=True)])
    assert out.model is not None, out.rejection
    merged = room(out.model, "room:entrance")
    assert merged.id == entrance.id and merged.name == entrance.name
    assert merged.properties.room_type == entrance.properties.room_type
    assert corridor.id not in {e.id for e in out.model.elements}
    assert merged.dimensions.area == pytest.approx(
        entrance.dimensions.area + corridor.dimensions.area, abs=0.02
    )
    assert merged.dimensions.area == pytest.approx(ring_area(merged), abs=0.01)
    assert (
        signed_area(to_absolute(merged.properties.boundary, merged.position, merged.rotation)) > 0
    )
    # Everything that pointed at the corridor points at the merged room.
    ids = {e.id for e in out.model.elements}
    for e in out.model.elements:
        assert all(r.target_id in ids for r in e.relationships), e.name
    reached = [
        e.id
        for e in base.elements
        if isinstance(e, Door)
        and e.semantic_key != "door:ent_corr"
        and any(r.target_id == corridor.id for r in e.relationships)
    ]
    assert reached  # doors from the corridor into other rooms
    for door_id in reached:
        door = next(e for e in out.model.elements if e.id == door_id)
        connects = [r.target_id for r in door.relationships if r.kind == "connects"]
        assert entrance.id in connects and len(connects) == len(set(connects))
    assert not errors(validate_model(out.model, material_ids=MATERIALS))


def test_merged_rooms_on_the_upper_floor_are_a_valid_model() -> None:
    out = check([remove("wall:F-I7", merge=True)])  # master bedroom | study
    assert out.model is not None, out.rejection
    master = room(out.model, "room:master")
    assert master.dimensions.area == pytest.approx(29.6 + 18.4, abs=0.02)
    assert all(e.semantic_key != "room:study" for e in out.model.elements)


@pytest.mark.parametrize(
    ("key", "merge", "code", "phrase"),
    [
        ("wall:G-S", False, "EXTERIOR_WALL_FIXED", "exterior"),
        ("wall:G-I2", False, "WALL_HAS_JUNCTIONS", "W-G08 joins W-G06"),
        ("wall:G-I3", False, "WALL_ENCLOSES_ROOM", "Bathroom"),
        ("wall:G-I3", True, "WALL_ENCLOSES_ROOM", "keep their walls"),
        ("wall:F-I1", False, "WALL_EDGES_OPEN_SPACE", "one side"),
    ],
)
def test_walls_that_cannot_go_are_refused_with_the_reason(
    key: str, merge: bool, code: str, phrase: str
) -> None:
    got, message = rejected([remove(key, merge)])
    assert got == code and phrase in message


def test_a_merge_that_would_leave_a_wall_inside_the_room_is_refused() -> None:
    m = fixture("generated-house")
    code, message = rejected([remove("wall:L0:kitchen|laundry", True, "generated-house")], m)
    assert code == "ROOM_MERGE_WALL_INSIDE" and "W1-16" in message
    # Removing the other wall first makes the merge possible.
    out = check(
        [
            remove("wall:L0:laundry|kitchen", False, "generated-house"),
            remove("wall:L0:kitchen|laundry", True, "generated-house"),
        ],
        m,
    )
    assert out.model is not None, out.rejection


def test_remove_element_still_refuses_walls() -> None:
    code, message = rejected([RemoveElement(element_id=el(fixture(), "wall:G-I1").id)])
    assert code == "ELEMENT_NOT_REMOVABLE" and "remove_wall" in message


def test_a_merge_that_breaks_a_mandatory_requirement_is_refused() -> None:
    base = fixture("generated-house")
    raw = spec01().model_dump(mode="json")
    raw["requirements"] = [
        {"path": "/rooms/2/target_area_m2", "priority": "must", "origin": "form"}
    ]  # dining: 18 m²
    strict = BuildingSpecification.model_validate(raw)
    op = remove("wall:L0:hall_0|dining", True, "generated-house")
    out = check([op], base, strict)
    assert out.rejection is not None
    assert any(i.code == "EDIT_REQUIREMENT_UNMET" for i in out.rejection.issues)
    # Opening the wall without merging keeps the dining room: allowed.
    assert check([remove("wall:L0:hall_0|dining", False, "generated-house")], base, strict).model


def test_a_merge_of_a_requested_room_is_reported() -> None:
    base = fixture("generated-house")
    out = check([remove("wall:L0:hall_0|dining", True, "generated-house")], base, spec01())
    assert out.model is not None, out.rejection
    assert any(i.code == "EDIT_PROGRAM_CHANGED" and "merged" in i.message for i in out.warnings)


def test_a_locked_wall_cannot_be_removed() -> None:
    m = fixture()
    wall = el(m, "wall:G-I1")
    locked = m.model_copy(
        update={
            "elements": [
                e.model_copy(update={"locked": True}) if e.id == wall.id else e for e in m.elements
            ]
        }
    )
    code, _ = rejected([RemoveWall(wall_id=wall.id)], locked)
    assert code == "ELEMENT_LOCKED"


@cache
def _interior_walls(name: str) -> list[uuid.UUID]:
    return [
        e.id
        for e in fixture(name).elements
        if isinstance(e, Wall) and e.properties.wall_kind != "exterior"
    ]


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    name=st.sampled_from(["demo-house", "generated-house", "generated-l-house"]),
    pick=st.integers(min_value=0, max_value=10_000),
    merge=st.booleans(),
)
def test_every_wall_removal_is_refused_or_consistent(name: str, pick: int, merge: bool) -> None:
    base = fixture(name)
    walls = _interior_walls(name)
    target = walls[pick % len(walls)]
    wall = next(e for e in base.elements if e.id == target)
    assert isinstance(wall, Wall)
    rooms = rooms_along(base, wall)
    out = check([RemoveWall(wall_id=target, merge_rooms=merge)], base)
    if out.model is None:
        assert out.rejection is not None and out.rejection.message
        return
    assert not errors(validate_model(out.model, material_ids=MATERIALS))
    ids = {e.id for e in out.model.elements}
    assert target not in ids
    for e in out.model.elements:
        assert all(r.target_id in ids for r in e.relationships), e.name
    kept = [e for e in out.model.elements if isinstance(e, Room)]
    expected = len([e for e in base.elements if isinstance(e, Room)]) - (1 if merge else 0)
    assert len(kept) == expected
    if merge:
        survivor = next(r for r in rooms if r.id in ids)
        merged = next(r for r in kept if r.id == survivor.id)
        assert merged.dimensions.area == pytest.approx(
            sum(r.dimensions.area for r in rooms), abs=0.05
        )


# --- rename_room -------------------------------------------------------------------------------


def test_renaming_a_room_keeps_its_identity_and_geometry() -> None:
    base = fixture()
    before = room(base, "room:bedroom3")
    out = check([RenameRoom(room_id=before.id, name="  Guest   bedroom ")])
    assert out.model is not None, out.rejection
    after = room(out.model, "room:bedroom3")
    assert after.name == "Guest bedroom"
    assert after.model_copy(update={"name": before.name, "origin": before.origin}) == before
    assert out.changed_ids == [before.id]


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Bedroom 3", "NO_CHANGE"),
        ("   ", "ROOM_NAME_INVALID"),
        ("Bed\x07room", "ROOM_NAME_INVALID"),
        ("master BEDROOM", "ROOM_NAME_TAKEN"),
    ],
)
def test_invalid_names_are_refused(name: str, code: str) -> None:
    got, _ = rejected([RenameRoom(room_id=room(fixture(), "room:bedroom3").id, name=name)])
    assert got == code


def test_overlong_names_are_refused_as_input() -> None:
    with pytest.raises(ValueError):
        RenameRoom(room_id=uuid.uuid4(), name="x" * 121)


def test_rename_and_undo_by_replaying_fewer_operations() -> None:
    base = fixture()
    r = room(base, "room:storage")
    ops: list[Operation] = [RenameRoom(room_id=r.id, name="Home office")]
    assert room(apply_operations(base, ops), "room:storage").name == "Home office"
    assert room(apply_operations(base, ops[:0]), "room:storage").name == "Storage"


# --- set_room_type -----------------------------------------------------------------------------


def test_a_bedroom_becomes_a_study_with_its_zone() -> None:
    base = fixture()
    before = room(base, "room:bedroom3")
    out = check([SetRoomType(room_id=before.id, room_type=RoomType.STUDY)])
    assert out.model is not None, out.rejection
    after = room(out.model, "room:bedroom3")
    assert after.properties.room_type == RoomType.STUDY
    assert after.properties.zone == Zone.PRIVATE
    assert after.id == before.id and after.name == before.name
    assert after.properties.boundary == before.properties.boundary


def test_storage_becomes_a_laundry() -> None:
    out = check(
        [SetRoomType(room_id=room(fixture(), "room:storage").id, room_type=RoomType.LAUNDRY)]
    )
    assert out.model is not None, out.rejection
    after = room(out.model, "room:storage")
    assert after.properties.room_type == "laundry" and after.properties.zone == Zone.SERVICE


def test_the_rules_of_the_new_type_apply() -> None:
    # Bedroom 3 is 3.40 m wide; a living room needs the profile's 3.6 m.
    out = check(
        [SetRoomType(room_id=room(fixture(), "room:bedroom3").id, room_type=RoomType.LIVING)]
    )
    assert out.rejection is not None
    assert any(i.code == "RULE_ROOM_WIDTH" for i in out.rejection.issues)
    # A laundry without a window cannot become a bedroom (habitable rooms need daylight).
    m = fixture("generated-house")
    laundry = room(m, "room:laundry")
    out = check([SetRoomType(room_id=laundry.id, room_type=RoomType.BEDROOM)], m)
    assert out.rejection is not None
    codes = {i.code for i in out.rejection.issues}
    assert "HABITABLE_ROOM_WITHOUT_WINDOW" in codes


@pytest.mark.parametrize(
    ("key", "to", "code"),
    [
        ("room:bedroom3", RoomType.BEDROOM, "NO_CHANGE"),
        ("room:bedroom3", RoomType.GARAGE, "ROOM_TYPE_UNSUPPORTED"),
        ("room:bedroom3", RoomType.BALCONY, "ROOM_TYPE_UNSUPPORTED"),
        ("room:staircase", RoomType.STORAGE, "ROOM_TYPE_UNSUPPORTED"),
    ],
)
def test_unsupported_type_changes_are_refused(key: str, to: RoomType, code: str) -> None:
    got, message = rejected([SetRoomType(room_id=room(fixture(), key).id, room_type=to)])
    assert got == code and message


def test_retyping_a_room_the_spec_requires_is_refused() -> None:
    base = fixture("generated-house")
    study = room(base, "room:study")
    op = SetRoomType(room_id=study.id, room_type=RoomType.STORAGE)
    loose = check([op], base, spec01())
    assert loose.model is not None, loose.rejection
    assert any(i.code == "EDIT_PROGRAM_CHANGED" for i in loose.warnings)
    raw = spec01().model_dump(mode="json")
    raw["requirements"] = [
        {"path": "/rooms/3/target_area_m2", "priority": "must", "origin": "form"}
    ]
    strict = check([op], base, BuildingSpecification.model_validate(raw))
    assert strict.rejection is not None
    assert any(
        i.code == "EDIT_REQUIREMENT_UNMET" and "requires" in i.message
        for i in strict.rejection.issues
    )


def test_room_zones_match_the_layout_program() -> None:
    for t in RoomType:
        if t not in {
            RoomType.ENTRANCE,
            RoomType.HALL,
            RoomType.CORRIDOR,
            RoomType.STAIRCASE,
            RoomType.BALCONY,
            RoomType.TERRACE,
        }:
            assert room_zone(t) == zone_of(t), t


def test_a_refused_type_change_leaves_the_model_unchanged() -> None:
    base = fixture()
    snapshot = base.model_dump(mode="json")
    with pytest.raises(BatchRejected):
        apply_operations(
            base,
            [SetRoomType(room_id=room(base, "room:staircase").id, room_type=RoomType.HALL)],
        )
    assert base.model_dump(mode="json") == snapshot
