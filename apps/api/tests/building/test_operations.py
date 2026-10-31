"""Typed operations: move_wall (Phase 3.6 D2, docs/building-model.md §5)."""

import json
import math
import uuid
from functools import cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.building.elements import Door, Furniture, Room, Wall, Window
from app.modules.building.geometry import signed_area, to_absolute, wall_axis, wall_frame
from app.modules.building.migrations import load_model
from app.modules.building.model import BuildingModel
from app.modules.building.operations import (
    BatchRejected,
    MoveWall,
    OperationRejected,
    apply_operations,
)
from app.modules.building.validation import errors, validate_model
from app.modules.editing.evaluate import blocking, evaluate_edits
from app.shared.data_files import material_ids, rules_profile

DATA = Path(__file__).resolve().parents[4] / "data"
FIXTURES = ["demo-house", "generated-house", "generated-l-house", "generated-t-house"]
PROFILE = rules_profile(DATA, "generic-residential@1")
MATERIALS = material_ids(DATA)


@cache
def fixture(name: str) -> BuildingModel:
    raw = json.loads((DATA / "fixtures" / f"{name}.model.json").read_text(encoding="utf-8"))
    return load_model(raw)


def by_key(model: BuildingModel, key: str) -> Wall:
    wall = next(e for e in model.elements if e.semantic_key == key)
    assert isinstance(wall, Wall)
    return wall


def interior_walls(model: BuildingModel) -> list[Wall]:
    return [
        e for e in model.elements if isinstance(e, Wall) and e.properties.wall_kind == "interior"
    ]


def room_area(model: BuildingModel, level: uuid.UUID | None) -> float:
    """Exact floor area of the rooms of a level (stored areas are rounded to 0.01 m² each)."""
    return sum(
        abs(signed_area(to_absolute(e.properties.boundary, e.position, e.rotation)))
        for e in model.elements
        if isinstance(e, Room) and e.level_id == level
    )


def opening_center(model: BuildingModel, el: Door | Window) -> tuple[float, float]:
    host_id = next(r.target_id for r in el.relationships if r.kind == "hosted_by")
    host = next(e for e in model.elements if e.id == host_id)
    assert isinstance(host, Wall)
    return wall_frame(host).at(el.position.x + el.dimensions.width / 2)


def move(model: BuildingModel, wall: Wall, offset: float) -> BuildingModel:
    return apply_operations(model, [MoveWall(wall_id=wall.id, offset_m=offset)])


# --- a known good move ---------------------------------------------------------------------


def test_moving_a_wall_moves_it_and_reshapes_the_rooms_beside_it() -> None:
    base = fixture("demo-house")
    wall = by_key(base, "wall:G-I1")
    out = move(base, wall, 0.5)
    moved = by_key(out, "wall:G-I1")
    (ax, ay), (bx, by) = wall_axis(wall)
    (cx, cy), (dx, dy) = wall_axis(moved)
    nx, ny = -math.sin(wall.rotation.z), math.cos(wall.rotation.z)
    assert (cx - ax, cy - ay) == pytest.approx((0.5 * nx, 0.5 * ny), abs=1e-6)
    assert (dx - bx, dy - by) == pytest.approx((0.5 * nx, 0.5 * ny), abs=1e-6)
    assert moved.dimensions.length == wall.dimensions.length
    assert moved.origin == "user"
    # The rooms on either side trade exactly the strip the wall swept.
    changed = {
        e.id: e.dimensions.area
        for e in out.elements
        if isinstance(e, Room)
        and e.dimensions.area != next(b for b in base.elements if b.id == e.id).dimensions.area  # type: ignore[union-attr]
    }
    assert len(changed) >= 2
    assert room_area(out, wall.level_id) == pytest.approx(room_area(base, wall.level_id), abs=1e-3)
    assert errors(validate_model(out, material_ids=MATERIALS)) == []
    assert out.metadata.source == "operations"


def test_the_editing_check_accepts_it_and_reports_what_changed() -> None:
    base = fixture("demo-house")
    wall = by_key(base, "wall:G-I1")
    outcome = evaluate_edits(base, [MoveWall(wall_id=wall.id, offset_m=0.2)], PROFILE, MATERIALS)
    assert outcome.model is not None and outcome.rejection is None
    assert wall.id in outcome.changed_ids
    assert not any(blocking(i) for i in outcome.warnings)


def test_moving_back_restores_the_plan() -> None:
    base = fixture("demo-house")
    wall = by_key(base, "wall:G-I1")
    there_and_back = apply_operations(
        base, [MoveWall(wall_id=wall.id, offset_m=0.4), MoveWall(wall_id=wall.id, offset_m=-0.4)]
    )

    def plan(m: BuildingModel) -> tuple[object, ...]:
        walls = sorted((str(e.id), wall_axis(e)) for e in m.elements if isinstance(e, Wall))
        rooms = sorted(
            (
                str(e.id),
                e.dimensions.area,
                tuple(to_absolute(e.properties.boundary, e.position, e.rotation)),
            )
            for e in m.elements
            if isinstance(e, Room)
        )
        return (tuple(walls), tuple(rooms))

    assert plan(there_and_back) == plan(base)


def test_replaying_the_same_operations_gives_the_same_model() -> None:
    base = fixture("generated-l-house")
    ops = [MoveWall(wall_id=w.id, offset_m=0.2) for w in interior_walls(base)[:1]]
    assert (
        apply_operations(base, ops).model_dump_json()
        == apply_operations(base, ops).model_dump_json()
    )


# --- refusals ------------------------------------------------------------------------------


def test_exterior_walls_are_refused_with_a_reason() -> None:
    base = fixture("demo-house")
    ext = next(
        e for e in base.elements if isinstance(e, Wall) and e.properties.wall_kind == "exterior"
    )
    with pytest.raises(BatchRejected) as err:
        move(base, ext, 0.5)
    assert err.value.code == "EXTERIOR_WALL_FIXED" and err.value.index == 0
    assert "exterior wall" in err.value.message and ext.name in err.value.message


def test_unknown_wall_and_zero_move_are_refused() -> None:
    base = fixture("demo-house")
    with pytest.raises(OperationRejected) as err:
        apply_operations(base, [MoveWall(wall_id=uuid.uuid4(), offset_m=0.5)])
    assert err.value.code == "WALL_NOT_FOUND"
    with pytest.raises(OperationRejected) as err:
        move(base, by_key(base, "wall:G-I1"), 0.0004)
    assert err.value.code == "NO_CHANGE"


def test_moving_into_a_room_until_it_closes_is_refused() -> None:
    base = fixture("demo-house")
    with pytest.raises(OperationRejected) as err:
        move(base, by_key(base, "wall:G-I1"), 15.0)
    assert err.value.code in {"ROOM_WOULD_COLLAPSE", "WALL_WOULD_VANISH", "WALL_END_UNSUPPORTED"}


def test_an_edit_that_breaks_a_rule_is_rejected_with_the_finding() -> None:
    base = fixture("demo-house")
    wall = by_key(base, "wall:G-I6")
    outcome = evaluate_edits(base, [MoveWall(wall_id=wall.id, offset_m=0.5)], PROFILE, MATERIALS)
    assert outcome.model is None and outcome.rejection is not None
    assert outcome.rejection.code == "EDIT_INVALID"
    assert outcome.rejection.issues and all(blocking(i) for i in outcome.rejection.issues)
    assert outcome.rejection.message.startswith("This change would make the design invalid:")


def test_squeezing_a_corridor_below_the_corridor_minimum_is_rejected() -> None:
    """W-G05 bounds the 1.2 m deep demo corridor; the profile sets the corridor minimum."""
    base = fixture("demo-house")
    wall = by_key(base, "wall:G-I1")
    minimum = PROFILE.corridors.min_width_m
    room_left = round(1.2 - minimum, 3)
    ok = evaluate_edits(base, [MoveWall(wall_id=wall.id, offset_m=room_left)], PROFILE, MATERIALS)
    assert ok.model is not None  # leaves exactly the minimum
    bad = evaluate_edits(
        base, [MoveWall(wall_id=wall.id, offset_m=room_left + 0.1)], PROFILE, MATERIALS
    )
    assert bad.model is None and bad.rejection is not None
    pinch = [i for i in bad.rejection.issues if i.code == "EDIT_CIRCULATION_PINCH"]
    assert pinch and pinch[0].rule_ref == PROFILE.rule_ref("corridors.min_width_m")
    assert "Corridor" in bad.rejection.message and f"{minimum} m" in bad.rejection.message


def test_a_refused_operation_names_its_index_in_the_batch() -> None:
    base = fixture("demo-house")
    good = MoveWall(wall_id=by_key(base, "wall:G-I1").id, offset_m=0.2)
    ext = next(
        e for e in base.elements if isinstance(e, Wall) and e.properties.wall_kind == "exterior"
    )
    with pytest.raises(BatchRejected) as err:
        apply_operations(base, [good, MoveWall(wall_id=ext.id, offset_m=0.2)])
    assert err.value.index == 1


# --- invariants over many moves ----------------------------------------------------------------


def _all_moves() -> list[tuple[str, str]]:
    return [(name, w.semantic_key) for name in FIXTURES for w in interior_walls(fixture(name))]


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    case=st.sampled_from(_all_moves()),
    offset=st.sampled_from([-0.9, -0.5, -0.25, -0.05, 0.05, 0.25, 0.5, 0.9]),
)
def test_every_move_is_either_refused_or_consistent(case: tuple[str, str], offset: float) -> None:
    base = fixture(case[0])
    wall = by_key(base, case[1])
    outcome = evaluate_edits(base, [MoveWall(wall_id=wall.id, offset_m=offset)], PROFILE, MATERIALS)
    if outcome.model is None:
        assert outcome.rejection is not None and outcome.rejection.message
        return
    out = outcome.model
    # Valid as a model, no new blocking findings (the check already ran them; re-check errors).
    assert errors(validate_model(out, material_ids=MATERIALS)) == []
    # Moving an interior wall only redistributes floor area between rooms.
    assert room_area(out, wall.level_id) == pytest.approx(room_area(base, wall.level_id), abs=1e-3)
    # Openings stay where they are in the plan, except those in the moved wall, which move with it.
    nx, ny = -math.sin(wall.rotation.z), math.cos(wall.rotation.z)
    hosted_by_wall = {
        e.id
        for e in base.elements
        if any(r.kind == "hosted_by" and r.target_id == wall.id for r in e.relationships)
    }
    new = {e.id: e for e in out.elements}
    for el in base.elements:
        if isinstance(el, Door | Window):
            before = opening_center(base, el)
            after = opening_center(out, new[el.id])  # type: ignore[arg-type]
            shift = (offset * nx, offset * ny) if el.id in hosted_by_wall else (0.0, 0.0)
            assert after == pytest.approx((before[0] + shift[0], before[1] + shift[1]), abs=2e-3)
    # Nothing outside the wall's level changes.
    old = {e.id: e for e in base.elements}
    for el in out.elements:
        if el.level_id != wall.level_id:
            assert el == old[el.id]


def test_a_wall_that_leaves_a_straight_line_gets_a_step() -> None:
    """Across the fixtures, some valid move takes a wall out of a straight line of walls; the
    step is closed by a short wall exactly as long as the move."""
    for name, key in _all_moves():
        base = fixture(name)
        wall = by_key(base, key)
        for offset in (-0.3, 0.3):
            outcome = evaluate_edits(
                base, [MoveWall(wall_id=wall.id, offset_m=offset)], PROFILE, MATERIALS
            )
            if outcome.model is None:
                continue
            jogs = [
                e
                for e in outcome.model.elements
                if isinstance(e, Wall) and ":jog:" in e.semantic_key
            ]
            if jogs:
                assert all(j.dimensions.length == pytest.approx(abs(offset)) for j in jogs)
                assert all(j.semantic_key.startswith(wall.semantic_key) for j in jogs)
                return
    pytest.skip("no fixture wall continues a straight line in a movable way")


def test_furniture_against_the_wall_moves_with_it() -> None:
    for name, key in _all_moves():
        base = fixture(name)
        wall = by_key(base, key)
        outcome = evaluate_edits(
            base, [MoveWall(wall_id=wall.id, offset_m=0.25)], PROFILE, MATERIALS
        )
        if outcome.model is None:
            continue
        old = {e.id: e for e in base.elements}
        moved = [
            e
            for e in outcome.model.elements
            if isinstance(e, Furniture) and e.position != old[e.id].position
        ]
        if moved:
            nx, ny = -math.sin(wall.rotation.z), math.cos(wall.rotation.z)
            for item in moved:
                was = old[item.id]
                assert (
                    item.position.x - was.position.x,
                    item.position.y - was.position.y,
                ) == pytest.approx((0.25 * nx, 0.25 * ny), abs=1e-6)
            return
    pytest.fail("no valid move touched any furniture")
