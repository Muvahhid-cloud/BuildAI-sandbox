from app.modules.building.fixtures.demo_house import build_demo_house
from app.modules.building.primitives import Vec3
from app.modules.rules.loader import load_rules_profile
from app.modules.rules.model_checks import check_model, clear_width
from tests.building.helpers import DATA_DIR, find, with_element

PROFILE = load_rules_profile(DATA_DIR, "generic-residential@1")


def test_demo_house_meets_the_generic_profile() -> None:
    assert check_model(build_demo_house(), PROFILE) == []


def test_clear_width_of_l_shaped_room_is_its_main_part() -> None:
    # 3 m wide main part, 1.2 m deep alcove along the facade.
    l_shape = [(0, 0), (5, 0), (5, 1.2), (3, 1.2), (3, 4), (0, 4)]
    assert abs(clear_width(l_shape) - 3.0) < 1e-6
    assert abs(clear_width([(0, 0), (2.5, 0), (2.5, 6), (0, 6)]) - 2.5) < 1e-6


def test_findings_carry_rule_refs_and_element_ids() -> None:
    model = build_demo_house()
    _, window = find(model, "window:bed2_s")
    model = with_element(
        model,
        "window:bed2_s",
        position=Vec3(x=window.position.x, y=0, z=0.3),
        dimensions=window.dimensions.model_copy(update={"width": 0.4}),
    )
    _, door = find(model, "door:bath_f")
    model = with_element(
        model, "door:bath_f", dimensions=door.dimensions.model_copy(update={"width": 0.6})
    )
    _, stair = find(model, "stair:main")
    model = with_element(
        model, "stair:main", dimensions=stair.dimensions.model_copy(update={"width": 0.8})
    )
    findings = {(i.code, i.rule_ref): i for i in check_model(model, PROFILE)}
    assert ("RULE_WINDOW_SIZE", "generic-residential@1:windows.min_width_m") in findings
    assert ("RULE_WINDOW_GUARD", "generic-residential@1:windows.guard_required_below_sill_m") in (
        findings
    )
    assert ("RULE_DOOR_WIDTH", "generic-residential@1:doors.bathroom") in findings
    assert ("RULE_STAIR_WIDTH", "generic-residential@1:stairs.min_width_m") in findings
    assert all(i.severity == "warning" and i.element_id is not None for i in findings.values())


def test_small_room_and_missing_glazing() -> None:
    model = build_demo_house()
    windows = [
        el.id
        for el in model.elements
        if el.type == "window" and el.semantic_key in {"window:study_n", "window:study_e"}
    ]
    model = model.model_copy(
        update={"elements": [el for el in model.elements if el.id not in windows]}
    )
    codes = {(i.code, i.element_id) for i in check_model(model, PROFILE)}
    _, study = find(model, "room:study")
    assert ("RULE_GLAZING_RATIO", study.id) in codes
