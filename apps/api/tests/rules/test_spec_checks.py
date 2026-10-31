from typing import Any

import pytest

from app.modules.building.issues import Issue
from app.modules.building.specification import BuildingSpecification
from app.modules.rules.loader import load_rules_profile
from app.modules.rules.spec_checks import check_spec
from tests.building.helpers import DATA_DIR, SPECS_DIR

PROFILE = load_rules_profile(DATA_DIR, "generic-residential@1")


def spec(**overrides: Any) -> BuildingSpecification:
    doc: dict[str, Any] = {
        "name": "Test house",
        "targets": {"storeys": 2, "gross_floor_area_m2": 160},
        "rooms": [
            {"key": "kitchen_living", "type": "open_kitchen_living"},
            {"key": "bedroom", "type": "bedroom", "count": 3},
            {"key": "bathroom", "type": "bathroom"},
        ],
    }
    doc.update(overrides)
    return BuildingSpecification.model_validate(doc)


def check(s: BuildingSpecification) -> list[Issue]:
    return check_spec(s, PROFILE, floor_structure_m=0.2)


def codes(s: BuildingSpecification, severity: str = "error") -> set[str]:
    return {i.code for i in check(s) if i.severity == severity}


@pytest.mark.parametrize("path", sorted(SPECS_DIR.glob("*.spec.json")), ids=lambda p: p.name)
def test_reference_specs_have_no_errors(path: Any) -> None:
    s = BuildingSpecification.model_validate_json(path.read_text(encoding="utf-8"))
    assert codes(s) == set()


def test_minimal_valid_spec() -> None:
    assert check(spec()) == []


def test_level_out_of_range() -> None:
    s = spec(rooms=[*spec().model_dump()["rooms"], {"key": "study", "type": "study", "level": 2}])
    issues = [i for i in check(s) if i.code == "SPEC_LEVEL_OUT_OF_RANGE"]
    assert issues and issues[0].path == "/rooms/3/level"


def test_area_below_rules_minimum_is_traceable() -> None:
    s = spec(
        rooms=[
            {"key": "bathroom", "type": "bathroom"},
            {"key": "b", "type": "bedroom", "target_area_m2": 6},
        ]
    )
    [issue] = [i for i in check(s) if i.code == "SPEC_AREA_BELOW_MINIMUM"]
    assert issue.path == "/rooms/1/target_area_m2"
    assert issue.rule_ref == "generic-residential@1:rooms.bedroom.min_area_m2"
    assert issue.suggestion


def test_unknown_room_references() -> None:
    s = spec(
        rooms=[
            {
                "key": "kitchen",
                "type": "kitchen",
                "adjacent_to": ["pantry"],
                "open_to": ["kitchen"],
            },
            {"key": "bathroom", "type": "bathroom"},
        ]
    )
    assert "SPEC_UNKNOWN_ROOM_KEY" in codes(s)


def test_open_plan_only_between_living_spaces() -> None:
    s = spec(
        rooms=[
            {"key": "kitchen", "type": "kitchen", "open_to": ["bath"]},
            {"key": "bath", "type": "bathroom"},
        ]
    )
    assert "SPEC_OPEN_PLAN_TYPES" in codes(s)


def test_features_only_on_bedrooms() -> None:
    s = spec(
        rooms=[
            {"key": "study", "type": "study", "features": ["en_suite"]},
            {"key": "bathroom", "type": "bathroom"},
        ]
    )
    assert "SPEC_FEATURE_NOT_ALLOWED" in codes(s)


def test_needs_a_bathroom_but_an_en_suite_counts() -> None:
    no_bath = spec(rooms=[{"key": "bedroom", "type": "bedroom"}])
    assert "SPEC_NO_BATHROOM" in codes(no_bath)
    en_suite = spec(rooms=[{"key": "bedroom", "type": "bedroom", "features": ["en_suite"]}])
    assert "SPEC_NO_BATHROOM" not in codes(en_suite)
    assert "SPEC_NO_KITCHEN" in codes(en_suite, "warning")


def test_program_larger_than_area() -> None:
    s = spec(
        targets={"storeys": 1, "gross_floor_area_m2": 60},
        rooms=[
            {"key": "living", "type": "living", "target_area_m2": 40},
            {"key": "bedroom", "type": "bedroom", "count": 2, "target_area_m2": 14},
            {"key": "bathroom", "type": "bathroom"},
        ],
    )
    [issue] = [i for i in check(s) if i.code == "SPEC_PROGRAM_EXCEEDS_AREA"]
    assert issue.path == "/targets/gross_floor_area_m2"
    assert issue.suggestion and "m²" in issue.suggestion


def test_ceiling_and_stair_limits() -> None:
    low = spec(targets={"storeys": 2, "floor_to_floor_height_m": 2.6})
    assert "SPEC_CEILING_TOO_LOW" in codes(low)
    tall = spec(targets={"storeys": 2, "floor_to_floor_height_m": 3.2})
    assert "SPEC_STAIR_TOO_HIGH" in codes(tall)
    single = spec(targets={"storeys": 1, "floor_to_floor_height_m": 3.2})
    assert "SPEC_STAIR_TOO_HIGH" not in codes(single)  # no stair in a bungalow


def test_balcony_needs_an_upper_floor() -> None:
    s = spec(targets={"storeys": 1}, features={"balconies": [{"level": 1}]})
    assert "SPEC_BALCONY_LEVEL" in codes(s)


def test_attached_room_must_exist_on_that_level() -> None:
    s = spec(
        rooms=[
            {"key": "living", "type": "living", "level": 1},
            {"key": "bathroom", "type": "bathroom"},
        ],
        features={"terrace": {"attached_to": "living"}},
    )
    assert "SPEC_ATTACHED_LEVEL" in codes(s)


def test_plot_too_small() -> None:
    s = spec(
        site={"plot_width_m": 8, "plot_depth_m": 10, "setback_front_m": 3, "setback_side_m": 1}
    )
    assert "SPEC_PLOT_TOO_SMALL" in codes(s)
