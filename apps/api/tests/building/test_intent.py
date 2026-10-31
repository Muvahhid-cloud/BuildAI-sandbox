"""Spec 1.2.0 intent: priorities, permissible area ranges, separations, requirement traces."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.building.intent import (
    DEFAULT_AREA_TOLERANCE,
    area_range,
    check_requirements,
    requirements,
)
from app.modules.building.specification import BuildingSpecification, Priority
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.rules.spec_checks import check_spec
from tests.layout.helpers import PROFILE


def spec(**over: Any) -> BuildingSpecification:
    base: dict[str, Any] = {
        "name": "Intent",
        "targets": {"storeys": 1, "gross_floor_area_m2": 140},
        "rooms": [
            {"key": "living", "type": "living", "target_area_m2": 40},
            {"key": "kitchen", "type": "kitchen", "adjacent_to": ["dining"]},
            {"key": "dining", "type": "dining"},
            {"key": "bedroom", "type": "bedroom", "count": 2, "separate_from": ["living"]},
            {"key": "bathroom", "type": "bathroom"},
        ],
    }
    base.update(over)
    return BuildingSpecification.model_validate(base)


def codes(s: BuildingSpecification) -> list[str]:
    return [i.code for i in check_requirements(s)]


def test_new_fields_are_optional_and_older_documents_keep_their_meaning() -> None:
    old = BuildingSpecification.model_validate(
        {
            "schema_version": "1.1.0",
            "name": "Old",
            "targets": {"storeys": 1},
            "rooms": [{"key": "bedroom", "type": "bedroom"}],
        }
    )
    assert old.schema_version == "1.1.0"
    assert old.requirements == [] and old.design.priorities == []
    assert requirements(old) == []


def test_untraced_requirements_are_preferences() -> None:
    reqs = {r.path: r for r in requirements(spec())}
    assert set(reqs) == {
        "/rooms/0/target_area_m2",
        "/rooms/1/adjacent_to/0",
        "/rooms/3/separate_from/0",
    }
    assert all(r.priority == Priority.SHOULD for r in reqs.values())
    assert reqs["/rooms/3/separate_from/0"].kind == "separate"
    assert reqs["/rooms/3/separate_from/0"].other == "living"


def test_traces_carry_priority_origin_and_quote() -> None:
    s = spec(
        requirements=[
            {
                "path": "/rooms/0/target_area_m2",
                "priority": "must",
                "origin": "user_text",
                "quote": "a 40 m2 living room",
            }
        ]
    )
    req = next(r for r in requirements(s) if r.kind == "room_area")
    assert req.mandatory and req.quote == "a 40 m2 living room"
    assert s.priority_of("/rooms/1/adjacent_to/0") == Priority.SHOULD


def test_area_range_defaults_to_the_tolerance_and_honours_min_max() -> None:
    living = spec().rooms[0]
    r = area_range(living)
    assert r.low == pytest.approx(40 * (1 - DEFAULT_AREA_TOLERANCE))
    assert r.high == pytest.approx(40 * (1 + DEFAULT_AREA_TOLERANCE))
    ranged = spec(
        rooms=[
            {
                "key": "living",
                "type": "living",
                "target_area_m2": 20,
                "min_area_m2": 20,
                "max_area_m2": 25,
            },
            {"key": "bedroom", "type": "bedroom"},
        ]
    ).rooms[0]
    assert (area_range(ranged).low, area_range(ranged).high) == (20, 25)


@pytest.mark.parametrize(
    "room",
    [
        {"key": "living", "type": "living", "min_area_m2": 30, "max_area_m2": 20},
        {"key": "living", "type": "living", "target_area_m2": 30, "max_area_m2": 20},
    ],
)
def test_inconsistent_area_ranges_are_rejected(room: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        spec(rooms=[room])


def test_duplicate_traces_and_priorities_are_rejected() -> None:
    trace = {"path": "/rooms/0/target_area_m2", "priority": "must"}
    with pytest.raises(ValidationError):
        spec(requirements=[trace, trace])
    with pytest.raises(ValidationError):
        spec(design={"priorities": ["privacy", "privacy"]})


def test_trace_paths_must_name_existing_values() -> None:
    assert codes(spec(requirements=[{"path": "/rooms/9/faces"}])) == ["SPEC_REQUIREMENT_PATH"]
    assert codes(spec(requirements=[{"path": "/rooms/1/faces"}])) == ["SPEC_REQUIREMENT_PATH"]


def test_must_is_refused_where_the_engine_cannot_enforce_it() -> None:
    s = spec(requirements=[{"path": "/targets/gross_floor_area_m2", "priority": "must"}])
    assert codes(s) == ["SPEC_REQUIREMENT_UNSUPPORTED"]
    ok = spec(requirements=[{"path": "/targets/gross_floor_area_m2", "priority": "should"}])
    assert codes(ok) == []


def test_separation_must_name_another_room_and_not_contradict_adjacency() -> None:
    unknown = spec(
        rooms=[
            {"key": "living", "type": "living", "separate_from": ["garden"]},
            {"key": "bedroom", "type": "bedroom"},
        ]
    )
    assert codes(unknown) == ["SPEC_UNKNOWN_ROOM_KEY"]
    conflict = spec(
        rooms=[
            {"key": "living", "type": "living", "adjacent_to": ["bedroom"]},
            {"key": "bedroom", "type": "bedroom", "separate_from": ["living"]},
        ]
    )
    assert codes(conflict) == ["SPEC_REQUIREMENT_CONFLICT"]


def test_max_area_below_the_rules_minimum_is_an_error() -> None:
    s = spec(
        rooms=[
            {"key": "bedroom", "type": "bedroom", "target_area_m2": 4, "max_area_m2": 4},
            {"key": "bathroom", "type": "bathroom"},
        ]
    )
    issues = check_spec(s, PROFILE, floor_structure_m=DEFAULT_CONFIG.floor_slab_thickness)
    paths = {i.path for i in issues if i.code == "SPEC_AREA_BELOW_MINIMUM"}
    assert "/rooms/0/max_area_m2" in paths
