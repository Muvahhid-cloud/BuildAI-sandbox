import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.modules.building.enums import RoomType
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.engine import LayoutError
from app.modules.layout.plan import Strip
from app.modules.layout.planner import Unit, design_stair, layout_strip
from app.modules.layout.program import expand_program
from tests.layout.helpers import NAMESPACE, PROFILE, generate, load_spec

API_ROOT = Path(__file__).resolve().parents[2]


def test_stair_design_follows_the_rules() -> None:
    s = design_stair(3.0, PROFILE, DEFAULT_CONFIG)
    assert s.risers == 16
    assert 0.15 <= s.riser <= 0.19
    assert 0.25 <= s.tread <= 0.32
    assert 0.60 <= 2 * s.riser + s.tread <= 0.65
    assert s.run == pytest.approx(15 * s.tread)
    assert s.width >= PROFILE.stairs.min_width_m


def test_program_expansion_names_instances_and_attaches_suites() -> None:
    program = expand_program(
        load_spec("05-three-storey-villa-360.spec.json"), PROFILE, DEFAULT_CONFIG
    )
    keys = [r.key for r in program.rooms]
    assert {
        "bedroom_1",
        "bedroom_4",
        "master_bedroom_en_suite",
        "master_bedroom_walk_in_closet",
    } <= set(keys)
    suite = next(r for r in program.rooms if r.key == "master_bedroom_en_suite")
    assert suite.serves == "master_bedroom" and suite.type == RoomType.EN_SUITE
    assert all(r.target_area >= r.min_area for r in program.rooms)


def test_strip_widths_fill_the_strip_exactly_on_the_grid() -> None:
    program = expand_program(load_spec("08-classic-brick-220.spec.json"), PROFILE, DEFAULT_CONFIG)
    beds = [Unit(r) for r in program.rooms if r.type == RoomType.BEDROOM]
    strip = Strip("N", 0.0, 11.45, 6.1, 11.05, "north")
    lay = layout_strip(strip, beds, DEFAULT_CONFIG)
    assert lay is not None
    assert sum(c.width for c in lay.columns) == pytest.approx(strip.length)
    for c in lay.columns:
        assert round(c.width / DEFAULT_CONFIG.grid, 6) % 1 == 0
        assert c.width >= c.room.min_width
    assert layout_strip(Strip("N", 0.0, 5.0, 6.1, 11.05, "north"), beds, DEFAULT_CONFIG) is None


def test_same_input_same_model() -> None:
    spec = load_spec("03-bungalow-150-terrace.spec.json")
    a, b = generate(spec, seed=7), generate(spec, seed=7)
    assert a.model.model_dump_json() == b.model.model_dump_json()


def test_determinism_does_not_depend_on_hash_seed() -> None:
    code = (
        "from app.modules.layout.golden import generate_reference, golden_summary;"
        "from pathlib import Path;"
        "d = Path('../../data').resolve();"
        "r = generate_reference(d, d / 'fixtures/specs/02-compact-bungalow-90.spec.json');"
        "print(golden_summary(r)['model_sha256'])"
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
        hashes.add(out.stdout.strip())
    assert len(hashes) == 1


def test_ids_are_stable_per_namespace_and_reusable() -> None:
    spec = load_spec("02-compact-bungalow-90.spec.json")
    first = generate(spec).model
    ids = {el.semantic_key: el.id for el in first.elements}
    other = generate(spec).model
    assert {el.semantic_key: el.id for el in other.elements} == ids
    from app.modules.layout.engine import generate_layout
    from tests.building.helpers import material_ids

    elsewhere = generate_layout(
        spec, PROFILE, id_namespace=uuid.uuid4(), seed=0, material_ids=material_ids()
    ).model
    assert {el.id for el in elsewhere.elements}.isdisjoint(ids.values())
    kept = generate_layout(
        spec, PROFILE, id_namespace=uuid.uuid4(), previous_ids=ids, material_ids=material_ids()
    ).model
    assert {el.semantic_key: el.id for el in kept.elements} == ids


def test_every_element_uses_the_layout_engine_origin() -> None:
    model = generate(load_spec("02-compact-bungalow-90.spec.json")).model
    assert model.metadata.source == "layout"
    assert model.engine_version == DEFAULT_CONFIG.engine_version
    assert model.seed == 0
    assert {el.origin for el in model.elements} == {"generated"}


def test_deviations_are_reported_not_hidden() -> None:
    result = generate(load_spec("05-three-storey-villa-360.spec.json"))
    codes = {w.code for w in result.warnings}
    assert "LAYOUT_AREA_DEVIATION" in codes
    assert all(
        w.path.startswith("/rooms/") for w in result.warnings if w.code == "LAYOUT_AREA_DEVIATION"
    )


def test_derived_floor_area_is_noted() -> None:
    result = generate(load_spec("06-no-area-given.spec.json"))
    assert any("derived" in n for n in result.notes)


def test_plot_that_cannot_fit_the_house_is_infeasible() -> None:
    base = load_spec("01-family-house-280.spec.json")
    spec = type(base).model_validate(
        {**base.model_dump(), "site": {"plot_width_m": 9, "plot_depth_m": 9}}
    )
    with pytest.raises(LayoutError) as exc:
        generate(spec)
    assert exc.value.code == "LAYOUT_INFEASIBLE"
    assert exc.value.issues and all(i.severity == "error" for i in exc.value.issues)


def test_storey_too_tall_for_one_flight_is_infeasible() -> None:
    spec = load_spec("09-small-two-storey-120.spec.json")
    spec = type(spec).model_validate(
        {
            **spec.model_dump(),
            "targets": {**spec.targets.model_dump(), "floor_to_floor_height_m": 3.3},
        }
    )
    with pytest.raises(LayoutError) as exc:
        generate(spec)
    assert exc.value.code == "LAYOUT_INFEASIBLE"
    assert "risers" in exc.value.issues[0].message


def test_namespace_constant_is_a_uuid() -> None:
    assert isinstance(NAMESPACE, uuid.UUID)
