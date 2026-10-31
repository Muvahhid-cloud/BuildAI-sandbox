"""Phase 2 exit: the 10 reference specs produce valid, plausible houses (docs/roadmap.md)."""

import json
from pathlib import Path

import pytest

from app.modules.building.elements import Door, Railing, Roof, Room, Stair, Wall, Window
from app.modules.building.enums import DoorKind, RoomType, WallKind
from app.modules.building.summary import summarize
from app.modules.building.validation import validate_model
from app.modules.layout.golden import golden_path, golden_summary
from app.modules.rules.model_checks import check_model
from tests.building.helpers import DATA_DIR
from tests.layout.helpers import PROFILE, SPEC_PATHS, load_spec, reference, rooms_of

NAMES = [p.name for p in SPEC_PATHS]


def test_there_are_twelve_reference_specs() -> None:
    assert len(NAMES) == 12  # 11: the L-shaped bungalow (V1.1); 12: the T-shaped one (V1.3)


@pytest.mark.parametrize("name", NAMES)
def test_model_is_valid_and_reachable(name: str) -> None:
    model = reference(name).model
    issues = validate_model(model, material_ids=None)
    assert [i for i in issues if i.severity == "error"] == []
    assert [i.message for i in issues if i.code == "ROOM_UNREACHABLE"] == []
    assert [i.message for i in issues if i.code == "HABITABLE_ROOM_WITHOUT_WINDOW"] == []


@pytest.mark.parametrize("name", NAMES)
def test_model_meets_the_rules_profile(name: str) -> None:
    findings = check_model(reference(name).model, PROFILE)
    assert [f"{f.code}: {f.message}" for f in findings] == []


@pytest.mark.parametrize("name", NAMES)
def test_program_is_delivered(name: str) -> None:
    spec = load_spec(name)
    model = reference(name).model
    assert len(model.levels) == spec.targets.storeys
    for req in spec.rooms:
        found = [
            el
            for el in model.elements
            if isinstance(el, Room)
            and el.semantic_key.startswith(f"room:{req.key}")
            and el.properties.room_type.value == req.type.value
        ]
        assert len(found) == req.count, req.key
        if req.level is not None:
            level_ids = {model.levels[req.level].id}
            assert {r.level_id for r in found} <= level_ids, req.key
        for feature in req.features:
            attached = rooms_of(
                model, RoomType.EN_SUITE if feature.value == "en_suite" else RoomType.WALK_IN_CLOSET
            )
            assert len([r for r in attached if req.key in r.semantic_key]) == req.count
    summary = summarize(model)
    assert summary.garage == (spec.features.garage is not None)
    assert summary.balconies == len(spec.features.balconies)
    assert summary.terraces == (1 if spec.features.terrace else 0)
    target = spec.targets.gross_floor_area_m2 or reference(name).metrics.target_gross_floor_area_m2  # type: ignore[union-attr]
    assert abs(summary.gross_floor_area_m2 - target) / target < 0.03


@pytest.mark.parametrize("name", NAMES)
def test_house_is_buildable_in_principle(name: str) -> None:
    model = reference(name).model
    els = model.elements
    doors = [el for el in els if isinstance(el, Door)]
    assert sum(d.properties.door_kind == DoorKind.ENTRANCE for d in doors) == 1
    assert any(isinstance(el, Roof) for el in els)
    for level in model.levels:
        exterior = [
            el
            for el in els
            if isinstance(el, Wall)
            and el.level_id == level.id
            and el.properties.wall_kind == WallKind.EXTERIOR
        ]
        assert len(exterior) >= 4
        assert any(isinstance(el, Window) and el.level_id == level.id for el in els)
    stairs = [el for el in els if isinstance(el, Stair)]
    assert len(stairs) == len(model.levels) - 1
    if stairs:  # the first flight has a guard on its open side
        assert any(isinstance(el, Railing) and el.semantic_key == "railing:stair_0" for el in els)


@pytest.mark.parametrize("name", NAMES)
def test_golden_file(name: str) -> None:
    """Spec + seed -> model is stable. On an intended change run `pnpm golden` and explain the
    change in the commit message."""
    path = golden_path(DATA_DIR / "fixtures" / "golden", Path(name))
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert golden_summary(reference(name)) == expected


def test_generated_house_fixture_is_current() -> None:
    fixture = (DATA_DIR / "fixtures" / "generated-house.model.json").read_text(encoding="utf-8")
    assert (
        fixture == reference("01-family-house-280.spec.json").model.model_dump_json(indent=2) + "\n"
    )
