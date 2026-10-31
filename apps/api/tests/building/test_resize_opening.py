"""`resize_opening` (Phase 3.6 D2.4, docs/building-model.md §5.4): new width, height and (windows)
sill of a door or window, judged by the editing check like every edit."""

import json
import uuid
from functools import cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.building.elements import Door, Element, Wall, Window
from app.modules.building.enums import DoorKind
from app.modules.building.migrations import load_model
from app.modules.building.model import BuildingModel
from app.modules.building.operations import (
    BatchRejected,
    MoveOpening,
    Operation,
    ResizeOpening,
    apply_operations,
)
from app.modules.building.operations.openings import door_rooms, host_of
from app.modules.building.types import DoorTypeParams, TypeSnapshot
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


def opening(model: BuildingModel, key: str) -> Door | Window:
    o = el(model, key)
    assert isinstance(o, Door | Window)
    return o


def check(ops: list[Operation], model: BuildingModel | None = None) -> EditOutcome:
    return evaluate_edits(model or fixture(), ops, PROFILE, MATERIALS)


def resize(key: str, width: float, height: float, **kw: float) -> ResizeOpening:
    return ResizeOpening(
        opening_id=opening(fixture(), key).id, width_m=width, height_m=height, **kw
    )


def rejected(ops: list[Operation]) -> tuple[str, str]:
    out = check(ops)
    assert out.model is None and out.rejection is not None
    return out.rejection.code, out.rejection.message


def test_a_window_gets_a_new_width_height_and_sill_keeping_its_identity() -> None:
    base = fixture()
    before = opening(base, "window:bed3_s")  # 1.6 x 1.4 at 0.9 in F-S, offset 0.9
    out = check([resize("window:bed3_s", 1.8, 1.5, sill_m=1.0)])
    assert out.model is not None, out.rejection
    after = opening(out.model, "window:bed3_s")
    assert after.id == before.id and after.name == before.name and after.type == "window"
    assert (after.dimensions.width, after.dimensions.height) == (1.8, 1.5)
    assert after.position.z == 1.0
    assert after.position.x == 0.8  # the centre stays at 1.7 m
    assert host_of(out.model, after) == host_of(base, before)
    assert isinstance(after, Window) and isinstance(before, Window)
    assert after.properties.window_kind == before.properties.window_kind
    assert after.material_id == before.material_id and after.origin == "user"
    assert out.changed_ids == [before.id]
    assert not errors(validate_model(out.model, material_ids=MATERIALS))


def test_the_example_window_from_0_8_by_1_0_to_1_8_by_1_4() -> None:
    # A window added at 0.8 x 1.0 m, then made 1.8 x 1.4 m without deleting it.
    from app.modules.building.operations import AddOpening

    m = fixture()
    west = next(e for e in m.elements if e.semantic_key == "wall:G-W")
    added = apply_operations(
        m,
        [
            AddOpening(
                kind="window",
                host_wall_id=west.id,
                offset_m=7.0,
                width_m=0.8,
                height_m=1.0,
                sill_m=0.9,
            )
        ],
    )
    new = next(e for e in added.elements if e.semantic_key == "window:edit:1")
    out = check([ResizeOpening(opening_id=new.id, width_m=1.8, height_m=1.4)], added)
    assert out.model is not None, out.rejection
    w = opening(out.model, "window:edit:1")
    assert w.id == new.id and (w.dimensions.width, w.dimensions.height) == (1.8, 1.4)
    assert w.position.x == 6.5 and w.position.z == 0.9  # centre kept; sill kept when not given


def test_a_door_is_widened_and_made_taller_with_its_rooms_kept() -> None:
    base = fixture()
    before = opening(base, "door:bedroom3")  # 0.9 x 2.1 in F-I3 (3.4 m long), offset 1.2
    out = check([resize("door:bedroom3", 1.0, 2.2)])
    assert out.model is not None, out.rejection
    after = opening(out.model, "door:bedroom3")
    assert isinstance(after, Door)
    assert after.id == before.id and after.properties == before.properties
    assert (after.dimensions.width, after.dimensions.height) == (1.0, 2.2)
    assert after.dimensions.thickness == before.dimensions.thickness
    assert after.position.x == 1.15 and after.position.z == 0.0
    connects = {r.target_id for r in after.relationships if r.kind == "connects"}
    assert connects == {r.target_id for r in before.relationships if r.kind == "connects"}
    wall = host_of(out.model, after)
    assert wall is not None
    assert connects == set(door_rooms(out.model, wall, (1.15, 2.15)))


def test_an_explicit_offset_moves_the_start_edge() -> None:
    out = check([resize("door:bedroom3", 1.2, 2.1, offset_m=1.0)])
    assert out.model is not None, out.rejection
    assert opening(out.model, "door:bedroom3").position.x == 1.0


def test_a_wider_window_keeps_its_pane_width() -> None:
    before = opening(fixture(), "window:kitchen_e")  # 1.8 m, two panes of 0.9 m
    assert isinstance(before, Window) and before.properties.mullions == 1
    out = check([resize("window:kitchen_e", 2.7, 1.1, offset_m=1.0)])
    assert out.model is not None, out.rejection
    after = opening(out.model, "window:kitchen_e")
    assert isinstance(after, Window) and after.properties.mullions == 2


def test_a_resized_opening_near_the_wall_end_shifts_inside_the_wall() -> None:
    # door:ent_corr: 0.9 m at 1.2 in a 3.4 m wall; 2.2 m centred would reach 3.75 m.
    out = apply_operations(fixture(), [resize("door:ent_corr", 2.2, 2.1)])
    door = opening(out, "door:ent_corr")
    assert door.position.x + door.dimensions.width <= 3.4


@pytest.mark.parametrize(
    ("op", "code"),
    [
        (lambda: resize("window:bed3_s", 1.6, 1.4), "NO_CHANGE"),
        (lambda: resize("door:bedroom3", 0.9, 2.1, sill_m=0.2), "INVALID_HOST_POSITION"),
        (lambda: resize("window:bed3_s", 1.6, 2.2, sill_m=0.9), "OPENING_TOO_TALL"),
        (lambda: resize("door:bedroom3", 0.9, 2.9), "OPENING_TOO_TALL"),
        (lambda: resize("window:bed3_s", 1.6, 1.4, offset_m=11.0), "OPENING_OUTSIDE_WALL"),
        (lambda: resize("window:ent", 4.0, 1.3), "OPENINGS_OVERLAP"),
        (lambda: resize("door:ent_corr", 3.6, 2.1), "OPENING_OUTSIDE_WALL"),
    ],
)
def test_impossible_sizes_are_refused_by_the_operation(op: object, code: str) -> None:
    got, message = rejected([op()])  # type: ignore[operator]
    assert got == code and message


def test_a_window_cannot_cross_a_joining_wall() -> None:
    # window:bed3_s in F-S; the corridor wall F-I1 / F-I3 joins F-S at x = 3.4.
    code, _ = rejected([resize("window:bed3_s", 3.2, 1.4, offset_m=0.9)])
    assert code in {"OPENING_IN_WALL_JUNCTION", "OPENINGS_OVERLAP"}


def test_sizes_below_the_profile_minimums_are_refused_with_the_rule() -> None:
    out = check([resize("door:bedroom3", 0.6, 2.1)])
    assert out.rejection is not None and out.rejection.code == "EDIT_INVALID"
    rules = {i.rule_ref for i in out.rejection.issues}
    assert any(r and "doors.interior" in r for r in rules), out.rejection.issues
    out = check([resize("window:bed3_s", 0.3, 1.4)])
    assert out.rejection is not None
    assert any(i.code == "RULE_WINDOW_SIZE" for i in out.rejection.issues)


def test_a_low_sill_on_an_upper_floor_needs_a_guard() -> None:
    out = check([resize("window:bed3_s", 1.6, 1.4, sill_m=0.5)])
    assert out.rejection is not None
    assert any(i.code == "RULE_WINDOW_GUARD" for i in out.rejection.issues)


def test_a_resize_keeps_the_clearance_to_corners() -> None:
    # door:ent_corr sits 1.2 m from the start of a 3.4 m wall; 2.0 m wide + offset 1.38 leaves
    # 0.02 m of wall at the end: below the profile's clearance.
    assert PROFILE.openings is not None
    out = check([resize("door:ent_corr", 2.0, 2.1, offset_m=1.38)])
    assert out.rejection is not None
    assert any(i.code == "EDIT_OPENING_CLEARANCE" for i in out.rejection.issues)


def test_shrinking_the_last_window_below_the_daylight_ratio_is_refused() -> None:
    out = check([resize("window:study_n", 0.6, 0.6), resize("window:study_e", 0.6, 0.6)])
    assert out.rejection is not None
    assert any(i.code == "RULE_GLAZING_RATIO" for i in out.rejection.issues)


def test_a_refused_resize_leaves_the_model_unchanged() -> None:
    base = fixture()
    snapshot = base.model_dump(mode="json")
    with pytest.raises(BatchRejected):
        apply_operations(base, [resize("door:bedroom3", 0.9, 2.9)])
    assert base.model_dump(mode="json") == snapshot


def test_resize_then_move_and_back_replays_identically() -> None:
    ops: list[Operation] = [
        resize("door:bedroom3", 1.0, 2.1),
        MoveOpening(opening_id=opening(fixture(), "door:bedroom3").id, offset_m=1.3),
    ]
    a, b = check(ops), check(ops)
    assert a.model is not None and a.model == b.model


def test_a_typed_door_resized_against_its_type_becomes_a_custom_door() -> None:
    m = fixture()
    door = opening(m, "door:bedroom3")
    assert isinstance(door, Door)
    t = TypeSnapshot(
        id="type.door.test_interior",
        family="family.door.interior",
        name="Test interior door",
        params=DoorTypeParams(
            door_kind=DoorKind.INTERIOR,
            height=2.1,
            thickness=door.dimensions.thickness,
            material_id=door.material_id,
            frame_material_id=door.properties.frame_material_id,
        ),
        assembly_id=None,
        source="test-types@1",
        content_sha256="0" * 64,
    )
    typed = m.model_copy(
        update={
            "types": [*m.types, t],
            "elements": [
                e.model_copy(update={"type_ref": t.id}) if e.id == door.id else e
                for e in m.elements
            ],
        }
    )
    wider = apply_operations(typed, [ResizeOpening(opening_id=door.id, width_m=1.0, height_m=2.1)])
    assert opening(wider, "door:bedroom3").type_ref == t.id  # the type does not fix the width
    taller = apply_operations(typed, [ResizeOpening(opening_id=door.id, width_m=0.9, height_m=2.2)])
    assert opening(taller, "door:bedroom3").type_ref is None


@cache
def _openings(name: str) -> list[uuid.UUID]:
    return [e.id for e in fixture(name).elements if isinstance(e, Door | Window)]


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    name=st.sampled_from(["demo-house", "generated-house"]),
    pick=st.integers(min_value=0, max_value=10_000),
    width=st.floats(min_value=0.3, max_value=4.0),
    height=st.floats(min_value=0.3, max_value=3.0),
)
def test_every_resize_is_refused_or_consistent(
    name: str, pick: int, width: float, height: float
) -> None:
    ids = _openings(name)
    target = ids[pick % len(ids)]
    out = check([ResizeOpening(opening_id=target, width_m=width, height_m=height)], fixture(name))
    if out.model is None:
        assert out.rejection is not None and out.rejection.message
        return
    assert not errors(validate_model(out.model, material_ids=MATERIALS))
    resized = next(e for e in out.model.elements if e.id == target)
    assert isinstance(resized, Door | Window)
    assert resized.dimensions.width == round(width, 3)
    assert set(out.changed_ids) == {target}
    wall = host_of(out.model, resized)
    assert isinstance(wall, Wall)
    assert resized.position.x >= 0
    assert resized.position.x + resized.dimensions.width <= wall.dimensions.length + 1e-6
