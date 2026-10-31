"""Door and window operations (Phase 3.6 D2.3, docs/building-model.md §5.3): move_opening,
add_opening and remove_element, and how the editing check judges them."""

import json
import uuid
from functools import cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.building.elements import Door, Element, Wall, Window
from app.modules.building.migrations import load_model
from app.modules.building.model import BuildingModel
from app.modules.building.operations import (
    AddOpening,
    BatchRejected,
    MoveOpening,
    MoveWall,
    Operation,
    RemoveElement,
    apply_operations,
)
from app.modules.building.operations.openings import door_rooms, host_of, hosted
from app.modules.building.validation import errors, validate_model
from app.modules.editing.evaluate import EditOutcome, evaluate_edits
from app.shared.data_files import material_ids, rules_profile

DATA = Path(__file__).resolve().parents[4] / "data"
FIXTURES = ["demo-house", "generated-house", "generated-l-house", "generated-t-house"]
PROFILE = rules_profile(DATA, "generic-residential@1")
MATERIALS = material_ids(DATA)


@cache
def fixture(name: str = "demo-house") -> BuildingModel:
    raw = json.loads((DATA / "fixtures" / f"{name}.model.json").read_text(encoding="utf-8"))
    return load_model(raw)


def el(model: BuildingModel, key: str) -> Element:
    return next(e for e in model.elements if e.semantic_key == key)


def opening(model: BuildingModel, key: str) -> Door | Window:
    o = el(model, key)
    assert isinstance(o, Door | Window)
    return o


def wall(model: BuildingModel, key: str) -> Wall:
    w = el(model, key)
    assert isinstance(w, Wall)
    return w


def check(ops: list[Operation], model: BuildingModel | None = None) -> EditOutcome:
    return evaluate_edits(model or fixture(), ops, PROFILE, MATERIALS)


def move(key: str, offset: float, to: str | None = None) -> MoveOpening:
    m = fixture()
    return MoveOpening(
        opening_id=opening(m, key).id,
        offset_m=offset,
        host_wall_id=wall(m, to).id if to else None,
    )


def add(kind: str, on: str, offset: float, width: float, height: float, **kw: object) -> AddOpening:
    return AddOpening.model_validate(
        {
            "kind": kind,
            "host_wall_id": str(wall(fixture(), on).id),
            "offset_m": offset,
            "width_m": width,
            "height_m": height,
            **kw,
        }
    )


def rejected(ops: list[Operation]) -> tuple[str, str]:
    out = check(ops)
    assert out.model is None and out.rejection is not None
    return out.rejection.code, out.rejection.message


def untouched(before: BuildingModel, after: BuildingModel, changed: set[uuid.UUID]) -> None:
    old = {e.id: e for e in before.elements}
    for e in after.elements:
        if e.id not in changed:
            assert e == old[e.id], e.name


# --- move_opening -------------------------------------------------------------------------------


def test_sliding_a_door_along_its_wall_keeps_its_identity_and_rooms() -> None:
    base = fixture()
    door = opening(base, "door:ent_corr")
    out = check([move("door:ent_corr", 2.0)])
    assert out.model is not None, out.rejection
    moved = opening(out.model, "door:ent_corr")
    assert moved.id == door.id and moved.type == door.type and moved.name == door.name
    assert moved.dimensions == door.dimensions and moved.properties == door.properties
    assert moved.position.x == 2.0 and moved.origin == "user"
    assert host_of(out.model, moved) == host_of(base, door)
    assert {r.target_id for r in moved.relationships if r.kind == "connects"} == {
        r.target_id for r in door.relationships if r.kind == "connects"
    }
    assert out.changed_ids == [door.id]
    untouched(base, out.model, {door.id})


def test_moving_a_door_to_another_wall_reconnects_it_to_the_rooms_there() -> None:
    out = check([move("door:storage", 1.0, "wall:G-I2")])
    assert out.model is not None, out.rejection
    moved = opening(out.model, "door:storage")
    target = wall(out.model, "wall:G-I2")
    assert host_of(out.model, moved) == target
    connects = {r.target_id for r in moved.relationships if r.kind == "connects"}
    assert connects == set(door_rooms(out.model, target, (1.0, 1.8))) and len(connects) == 2
    assert not errors(validate_model(out.model, material_ids=MATERIALS))


def test_a_window_moves_to_another_exterior_wall() -> None:
    out = check([move("window:storage", 4.0, "wall:G-E")])
    assert out.model is not None, out.rejection
    assert host_of(out.model, opening(out.model, "window:storage")) == wall(out.model, "wall:G-E")


def test_positions_outside_the_wall_are_refused() -> None:
    code, message = rejected([move("door:ent_corr", 2.8)])
    assert code == "OPENING_OUTSIDE_WALL" and "3.40 m long" in message


def test_overlapping_another_opening_is_refused() -> None:
    code, message = rejected([move("window:ent", 1.0)])
    assert code == "OPENINGS_OVERLAP" and "Front door" in message


def test_cutting_into_a_joining_wall_is_refused() -> None:
    code, message = rejected([move("window:stair_g", 4.3)])
    assert code == "OPENING_IN_WALL_JUNCTION" and "4.74-4.86" in message


def test_the_clearance_to_corners_and_other_openings_comes_from_the_rules_profile() -> None:
    assert PROFILE.openings is not None and PROFILE.openings.min_clearance_m == 0.1
    # The joining wall's body ends at 0.15 m: 0.05 m of wall is too little, 0.10 m is enough.
    out = check([move("door:ent_corr", 0.2)])
    assert out.rejection is not None and out.rejection.code == "EDIT_INVALID"
    issue = out.rejection.issues[0]
    assert issue.code == "EDIT_OPENING_CLEARANCE"
    assert issue.rule_ref == "generic-residential@1:openings.min_clearance_m"
    assert issue.measure is not None and issue.measure.actual == pytest.approx(0.05)
    assert check([move("door:ent_corr", 0.25)]).model is not None
    # Between two openings of a wall.
    out = check([move("window:ent", 0.55)])
    assert out.rejection is not None and "from Front door" in out.rejection.message


def test_a_wall_move_does_not_apply_the_clearance_to_openings_it_does_not_place() -> None:
    """D2.1 behaviour is unchanged: only openings an edit places are held to the margin."""
    base = fixture()
    out = check([MoveWall(wall_id=wall(base, "wall:G-I1").id, offset_m=0.2)])
    assert out.model is not None, out.rejection


@pytest.mark.parametrize(
    ("key", "to", "code"),
    [
        ("window:ent", "wall:G-I1", "OPENING_WALL_INCOMPATIBLE"),  # windows: exterior walls
        ("door:front", "wall:G-I1", "OPENING_WALL_INCOMPATIBLE"),  # entrance: exterior walls
        ("door:garden", "wall:G-I6", "OPENING_WALL_INCOMPATIBLE"),  # sliding: exterior walls
        ("door:ent_corr", "wall:F-I1", "OPENING_LEVEL"),  # another floor
    ],
)
def test_incompatible_walls_are_refused(key: str, to: str, code: str) -> None:
    assert rejected([move(key, 1.0, to)])[0] == code


def test_hosts_that_are_not_walls_are_refused() -> None:
    m = fixture()
    room = el(m, "room:entrance")
    op = MoveOpening(opening_id=opening(m, "door:ent_corr").id, host_wall_id=room.id, offset_m=1)
    assert rejected([op])[0] == "HOST_INCOMPATIBLE"
    ghost = MoveOpening(opening_id=uuid.uuid4(), offset_m=1)
    assert rejected([ghost])[0] == "OPENING_NOT_FOUND"
    assert rejected([move("door:ent_corr", 1.2)])[0] == "NO_CHANGE"


def test_a_move_that_cuts_a_room_off_is_refused() -> None:
    code, message = rejected([move("door:bath_g", 1.0, "wall:G-I6")])
    assert code == "EDIT_INVALID" and "Bathroom cannot be reached" in message


def test_a_locked_opening_cannot_be_moved_or_removed() -> None:
    m = fixture()
    door = opening(m, "door:ent_corr")
    locked = m.model_copy(
        update={
            "elements": [
                e.model_copy(update={"locked": True}) if e.id == door.id else e for e in m.elements
            ]
        }
    )
    for op in (
        MoveOpening(opening_id=door.id, offset_m=2.0),
        RemoveElement(element_id=door.id),
    ):
        with pytest.raises(BatchRejected) as err:
            apply_operations(locked, [op])
        assert err.value.code == "ELEMENT_LOCKED"


def test_moving_back_restores_the_model() -> None:
    base = fixture()
    there = apply_operations(base, [move("door:ent_corr", 2.0), move("door:ent_corr", 1.2)])
    assert opening(there, "door:ent_corr") == opening(base, "door:ent_corr").model_copy(
        update={"origin": "user"}
    )


# --- add_opening --------------------------------------------------------------------------------


def test_adding_a_door_puts_it_in_the_wall_with_its_rooms() -> None:
    base = fixture()
    target = wall(base, "wall:G-I2")
    out = check([add("door", "wall:G-I2", 1.0, 0.9, 2.1)])
    assert out.model is not None, out.rejection
    new = [e for e in out.model.elements if e.id not in {b.id for b in base.elements}]
    assert len(new) == 1 and isinstance(new[0], Door)
    door = new[0]
    assert door.semantic_key == "door:edit:1" and door.name == "New door 1"
    assert door.id == uuid.uuid5(base.id, "edit:door:edit:1")
    assert door.properties.door_kind == "interior" and door.origin == "user"
    assert (door.position.x, door.position.z, door.dimensions.width) == (1.0, 0.0, 0.9)
    assert door.dimensions.thickness <= target.dimensions.thickness
    assert door.material_id == "wood"  # like the model's other interior doors
    assert host_of(out.model, door) == target
    assert len([r for r in door.relationships if r.kind == "connects"]) == 2
    assert out.changed_ids == [door.id]
    untouched(base, out.model, {door.id})
    assert out.model.elements.index(door) == base.elements.index(target) + 1


def test_adding_a_window_and_an_entrance_door_to_exterior_walls() -> None:
    out = check([add("window", "wall:G-W", 6.0, 1.2, 1.4, sill_m=0.9)])
    assert out.model is not None, out.rejection
    win = el(out.model, "window:edit:1")
    assert isinstance(win, Window) and win.position.z == 0.9
    assert win.properties.window_kind == "casement"
    out = check([add("door", "wall:G-E", 3.5, 1.0, 2.2, door_kind="entrance")])
    assert out.model is not None, out.rejection
    door = el(out.model, "door:edit:1")
    assert isinstance(door, Door) and door.material_id == "wood_dark"  # like the front door
    assert len([r for r in door.relationships if r.kind == "connects"]) == 1


def test_two_added_openings_get_distinct_ids_and_replay_identically() -> None:
    ops: list[Operation] = [
        add("door", "wall:G-I2", 0.5, 0.8, 2.1),
        add("door", "wall:G-I2", 3.0, 0.8, 2.1),
    ]
    a, b = apply_operations(fixture(), ops), apply_operations(fixture(), ops)
    assert a == b
    keys = [e.semantic_key for e in a.elements if e.semantic_key.startswith("door:edit:")]
    assert keys == ["door:edit:1", "door:edit:2"]


@pytest.mark.parametrize(
    ("op", "code"),
    [
        (
            lambda: add("window", "wall:G-I2", 1.0, 1.2, 1.4, sill_m=0.9),
            "OPENING_WALL_INCOMPATIBLE",
        ),
        (lambda: add("door", "wall:G-I1", 1.0, 0.9, 2.1), "OPENINGS_OVERLAP"),
        (lambda: add("door", "wall:G-I2", 4.2, 0.9, 2.1), "OPENING_OUTSIDE_WALL"),
        (lambda: add("door", "wall:G-I2", 2.0, 0.9, 2.1), "OPENING_IN_WALL_JUNCTION"),
        (lambda: add("door", "wall:G-I2", 1.0, 0.9, 3.0), "OPENING_TOO_TALL"),
        (lambda: add("door", "wall:G-I2", 1.0, 0.9, 2.0, sill_m=0.3), "INVALID_HOST_POSITION"),
    ],
)
def test_impossible_openings_are_refused(op: object, code: str) -> None:
    assert callable(op)
    assert rejected([op()])[0] == code


def test_openings_below_the_profile_minimums_are_refused_with_the_rule() -> None:
    out = check([add("window", "wall:G-W", 6.0, 0.4, 1.4, sill_m=0.9)])
    assert out.rejection is not None
    assert out.rejection.issues[0].rule_ref == "generic-residential@1:windows.min_width_m"
    out = check([add("door", "wall:G-I2", 0.5, 1.0, 2.1), move("door:storage", 0.6, "wall:G-I2")])
    assert out.rejection is not None and out.rejection.index == 1  # overlaps the new door


def test_an_added_door_near_a_corner_needs_the_clearance() -> None:
    out = check([add("door", "wall:G-I2", 0.2, 0.9, 2.1)])  # joining wall body ends at 0.15
    assert out.rejection is not None
    assert out.rejection.issues[0].code == "EDIT_OPENING_CLEARANCE"


# --- remove_element -----------------------------------------------------------------------------


def test_removing_a_window_closes_the_wall_and_keeps_everything_else() -> None:
    base = fixture()
    win = opening(base, "window:ent")
    out = check([RemoveElement(element_id=win.id)])
    assert out.model is not None, out.rejection
    assert win.id not in {e.id for e in out.model.elements}
    assert out.changed_ids == [win.id]
    untouched(base, out.model, set())
    assert len(out.model.elements) == len(base.elements) - 1
    assert win not in hosted(out.model, wall(out.model, "wall:G-S"))


def test_removing_a_rooms_only_door_is_refused() -> None:
    code, message = rejected([RemoveElement(element_id=opening(fixture(), "door:storage").id)])
    assert code == "EDIT_INVALID" and "Storage cannot be reached" in message


def test_removing_the_entrance_door_is_refused() -> None:
    code, message = rejected([RemoveElement(element_id=opening(fixture(), "door:front").id)])
    assert code == "EDIT_INVALID" and "no entrance door" in message


def test_removing_the_last_windows_of_a_bedroom_is_refused() -> None:
    m = fixture()
    ops: list[Operation] = [
        RemoveElement(element_id=opening(m, "window:bed3_s").id),
        RemoveElement(element_id=opening(m, "window:bed3_w").id),
    ]
    code, message = rejected(ops)
    assert code == "EDIT_INVALID" and "Bedroom 3" in message
    assert check(ops[:1]).model is not None  # one window left is fine


def test_only_doors_and_windows_can_be_removed() -> None:
    m = fixture()
    assert rejected([RemoveElement(element_id=wall(m, "wall:G-I1").id)])[0] == (
        "ELEMENT_NOT_REMOVABLE"
    )
    assert rejected([RemoveElement(element_id=uuid.uuid4())])[0] == "ELEMENT_NOT_FOUND"


def test_remove_then_add_back_is_a_consistent_model() -> None:
    m = fixture()
    win = opening(m, "window:ent")
    out = check(
        [
            RemoveElement(element_id=win.id),
            add("window", "wall:G-S", win.position.x, 0.6, 0.6, sill_m=win.position.z),
        ]
    )
    assert out.model is not None, out.rejection


# --- property: every opening move is refused or consistent --------------------------------------


@cache
def _cases(name: str) -> list[tuple[uuid.UUID, uuid.UUID]]:
    m = fixture(name)
    out = []
    for o in m.elements:
        if not isinstance(o, Door | Window):
            continue
        host = host_of(m, o)
        assert host is not None
        walls = [w for w in m.elements if isinstance(w, Wall) and w.level_id == o.level_id]
        out += [(o.id, w.id) for w in walls]
    return out


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    name=st.sampled_from(FIXTURES),
    pick=st.integers(min_value=0, max_value=10_000),
    offset=st.floats(min_value=0, max_value=12, allow_nan=False).map(lambda v: round(v, 2)),
)
def test_every_opening_move_is_refused_or_consistent(name: str, pick: int, offset: float) -> None:
    base = fixture(name)
    cases = _cases(name)
    opening_id, wall_id = cases[pick % len(cases)]
    op = MoveOpening(opening_id=opening_id, host_wall_id=wall_id, offset_m=offset)
    out = evaluate_edits(base, [op], PROFILE, MATERIALS)
    if out.model is None:
        assert out.rejection is not None and out.rejection.message
        return
    moved = next(e for e in out.model.elements if e.id == opening_id)
    assert isinstance(moved, Door | Window)
    host = host_of(out.model, moved)
    assert host is not None and host.id == wall_id
    assert moved.position.x >= 0 and moved.position.x + moved.dimensions.width <= (
        host.dimensions.length + 1e-6
    )
    assert not errors(validate_model(out.model, material_ids=MATERIALS))
    if isinstance(moved, Door):
        span = (moved.position.x, moved.position.x + moved.dimensions.width)
        assert {r.target_id for r in moved.relationships if r.kind == "connects"} == set(
            door_rooms(out.model, host, span)
        )
    untouched(base, out.model, {opening_id})
