"""Approved types are checked against the rules profile and refused — never resized (K2)."""

from app.modules.building.types import TypeSet
from app.modules.rules.loader import load_rules_profile
from app.modules.rules.type_checks import check_type_set
from tests.building.helpers import DATA_DIR
from tests.catalog.helpers import approved_generic_type_set

PROFILE = load_rules_profile(DATA_DIR, "generic-residential@1")


def _with_params(type_set: TypeSet, type_id: str, **params: float) -> TypeSet:
    types = [
        t.model_copy(update={"params": t.params.model_copy(update=params)})
        if t.id == type_id
        else t
        for t in type_set.types
    ]
    return type_set.model_copy(update={"types": types})


def test_generic_types_meet_the_generic_profile() -> None:
    assert check_type_set(approved_generic_type_set(), PROFILE) == []


def test_undersized_types_are_refused_with_rule_refs() -> None:
    ts = approved_generic_type_set()
    ts = _with_params(ts, "type.door.generic_wet_room", default_width=0.6)
    ts = _with_params(ts, "type.stair.generic_straight_1000", width=0.8)
    ts = _with_params(ts, "type.railing.generic_balcony", height=0.95)
    ts = _with_params(ts, "type.door.generic_garage", width_per_car=2.0)
    ts = _with_params(ts, "type.window.generic_service", default_width=0.4)
    issues = check_type_set(ts, PROFILE)
    refs = {i.rule_ref for i in issues}
    assert {i.code for i in issues} == {"TYPE_RULE_VIOLATION"}
    assert refs == {
        "generic-residential@1:doors.bathroom.min_width_m",
        "generic-residential@1:stairs.min_width_m",
        "generic-residential@1:railings.balcony_min_height_m",
        "generic-residential@1:doors.garage.min_width_per_car_m",
        "generic-residential@1:windows.min_width_m",
    }
    assert all(i.path.startswith("/roles/") for i in issues)
