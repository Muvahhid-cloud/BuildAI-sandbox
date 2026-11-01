"""D2.5 envelope editing: exterior wall moves, wall thickness, finish and height
(docs/building-model.md §5.6).

The facade moves on every storey, the slabs, roof and attached elements follow; shapes that
cannot follow are refused with a reason. The editing service holds every accepted result to the
standard of a generated model (validate_model + rules.model_checks).
"""

import json
import math
import uuid
from functools import cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.building.elements import Railing, Roof, Room, Slab, Wall, Window
from app.modules.building.enums import RoofType, SlabKind, WallKind
from app.modules.building.geometry import is_axis_aligned_rectangle, to_absolute, wall_axis
from app.modules.building.migrations import load_model
from app.modules.building.model import BuildingModel
from app.modules.building.operations import (
    BatchRejected,
    MoveWall,
    Operation,
    ResizeRoom,
    SetWallFinish,
    SetWallHeight,
    SetWallThickness,
    apply_operations,
    room_sides,
)
from app.modules.building.operations.envelope import facade_of
from app.modules.building.validation import errors, validate_model
from app.modules.editing.evaluate import evaluate_edits, issue_key, model_issues
from app.modules.rules.model_checks import check_model
from app.shared.data_files import material_ids, rules_profile
from tests.layout.helpers import reference

DATA = Path(__file__).resolve().parents[4] / "data"
FIXTURES = ["demo-house", "generated-house", "generated-l-house", "generated-t-house"]
PROFILE = rules_profile(DATA, "generic-residential@1")
MATERIALS = material_ids(DATA)


@cache
def fixture(name: str) -> BuildingModel:
    raw = json.loads((DATA / "fixtures" / f"{name}.model.json").read_text("utf-8"))
    return load_model(raw)


def by_key(model: BuildingModel, key: str) -> Wall:
    el = next(e for e in model.elements if e.semantic_key == key)
    assert isinstance(el, Wall)
    return el


def outline(el: Slab | Roof) -> list[tuple[float, float]]:
    return to_absolute(el.properties.outline, el.position, el.rotation)


def accepted(model: BuildingModel, ops: list[Operation]) -> BuildingModel:
    outcome = evaluate_edits(model, ops, PROFILE, MATERIALS)
    assert outcome.rejection is None, outcome.rejection
    assert outcome.model is not None
    return outcome.model


def refused(model: BuildingModel, ops: list[Operation]) -> tuple[str, str]:
    outcome = evaluate_edits(model, ops, PROFILE, MATERIALS)
    assert outcome.rejection is not None and outcome.model is None
    return outcome.rejection.code, outcome.rejection.message


# --- facade moves ---------------------------------------------------------------------------


def test_moving_a_facade_out_moves_it_on_every_storey_with_slabs_and_roof() -> None:
    base = fixture("generated-house")
    east = by_key(base, "wall:ext:L0:E")  # runs north; + = west (inwards)
    edited = accepted(base, [MoveWall(wall_id=east.id, offset_m=-1.0)])
    for key in ("wall:ext:L0:E", "wall:ext:L1:E"):
        assert by_key(edited, key).position.x == pytest.approx(by_key(base, key).position.x + 1)
    for key in ("wall:ext:L0:S", "wall:ext:L1:S", "wall:ext:L0:N", "wall:ext:L1:N"):
        assert by_key(edited, key).dimensions.length == pytest.approx(
            by_key(base, key).dimensions.length + 1
        )
    for key in ("slab:ground", "slab:L1", "roof:main"):
        before = next(e for e in base.elements if e.semantic_key == key)
        after = next(e for e in edited.elements if e.semantic_key == key)
        assert isinstance(before, Slab | Roof) and isinstance(after, Slab | Roof)
        assert max(x for x, _ in outline(after)) == pytest.approx(
            max(x for x, _ in outline(before)) + 1
        )
    # Openings stay host-relative: the moved facade's windows keep their offsets.
    for w in (e for e in base.elements if isinstance(e, Window)):
        host = next(r.target_id for r in w.relationships if r.kind == "hosted_by")
        if host == east.id:
            moved = next(e for e in edited.elements if e.id == w.id)
            assert moved.position == w.position

    # The building got 1 m wider: indoor floor area grew on both storeys.
    def floor(model: BuildingModel) -> float:
        return sum(
            r.dimensions.area
            for r in model.elements
            if isinstance(r, Room) and r.properties.zone != "exterior"
        )

    assert floor(edited) > floor(base) + 2 * 12.0
    assert errors(validate_model(edited, material_ids=MATERIALS)) == []
    assert check_model(edited, PROFILE) == []


def test_a_pitched_roof_follows_with_its_overhang_and_stays_a_rectangle() -> None:
    base = fixture("demo-house")  # hip roof
    east = by_key(base, "wall:G-E")
    edited = accepted(base, [MoveWall(wall_id=east.id, offset_m=-0.8)])
    roof = next(e for e in edited.elements if isinstance(e, Roof))
    before = next(e for e in base.elements if isinstance(e, Roof))
    assert roof.properties.roof_type == RoofType.HIP
    assert is_axis_aligned_rectangle(outline(roof))
    assert max(x for x, _ in outline(roof)) == pytest.approx(
        max(x for x, _ in outline(before)) + 0.8
    )
    assert roof.dimensions.overhang == before.dimensions.overhang


def test_a_balcony_and_its_railings_move_with_their_facade() -> None:
    base = fixture("generated-house")
    north = by_key(base, "wall:ext:L0:N")  # runs west; + = south (inwards)
    edited = accepted(base, [MoveWall(wall_id=north.id, offset_m=-1.2)])
    for el in base.elements:
        if el.semantic_key.startswith(("room:balcony", "slab:balcony", "railing:balcony")):
            assert isinstance(el, Room | Slab | Railing)
            after = next(e for e in edited.elements if e.id == el.id)
            assert after.position.y == pytest.approx(el.position.y + 1.2)
            assert after.position.x == pytest.approx(el.position.x)


def test_the_entrance_canopy_follows_its_facade() -> None:
    # Reference spec 09 has no garage, so its entrance facade can move as one.
    base = reference("09-small-two-storey-120.spec.json").model
    canopy = next(
        e for e in base.elements if isinstance(e, Slab) and e.properties.slab_kind == "canopy"
    )
    entrance = next(
        e for e in base.elements if e.type == "door" and e.properties.door_kind == "entrance"
    )
    host = next(r.target_id for r in entrance.relationships if r.kind == "hosted_by")
    wall = next(e for e in base.elements if e.id == host)
    assert isinstance(wall, Wall)
    edited = accepted(base, [MoveWall(wall_id=wall.id, offset_m=-0.5)])
    moved = next(e for e in edited.elements if e.id == canopy.id)
    assert math.dist(
        (moved.position.x, moved.position.y), (canopy.position.x, canopy.position.y)
    ) == pytest.approx(0.5)
    assert moved.position.z == canopy.position.z
    assert not [
        i
        for i in validate_model(edited, material_ids=MATERIALS)
        if i.code == "CANOPY_PLACEMENT_INVALID"
    ]


def test_resizing_a_room_at_its_exterior_side_moves_the_facade() -> None:
    base = fixture("demo-house")
    east = by_key(base, "wall:G-E")
    room, edge = next(
        (r, s.index)
        for r in base.elements
        if isinstance(r, Room)
        for s in room_sides(base, r)
        if [w.id for w in s.walls] == [east.id]
    )
    edited = accepted(base, [ResizeRoom(room_id=room.id, edge=edge, delta_m=0.5)])
    grown = next(e for e in edited.elements if e.id == room.id)
    assert isinstance(grown, Room)
    assert grown.dimensions.area > room.dimensions.area
    assert by_key(edited, "wall:F-E").position.x == pytest.approx(
        by_key(base, "wall:F-E").position.x + 0.5
    )


@pytest.mark.parametrize(
    ("name", "key", "offset", "code", "words"),
    [
        ("generated-house", "wall:ext:L0:S", 0.5, "FACADE_CONTINUES", "continues the facade"),
        ("generated-house", "wall:ext:L0:W", 0.5, "VOLUME_ATTACHED", "another volume"),
        ("generated-house", "wall:garage:N", 0.5, "VOLUME_ATTACHED", "another volume"),
        ("demo-house", "wall:G-S", 0.6, "FACADE_CUTS_STAIR", "stair opening"),
        ("generated-l-house", "wall:ext:L0:N", 0.6, "ROOF_CANNOT_FORM", "rectangular"),
    ],
)
def test_facades_that_cannot_follow_are_refused_with_the_reason(
    name: str, key: str, offset: float, code: str, words: str
) -> None:
    base = fixture(name)
    wall = by_key(base, key)
    with pytest.raises(BatchRejected) as err:
        apply_operations(base, [MoveWall(wall_id=wall.id, offset_m=offset)])
    assert err.value.code == code and words in err.value.message


def test_a_room_below_the_rules_minimum_refuses_the_move() -> None:
    base = fixture("generated-l-house")
    code, message = refused(
        base, [MoveWall(wall_id=by_key(base, "wall:ext:L0:wing:N").id, offset_m=0.6)]
    )
    assert code == "EDIT_INVALID" and "below" in message


def test_facade_edits_are_deterministic() -> None:
    base = fixture("generated-house")
    ops: list[Operation] = [
        MoveWall(wall_id=by_key(base, "wall:ext:L0:E").id, offset_m=-0.75),
        MoveWall(wall_id=by_key(base, "wall:ext:L0:N").id, offset_m=-0.5),
        SetWallThickness(wall_id=by_key(base, "wall:ext:L1:E").id, thickness_m=0.4),
    ]
    a = apply_operations(base, ops).model_dump(mode="json")
    b = apply_operations(fixture("generated-house"), ops).model_dump(mode="json")
    assert a == b


# --- wall properties ------------------------------------------------------------------------


def test_exterior_thickness_changes_the_facade_on_every_storey_and_its_envelope() -> None:
    base = fixture("generated-house")
    east = by_key(base, "wall:ext:L0:E")
    edited = accepted(base, [SetWallThickness(wall_id=east.id, thickness_m=0.45)])
    for key in ("wall:ext:L0:E", "wall:ext:L1:E"):
        w = by_key(edited, key)
        assert w.dimensions.thickness == 0.45
        assert w.position == by_key(base, key).position  # the axis stays
    roof = next(e for e in edited.elements if e.semantic_key == "roof:main")
    assert isinstance(roof, Roof)
    assert max(x for x, _ in outline(roof)) == pytest.approx(10.6 + 0.225)


def test_interior_thickness_keeps_room_boundaries_on_the_axis() -> None:
    base = fixture("demo-house")
    wall = by_key(base, "wall:G-I1")
    edited = accepted(base, [SetWallThickness(wall_id=wall.id, thickness_m=0.2)])
    assert by_key(edited, "wall:G-I1").dimensions.thickness == 0.2
    rooms = {e.id: e for e in base.elements if isinstance(e, Room)}
    for el in edited.elements:
        if isinstance(el, Room):
            assert el.properties.boundary == rooms[el.id].properties.boundary


@pytest.mark.parametrize(
    ("key", "thickness", "rule"),
    [
        ("wall:G-E", 0.15, "walls.exterior_thickness_m"),
        ("wall:G-E", 0.7, "walls.exterior_thickness_m"),
        ("wall:G-I1", 0.05, "walls.interior_thickness_m"),
        ("wall:G-I1", 0.4, "walls.interior_thickness_m"),
    ],
)
def test_thickness_outside_the_profile_range_is_refused(
    key: str, thickness: float, rule: str
) -> None:
    base = fixture("demo-house")
    outcome = evaluate_edits(
        base,
        [SetWallThickness(wall_id=by_key(base, key).id, thickness_m=thickness)],
        PROFILE,
        MATERIALS,
    )
    assert outcome.rejection is not None and outcome.rejection.code == "EDIT_INVALID"
    assert any((i.rule_ref or "").endswith(rule) for i in outcome.rejection.issues)
    assert "thick" in outcome.rejection.message


def test_a_balcony_facade_keeps_its_thickness() -> None:
    base = fixture("generated-house")
    with pytest.raises(BatchRejected) as err:
        apply_operations(
            base, [SetWallThickness(wall_id=by_key(base, "wall:ext:L0:N").id, thickness_m=0.4)]
        )
    assert err.value.code == "BALCONY_ATTACHED"


def test_a_wall_finish_comes_from_the_material_library() -> None:
    base = fixture("generated-house")
    east = by_key(base, "wall:ext:L0:E")
    edited = accepted(base, [SetWallFinish(wall_id=east.id, face="right", material_id="brick")])
    after = by_key(edited, "wall:ext:L0:E")
    assert after.properties.finish_right_id == "brick"
    assert after.properties.finish_left_id == east.properties.finish_left_id
    code, message = refused(
        base, [SetWallFinish(wall_id=east.id, face="both", material_id="unobtainium")]
    )
    assert code == "EDIT_INVALID" and "unobtainium" in message


def test_wall_height_only_for_walls_that_carry_nothing() -> None:
    base = fixture("demo-house")
    interior = next(
        w
        for w in base.elements
        if isinstance(w, Wall)
        and w.properties.wall_kind == WallKind.INTERIOR
        and not any(
            r.target_id == w.id and r.kind == "hosted_by"
            for e in base.elements
            for r in e.relationships
        )
    )
    edited = accepted(base, [SetWallHeight(wall_id=interior.id, height_m=1.2)])
    assert by_key(edited, interior.semantic_key).dimensions.height == 1.2
    cases: list[tuple[Wall, float, str]] = [
        (by_key(base, "wall:G-E"), 2.0, "WALL_HEIGHT_FIXED"),
        (interior, 3.5, "WALL_HEIGHT_EXCEEDS_STOREY"),
    ]
    with_door = next(
        w
        for w in base.elements
        if isinstance(w, Wall)
        and w.properties.wall_kind == WallKind.INTERIOR
        and any(
            r.target_id == w.id and r.kind == "hosted_by" and e.type == "door"
            for e in base.elements
            for r in e.relationships
        )
    )
    cases.append((with_door, 1.5, "OPENING_ABOVE_WALL_TOP"))
    for wall, height, code in cases:
        with pytest.raises(BatchRejected) as err:
            apply_operations(base, [SetWallHeight(wall_id=wall.id, height_m=height)])
        assert err.value.code == code
    outcome = evaluate_edits(
        base, [SetWallHeight(wall_id=interior.id, height_m=0.5)], PROFILE, MATERIALS
    )
    assert outcome.rejection is not None
    assert any((i.rule_ref or "").endswith("walls.min_height_m") for i in outcome.rejection.issues)


# --- property: refused or consistent --------------------------------------------------------


def _exterior(model: BuildingModel) -> list[Wall]:
    return sorted(
        (e for e in model.elements if isinstance(e, Wall) and e.properties.wall_kind == "exterior"),
        key=lambda w: w.semantic_key,
    )


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    name=st.sampled_from(FIXTURES),
    pick=st.integers(min_value=0, max_value=63),
    kind=st.sampled_from(["move", "thickness"]),
    steps=st.integers(min_value=-40, max_value=40),
)
def test_every_exterior_edit_is_refused_or_consistent(
    name: str, pick: int, kind: str, steps: int
) -> None:
    base = fixture(name)
    walls = _exterior(base)
    wall = walls[pick % len(walls)]
    op: Operation
    if kind == "move":
        if steps == 0:
            return
        op = MoveWall(wall_id=wall.id, offset_m=steps * 0.05)
    else:
        op = SetWallThickness(wall_id=wall.id, thickness_m=round(0.36 + steps * 0.008, 3))
        if abs(op.thickness_m - wall.dimensions.thickness) < 0.001:
            return
    outcome = evaluate_edits(base, [op], PROFILE, MATERIALS)
    if outcome.rejection is not None:
        assert outcome.model is None and outcome.rejection.message
        return
    edited = outcome.model
    assert edited is not None
    # Accepted: as good as a generated model (nothing new against the base).
    old = {issue_key(i) for i in model_issues(base, PROFILE, MATERIALS)}
    new = [
        i for i in errors(validate_model(edited, material_ids=MATERIALS)) if issue_key(i) not in old
    ]
    assert new == []
    assert [i for i in check_model(edited, PROFILE) if issue_key(i) not in old] == []
    # Storeys stay aligned: every wall of the facade lies on the same axis with one thickness.
    ids = {w.id for w in facade_of(base, wall).walls}
    stack = [e for e in edited.elements if isinstance(e, Wall) and e.id in ids]
    assert (
        len(
            {
                wall_axis(w)[0][0] if abs(math.sin(w.rotation.z)) > 0.5 else wall_axis(w)[0][1]
                for w in stack
            }
        )
        == 1
    )
    assert len({round(w.dimensions.thickness, 3) for w in stack if isinstance(w, Wall)}) == 1
    # Pitched roofs stay rectangles.
    for roof in (e for e in edited.elements if isinstance(e, Roof)):
        if roof.properties.roof_type != RoofType.FLAT:
            assert is_axis_aligned_rectangle(outline(roof))
    # Canopies stay valid (the model checks above include slab.canopy).
    assert all(
        e.properties.slab_kind != SlabKind.CANOPY or e.level_id is not None
        for e in edited.elements
        if isinstance(e, Slab)
    )


def test_unknown_wall_ids_are_refused() -> None:
    base = fixture("demo-house")
    for op in (
        SetWallThickness(wall_id=uuid.uuid4(), thickness_m=0.3),
        SetWallFinish(wall_id=uuid.uuid4(), face="left", material_id="brick"),
        SetWallHeight(wall_id=uuid.uuid4(), height_m=2.0),
    ):
        with pytest.raises(BatchRejected) as err:
            apply_operations(base, [op])
        assert err.value.code == "WALL_NOT_FOUND"
