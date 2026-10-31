"""resize_room (Phase 3.6 D2.2, docs/building-model.md §5.2): a room side moves by moving the
interior walls it runs along, so neighbours, openings and validation follow the wall move."""

import json
import math
from functools import cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.building.elements import Door, Room, Wall, Window
from app.modules.building.geometry import signed_area, to_absolute, wall_frame
from app.modules.building.migrations import load_model
from app.modules.building.model import BuildingModel
from app.modules.building.operations import (
    BatchRejected,
    ResizeRoom,
    apply_operations,
    room_sides,
)
from app.modules.building.specification import BuildingSpecification
from app.modules.building.validation import errors, validate_model
from app.modules.editing.evaluate import EditOutcome, evaluate_edits
from app.shared.data_files import material_ids, rules_profile

DATA = Path(__file__).resolve().parents[4] / "data"
PROFILE = rules_profile(DATA, "generic-residential@1")
MATERIALS = material_ids(DATA)
FIXTURES = ["demo-house", "generated-house", "generated-l-house", "generated-t-house"]
SPECS = {
    "generated-house": "01-family-house-280",
    "generated-l-house": "11-l-shaped-bungalow-160",
    "generated-t-house": "12-t-shaped-bungalow-170",
}


@cache
def fixture(name: str) -> BuildingModel:
    raw = json.loads((DATA / "fixtures" / f"{name}.model.json").read_text(encoding="utf-8"))
    return load_model(raw)


def spec_of(name: str) -> BuildingSpecification | None:
    if name not in SPECS:
        return None
    path = DATA / "fixtures" / "specs" / f"{SPECS[name]}.spec.json"
    return BuildingSpecification.model_validate_json(path.read_text(encoding="utf-8"))


def room(model: BuildingModel, name: str) -> Room:
    found = next(e for e in model.elements if isinstance(e, Room) and e.name == name)
    return found


def area(r: Room) -> float:
    return abs(signed_area(to_absolute(r.properties.boundary, r.position, r.rotation)))


def by_id(model: BuildingModel) -> dict[object, object]:
    return {e.id: e for e in model.elements}


def resize(name: str, r: Room, edge: int, delta: float) -> EditOutcome:
    return evaluate_edits(
        fixture(name),
        [ResizeRoom(room_id=r.id, edge=edge, delta_m=delta)],
        PROFILE,
        MATERIALS,
        spec=spec_of(name),
    )


@cache
def movable_side(name: str) -> tuple[str, int]:
    """A room side of the fixture that can both grow and shrink by 0.2 m, along one wall
    shared with exactly one other room (first in model order: deterministic)."""
    base = fixture(name)
    for r in (e for e in base.elements if isinstance(e, Room)):
        for side in room_sides(base, r):
            if len(side.walls) != 1:
                continue
            shared = [x for x in side.walls[0].relationships if x.kind == "bounds"]
            if len(shared) != 2:
                continue
            if all(resize(name, r, side.index, d).model is not None for d in (-0.2, 0.2)):
                return r.name, side.index
    raise AssertionError(f"no movable side in {name}")


# --- growing and shrinking ----------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
@pytest.mark.parametrize("delta", [0.2, -0.2])
def test_a_room_grows_and_shrinks_and_its_neighbour_gives_and_takes(
    name: str, delta: float
) -> None:
    base = fixture(name)
    room_name, edge = movable_side(name)
    r = room(base, room_name)
    side = room_sides(base, r)[edge]
    wall = side.walls[0]
    neighbour_id = next(
        x.target_id for x in wall.relationships if x.kind == "bounds" and x.target_id != r.id
    )
    outcome = resize(name, r, edge, delta)
    assert outcome.model is not None, outcome.rejection
    new = by_id(outcome.model)
    after = new[r.id]
    neighbour_before, neighbour_after = by_id(base)[neighbour_id], new[neighbour_id]
    assert (
        isinstance(after, Room)
        and isinstance(neighbour_before, Room)
        and isinstance(neighbour_after, Room)
    )
    gained = area(after) - area(r)
    # The room changes by the swept strip where the side runs along the wall: side length x delta
    # when the wall spans the side (it may be longer, then the neighbour side also moves).
    assert gained == pytest.approx(side.length * delta, abs=1e-3)
    assert area(neighbour_after) - area(neighbour_before) == pytest.approx(-gained, abs=1e-3) or (
        # the wall is longer than this side: other rooms along it share the change
        sum(
            area(e)
            for e in outcome.model.elements
            if isinstance(e, Room) and e.level_id == r.level_id
        )
        == pytest.approx(
            sum(area(e) for e in base.elements if isinstance(e, Room) and e.level_id == r.level_id),
            abs=1e-3,
        )
    )
    # Stored areas and perimeters match the new outlines; the model is valid.
    for el in outcome.model.elements:
        if isinstance(el, Room):
            assert el.dimensions.area == pytest.approx(area(el), abs=0.006)
    assert errors(validate_model(outcome.model, material_ids=MATERIALS)) == []
    # The shared wall moved by delta outwards and still bounds both rooms.
    moved = new[wall.id]
    assert isinstance(moved, Wall)
    shift = (moved.position.x - wall.position.x, moved.position.y - wall.position.y)
    assert shift == pytest.approx((delta * side.outward[0], delta * side.outward[1]), abs=1e-6)
    assert {x.target_id for x in moved.relationships if x.kind == "bounds"} >= {r.id, neighbour_id}


def test_a_resize_then_the_opposite_resize_restores_the_areas() -> None:
    base = fixture("demo-house")
    room_name, edge = movable_side("demo-house")
    r = room(base, room_name)
    out = apply_operations(
        base,
        [
            ResizeRoom(room_id=r.id, edge=edge, delta_m=0.2),
            ResizeRoom(room_id=r.id, edge=edge, delta_m=-0.2),
        ],
    )
    for el in out.elements:
        if isinstance(el, Room):
            assert el.dimensions.area == by_id(base)[el.id].dimensions.area  # type: ignore[attr-defined]


# --- refusals ------------------------------------------------------------------------------------


def _first_side(name: str, kind: str) -> tuple[Room, int]:
    base = fixture(name)
    for r in (e for e in base.elements if isinstance(e, Room)):
        for side in room_sides(base, r):
            if (
                kind == "exterior"
                and side.walls
                and side.walls[0].properties.wall_kind == "exterior"
            ):
                return r, side.index
            if kind == "open" and not side.walls:
                return r, side.index
            if kind == "partly" and side.walls and side.covered < side.length - 1e-3:
                return r, side.index
    raise AssertionError(kind)


@pytest.mark.parametrize(
    ("kind", "code", "words"),
    [
        ("exterior", "EXTERIOR_WALL_FIXED", "exterior wall"),
        ("open", "ROOM_SIDE_OPEN", "open boundary"),
        ("partly", "ROOM_SIDE_PARTLY_OPEN", "only partly a wall"),
    ],
)
def test_sides_that_cannot_move_are_refused_naming_the_room(
    kind: str, code: str, words: str
) -> None:
    r, edge = _first_side("demo-house", kind)
    outcome = resize("demo-house", r, edge, 0.3)
    assert outcome.model is None and outcome.rejection is not None
    assert outcome.rejection.code == code
    assert r.name in outcome.rejection.message and words in outcome.rejection.message


def test_unknown_room_or_side_is_refused() -> None:
    base = fixture("demo-house")
    r = room(base, "Kitchen")
    with pytest.raises(BatchRejected) as err:
        apply_operations(base, [ResizeRoom(room_id=r.id, edge=99, delta_m=0.3)])
    assert err.value.code == "ROOM_SIDE_NOT_FOUND"
    wall = next(e for e in base.elements if isinstance(e, Wall))
    with pytest.raises(BatchRejected) as err:
        apply_operations(base, [ResizeRoom(room_id=wall.id, edge=0, delta_m=0.3)])
    assert err.value.code == "ROOM_NOT_FOUND"


def _first_refusal(name: str, issue_code: str) -> tuple[Room, int, float]:
    base = fixture(name)
    for r in (e for e in base.elements if isinstance(e, Room)):
        for side in room_sides(base, r):
            if not side.walls or side.walls[0].properties.wall_kind == "exterior":
                continue
            for d in (-0.3, 0.3, -0.6, 0.6):
                o = resize(name, r, side.index, d)
                if o.rejection and any(i.code == issue_code for i in o.rejection.issues):
                    return r, side.index, d
    raise AssertionError(issue_code)


@pytest.mark.parametrize(
    ("name", "issue_code"),
    [
        ("generated-house", "RULE_ROOM_WIDTH"),  # a room below its minimum clear width
        ("demo-house", "EDIT_CIRCULATION_PINCH"),  # a corridor below the corridor minimum
        ("generated-house", "OPENING_OUTSIDE_WALL"),  # a door would end up off its wall
        ("demo-house", "OPENING_IN_WALL_JUNCTION"),  # a window would end up in a junction
    ],
)
def test_resizes_that_break_rules_or_openings_are_rejected(name: str, issue_code: str) -> None:
    r, edge, d = _first_refusal(name, issue_code)
    outcome = resize(name, r, edge, d)
    assert outcome.model is None and outcome.rejection is not None
    assert outcome.rejection.code == "EDIT_INVALID"
    assert outcome.rejection.message.startswith("This change would make the design invalid:")
    blocking_codes = {i.code for i in outcome.rejection.issues}
    assert issue_code in blocking_codes


def test_a_rejected_resize_leaves_the_model_untouched() -> None:
    base = fixture("demo-house")
    before = base.model_dump_json()
    r, edge, d = _first_refusal("demo-house", "EDIT_CIRCULATION_PINCH")
    outcome = resize("demo-house", r, edge, d)
    assert outcome.model is None
    assert base.model_dump_json() == before  # operations are pure


def test_doors_and_windows_in_the_moved_wall_move_with_the_side() -> None:
    for name in FIXTURES:
        base = fixture(name)
        for r in (e for e in base.elements if isinstance(e, Room)):
            for side in room_sides(base, r):
                if len(side.walls) != 1 or side.walls[0].properties.wall_kind == "exterior":
                    continue
                wall = side.walls[0]
                hosted = [
                    e
                    for e in base.elements
                    if isinstance(e, Door | Window)
                    and any(
                        x.kind == "hosted_by" and x.target_id == wall.id for x in e.relationships
                    )
                ]
                if not hosted:
                    continue
                outcome = resize(name, r, side.index, 0.2)
                if outcome.model is None:
                    continue
                new = by_id(outcome.model)
                moved_wall = new[wall.id]
                assert isinstance(moved_wall, Wall)
                for el in hosted:
                    after = new[el.id]
                    assert isinstance(after, Door | Window)
                    assert after.position.x == el.position.x  # same place on its wall
                    c0 = wall_frame(wall).at(el.position.x + el.dimensions.width / 2)
                    c1 = wall_frame(moved_wall).at(after.position.x + after.dimensions.width / 2)
                    assert (c1[0] - c0[0], c1[1] - c0[1]) == pytest.approx(
                        (0.2 * side.outward[0], 0.2 * side.outward[1]), abs=1e-6
                    )
                return
    pytest.fail("no valid resize moved a wall with openings")


def test_a_resize_that_breaks_a_mandatory_requirement_is_rejected() -> None:
    """The living room of reference spec 01 gets a MUST area target; shrinking it below the
    permitted range is refused, while the base model met it."""
    base = fixture("generated-house")
    spec = spec_of("generated-house")
    assert spec is not None
    living_index = next(i for i, rr in enumerate(spec.rooms) if rr.key == "living")
    living = room(
        base,
        next(
            e.name for e in base.elements if isinstance(e, Room) and e.semantic_key == "room:living"
        ),
    )
    raw = spec.model_dump(mode="json")
    raw["rooms"][living_index]["target_area_m2"] = round(living.dimensions.area, 1)
    raw["requirements"] = [
        *raw.get("requirements", []),
        {"path": f"/rooms/{living_index}/target_area_m2", "priority": "must", "origin": "form"},
    ]
    strict = BuildingSpecification.model_validate(raw)
    for side in room_sides(base, living):
        if (
            not side.walls
            or side.walls[0].properties.wall_kind == "exterior"
            or side.covered < side.length - 1e-3
        ):
            continue
        for delta in (-1.0, -2.0, -3.0):
            op = ResizeRoom(room_id=living.id, edge=side.index, delta_m=delta)
            outcome = evaluate_edits(base, [op], PROFILE, MATERIALS, spec=strict)
            if outcome.rejection and any(
                i.code == "EDIT_REQUIREMENT_UNMET" for i in outcome.rejection.issues
            ):
                assert "required" in outcome.rejection.message
                # Without the requirement the same edit is judged on geometry and rules alone.
                loose = evaluate_edits(base, [op], PROFILE, MATERIALS, spec=None)
                assert loose.rejection is None or all(
                    i.code != "EDIT_REQUIREMENT_UNMET" for i in loose.rejection.issues
                )
                return
    pytest.fail("no living-room side could be moved far enough to test the requirement")


# --- invariants ----------------------------------------------------------------------------------


def _all_sides() -> list[tuple[str, str, int]]:
    out = []
    for name in FIXTURES:
        base = fixture(name)
        for r in (e for e in base.elements if isinstance(e, Room)):
            out += [(name, r.name, s.index) for s in room_sides(base, r)]
    return out


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(case=st.sampled_from(_all_sides()), delta=st.sampled_from([-0.5, -0.15, 0.15, 0.5]))
def test_every_resize_is_refused_or_consistent(case: tuple[str, str, int], delta: float) -> None:
    name, room_name, edge = case
    base = fixture(name)
    r = room(base, room_name)
    outcome = resize(name, r, edge, delta)
    if outcome.model is None:
        assert outcome.rejection is not None and outcome.rejection.message
        return
    after = by_id(outcome.model)[r.id]
    assert isinstance(after, Room)
    assert math.copysign(1, area(after) - area(r)) == math.copysign(1, delta)  # grows / shrinks

    def level_area(m: BuildingModel) -> float:
        return sum(area(e) for e in m.elements if isinstance(e, Room) and e.level_id == r.level_id)

    assert level_area(outcome.model) == pytest.approx(level_area(base), abs=1e-3)
    assert errors(validate_model(outcome.model, material_ids=MATERIALS)) == []
