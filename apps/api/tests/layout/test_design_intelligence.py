"""Design Intelligence V1 in the layout engine: requirement priorities, layout patterns,
candidate evaluation, bounded repair, and the historical failures it fixes."""

import hashlib
import os
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import Polygon

import app.modules.layout.engine as engine
from app.modules.building.elements import Room
from app.modules.building.enums import RoomType
from app.modules.building.evaluation import DesignEvaluation, RequirementCheck
from app.modules.building.model import BuildingModel
from app.modules.building.patterns import PatternLibrary
from app.modules.building.specification import BuildingSpecification
from app.modules.building.summary import summarize
from app.modules.catalog.patterns import pattern_library
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.engine import LayoutError, LayoutResult, generate_layout
from app.modules.layout.patterns import detect_triggers, select_patterns
from tests.building.helpers import material_ids
from tests.catalog.helpers import real_registry
from tests.layout.helpers import NAMESPACE, PROFILE

API_ROOT = Path(__file__).resolve().parents[2]


@cache
def library() -> PatternLibrary:
    return pattern_library(real_registry())


def make(data: dict[str, Any]) -> BuildingSpecification:
    return BuildingSpecification.model_validate({"name": "Test", **data})


def run(data: dict[str, Any], *, patterns: bool = True, **kw: Any) -> LayoutResult:
    return generate_layout(
        make(data),
        PROFILE,
        id_namespace=NAMESPACE,
        seed=0,
        material_ids=material_ids(),
        patterns=library() if patterns else None,
        **kw,
    )


def rooms(model: BuildingModel) -> dict[str, Room]:
    return {
        el.semantic_key: el for el in model.elements if isinstance(el, Room) and el.semantic_key
    }


def poly(room: Room) -> Polygon:
    return Polygon(
        [(room.position.x + p.x, room.position.y + p.y) for p in room.properties.boundary]
    )


def shared(model: BuildingModel, a: str, b: str) -> float:
    r = rooms(model)
    if r[a].level_id != r[b].level_id:
        return 0.0
    return float(poly(r[a]).exterior.intersection(poly(r[b]).exterior).length)


FAMILY: dict[str, Any] = {
    "targets": {"storeys": 2, "gross_floor_area_m2": 220},
    "rooms": [
        {"key": "living", "type": "living", "level": 0, "target_area_m2": 40},
        {"key": "kitchen", "type": "kitchen", "level": 0},
        {"key": "dining", "type": "dining", "level": 0},
        {"key": "master_bedroom", "type": "bedroom", "level": 1, "features": ["en_suite"]},
        {"key": "bedroom", "type": "bedroom", "level": 1, "count": 3},
        {"key": "bathroom", "type": "bathroom"},
    ],
}


# --- historical failures (regression tests) ------------------------------------------------------


def test_requested_40_m2_living_room_is_delivered_within_its_range() -> None:
    """Historically a requested 40 m² living room came out at about 32-37 m² without a
    warning. The explicit target now has a permissible range (±10% by default)."""
    result = run(FAMILY, patterns=False)
    area = rooms(result.model)["room:living"].dimensions.area
    assert 36.0 <= area <= 44.0
    assert not [w for w in result.warnings if w.path == "/rooms/0/target_area_m2"]


def test_mandatory_living_room_area_is_met_or_generation_fails() -> None:
    data = dict(FAMILY, requirements=[{"path": "/rooms/0/target_area_m2", "priority": "must"}])
    result = run(data)
    assert result.evaluation is not None and result.evaluation.hard_ok
    check = next(c for c in result.evaluation.requirements if c.kind == "room_area")
    assert check.priority == "must" and check.met


def test_kitchen_requested_next_to_dining_shares_a_wall() -> None:
    """Historically 'kitchen next to the dining room' was dropped by the interpreter and the
    engine put them on opposite sides of the corridor (0 m shared)."""
    data = {
        "targets": {"storeys": 2, "gross_floor_area_m2": 220},
        "rooms": [
            {"key": "living", "type": "living", "level": 0},
            {"key": "kitchen", "type": "kitchen", "level": 0, "adjacent_to": ["dining"]},
            {"key": "dining", "type": "dining", "level": 0},
            {"key": "study", "type": "study"},
            {"key": "bedroom", "type": "bedroom", "level": 1, "count": 4},
            {"key": "bathroom", "type": "bathroom", "count": 2},
        ],
        "requirements": [{"path": "/rooms/1/adjacent_to/0", "priority": "must"}],
    }
    result = run(data)
    assert shared(result.model, "room:kitchen", "room:dining") >= 0.9


def test_panoramic_windows_go_to_the_rear_garden_facade_only() -> None:
    data = dict(
        FAMILY,
        design={
            "windows": {
                "emphasis": "panoramic",
                "preferred_facades": ["rear"],
                "excluded_facades": ["front"],
            }
        },
        requirements=[{"path": "/design/windows", "priority": "must"}],
    )
    result = run(data)
    by_facade = summarize(result.model).windows_by_facade
    assert by_facade["rear"].get("panoramic", 0) >= 2
    assert by_facade.get("front", {}).get("panoramic", 0) == 0
    assert result.evaluation is not None and result.evaluation.hard_ok


# --- mandatory requirements are never relaxed ----------------------------------------------------


APART = ["living", "dining", "kitchen"]
CONFLICT = {
    "targets": {"storeys": 1, "gross_floor_area_m2": 130},
    "rooms": [
        {"key": "living", "type": "living", "target_area_m2": 40},
        {"key": "kitchen", "type": "kitchen", "target_area_m2": 20, "adjacent_to": ["dining"]},
        {"key": "dining", "type": "dining"},
        {
            "key": "master_bedroom",
            "type": "bedroom",
            "features": ["en_suite"],
            "separate_from": APART,
        },
        {"key": "bedroom", "type": "bedroom", "count": 2, "separate_from": APART},
        {"key": "bathroom", "type": "bathroom"},
    ],
}
# What the interpreter makes of "a 40 m2 living room, a 20 m2 kitchen; the kitchen must be next
# to the dining room and the bedrooms must be separated from the living spaces" (benchmark).
MUSTS = [
    "/rooms/0/target_area_m2",
    "/rooms/1/target_area_m2",
    "/rooms/1/adjacent_to/0",
    *(f"/rooms/{i}/separate_from/{j}" for i in (3, 4) for j in range(3)),
]


def test_unmeetable_must_requirements_fail_with_the_reason() -> None:
    data = dict(CONFLICT, requirements=[{"path": p, "priority": "must"} for p in MUSTS])
    with pytest.raises(LayoutError) as info:
        run(data)
    assert info.value.code == "LAYOUT_REQUIREMENTS_UNMET"
    paths = {i.path for i in info.value.issues}
    assert paths and paths <= set(MUSTS)
    assert all("expected" in i.message and i.suggestion for i in info.value.issues)


def test_the_same_wishes_as_preferences_give_a_model_with_reported_deviations() -> None:
    result = run(CONFLICT)
    assert result.evaluation is not None and result.evaluation.hard_ok  # nothing is a MUST
    missed = [c for c in result.evaluation.requirements if c.kind == "room_area" and not c.met]
    deviations = {w.path for w in result.warnings if w.code == "LAYOUT_AREA_DEVIATION"}
    assert {c.path for c in missed} <= deviations  # every miss is reported, never hidden


def _fake_evaluation(unmet: bool) -> DesignEvaluation:
    check = RequirementCheck(
        path="/rooms/0/target_area_m2",
        kind="room_area",
        label="Living room: area",
        priority="must",
        origin="user_text",
        quote=None,
        expected="40 m²",
        delivered="30 m²" if unmet else "40 m²",
        met=not unmet,
    )
    return DesignEvaluation(requirements=[check], criteria=[], score=0.5)


def test_bounded_repair_builds_more_candidates_until_a_must_is_met(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def evaluate(spec: BuildingSpecification, model: BuildingModel) -> DesignEvaluation:
        calls["n"] += 1
        return _fake_evaluation(unmet=calls["n"] <= 3)  # the first three candidates miss it

    monkeypatch.setattr(engine, "evaluate_design", evaluate)
    config = DEFAULT_CONFIG.model_copy(update={"candidates_to_build": 2})
    result = run(FAMILY, config=config)
    assert result.metrics is not None
    assert result.metrics.repair_builds >= 2 and result.evaluation is not None
    assert result.evaluation.hard_ok
    assert result.candidates[0].must_met and result.candidates[0].chosen  # chosen ranks first


def test_repair_is_bounded_and_then_fails_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "evaluate_design", lambda s, m: _fake_evaluation(unmet=True))
    config = DEFAULT_CONFIG.model_copy(
        update={"candidates_to_build": 2, "repair_candidates_to_build": 3}
    )
    with pytest.raises(LayoutError) as info:
        run(FAMILY, config=config)
    assert info.value.code == "LAYOUT_REQUIREMENTS_UNMET"


# --- candidate evaluation ------------------------------------------------------------------------


def test_built_candidates_are_evaluated_and_the_choice_is_explained() -> None:
    result = run(FAMILY)
    assert result.metrics is not None and result.evaluation is not None
    assert result.metrics.candidates_valid == len(result.candidates) >= 2
    chosen = [c for c in result.candidates if c.chosen]
    assert len(chosen) == 1 and result.candidates[0].chosen
    assert result.metrics.design_score == result.evaluation.score
    keys = {c.key for c in result.evaluation.criteria}
    assert {"circulation", "proportions", "daylight", "privacy", "garden"} <= keys
    assert all(0 <= c.score <= 1 and c.explanation for c in result.evaluation.criteria)


def test_priorities_raise_the_weight_of_their_criterion() -> None:
    plain = run(FAMILY).evaluation
    focused = run(dict(FAMILY, design={"priorities": ["privacy"]})).evaluation
    assert plain is not None and focused is not None
    weight = {c.key: c.weight for c in plain.criteria}
    focused_weight = {c.key: c.weight for c in focused.criteria}
    assert focused_weight["privacy"] > weight["privacy"]


# --- layout patterns -----------------------------------------------------------------------------


def test_triggers_are_read_from_the_spec() -> None:
    garden = make(dict(FAMILY, design={"priorities": ["garden_connection"]}))
    assert set(detect_triggers(garden, 110, None, None)) == {"garden_focus"}
    narrow = make(dict(FAMILY, site={"plot_width_m": 7}))
    assert "narrow_site" in detect_triggers(narrow, 110, 7, None)
    open_plan = make(
        dict(FAMILY, rooms=[*FAMILY["rooms"][:1], {"key": "k", "type": "open_kitchen_living"}])
    )
    assert "open_plan" in detect_triggers(open_plan, 110, None, None)


def test_patterns_are_selected_and_merged_deterministically() -> None:
    spec = make(
        dict(FAMILY, design={"priorities": ["garden_connection", "privacy", "compactness"]})
    )
    guidance = select_patterns(library(), spec, 110, None, None)
    ids = [p.id for p in guidance.applied]
    assert ids == sorted(ids)
    assert {
        "pattern.garden_oriented_living",
        "pattern.public_private_zoning",
        "pattern.compact_family_home",
    } <= set(ids)
    assert all(p.status == "draft" for p in guidance.applied)
    # Compact (0.8-1.25) and garden (1.15-1.8) proportions intersect.
    assert guidance.aspect == (1.15, 1.25)
    assert guidance.band_penalty(RoomType.LIVING, "south") > 0
    assert guidance.band_penalty(RoomType.LIVING, "north") == 0
    assert select_patterns(None, spec, 110, None, None).applied == ()


def test_courtyard_pattern_is_never_applied() -> None:
    spec = make(dict(FAMILY, design={"priorities": ["garden_connection", "privacy"]}))
    guidance = select_patterns(library(), spec, 110, None, None)
    assert "pattern.courtyard_house" not in [p.id for p in guidance.applied]


def test_patterns_change_the_generated_layout_measurably() -> None:
    """The open-plan pattern keeps living, dining and kitchen together: without it the
    dining room is not open to the living room (benchmark case open-plan-living)."""
    data = {
        "targets": {"storeys": 2, "gross_floor_area_m2": 180},
        "rooms": [
            {"key": "living", "type": "living", "level": 0, "open_to": ["dining"]},
            {"key": "kitchen", "type": "kitchen", "level": 0},
            {"key": "dining", "type": "dining", "level": 0, "open_to": ["kitchen"]},
            {"key": "master_bedroom", "type": "bedroom", "level": 1, "features": ["en_suite"]},
            {"key": "bedroom", "type": "bedroom", "level": 1, "count": 2},
            {"key": "bathroom", "type": "bathroom"},
        ],
    }
    with_patterns, without = run(data), run(data, patterns=False)
    assert [p.id for p in with_patterns.patterns] == ["pattern.open_plan_living"]
    assert without.patterns == ()
    assert any("pattern" in n and "draft" in n for n in with_patterns.notes)

    def open_check(result: LayoutResult) -> bool:
        assert result.evaluation is not None
        return next(c.met for c in result.evaluation.requirements if c.path == "/rooms/0/open_to/0")

    assert open_check(with_patterns) and not open_check(without)


def test_patterns_never_override_explicit_facing() -> None:
    """Garden pattern wants day rooms on the garden side; an explicit 'faces front' wins."""
    data = dict(
        FAMILY,
        rooms=[{**FAMILY["rooms"][0], "faces": "front"}, *FAMILY["rooms"][1:]],
        design={"priorities": ["garden_connection"]},
        requirements=[{"path": "/rooms/0/faces", "priority": "must"}],
    )
    result = run(data)
    assert "pattern.garden_oriented_living" in [p.id for p in result.patterns]
    assert result.evaluation is not None and result.evaluation.hard_ok


def test_generation_with_patterns_does_not_depend_on_hash_seed() -> None:
    code = (
        "from tests.layout.test_design_intelligence import run, FAMILY;"
        "import hashlib;"
        "data = dict(FAMILY, design={'priorities': ['garden_connection', 'privacy']});"
        "r = run(data);"
        "print(hashlib.sha256((r.model.model_dump_json() + r.evaluation.model_dump_json())"
        ".encode()).hexdigest())"
    )
    hashes = set()
    for hash_seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(API_ROOT)}
        out = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
            [sys.executable, "-c", code],
            cwd=API_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        hashes.add(out.stdout.strip().splitlines()[-1])
    assert len(hashes) == 1
    assert hashlib.sha256(b"").hexdigest() not in hashes
