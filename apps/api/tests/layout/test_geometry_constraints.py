"""Constraint-aware generation (Phase 3.5 K2.5, layout/constraints.py, docs/3d-engine.md §16.7)."""

import hashlib
import os
import subprocess
import sys
from typing import Any

import pytest
from shapely import Polygon

from app.modules.building.elements import Door, Stair, Wall
from app.modules.building.fingerprint import geometry_sha256
from app.modules.building.geometry import OVERLAP_AREA_TOLERANCE, stair_region, wall_frame
from app.modules.building.geometry_checks import check_geometry
from app.modules.building.primitives import EPS
from app.modules.building.types import TypeSet
from app.modules.building.validation import validate_model
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.constraints import flights_fit_lanes
from app.modules.layout.engine import LayoutError, generate_layout
from app.modules.layout.golden import GOLDEN_NAMESPACE
from app.modules.layout.plan import Skeleton, lane_faces
from app.modules.layout.planner import design_stair
from tests.building.helpers import DATA_DIR, material_ids
from tests.catalog.helpers import approved_generic_type_set
from tests.layout.helpers import PROFILE, SPEC_PATHS, generate, load_spec, reference

API_ROOT = DATA_DIR.parent / "apps" / "api"
NAMES = [p.name for p in SPEC_PATHS]
FACADE_CORE_SPECS = [n for n in NAMES if n[:2] in {"05", "06", "09"}]


def _typed(name: str, type_set: TypeSet | None = None) -> Any:
    return generate_layout(
        load_spec(name),
        PROFILE,
        id_namespace=GOLDEN_NAMESPACE,
        material_ids=material_ids(),
        type_set=type_set or approved_generic_type_set(),
    )


def _replace_type(type_set: TypeSet, type_id: str, **params: object) -> TypeSet:
    types = [
        t.model_copy(update={"params": t.params.model_copy(update=params)})
        if t.id == type_id
        else t
        for t in type_set.types
    ]
    return type_set.model_copy(update={"types": types})


# --- reference buildings --------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_reference_models_are_geometrically_valid(name: str) -> None:
    assert check_geometry(reference(name).model) == []
    assert check_geometry(_typed(name).model) == []


@pytest.mark.parametrize("name", NAMES)
def test_stair_flights_do_not_cut_into_walls(name: str) -> None:
    """Regression (layout@1.1.0): with the stair core on the facade, the flight cut 5 cm into
    the exterior wall and ran under the edge of the slab above (specs 05, 06, 09)."""
    model = reference(name).model
    for stair in (el for el in model.elements if isinstance(el, Stair)):
        flight = Polygon(stair_region(stair))
        for wall in (el for el in model.elements if isinstance(el, Wall)):
            if wall.level_id == stair.level_id:
                body = Polygon(wall_frame(wall).footprint())
                assert flight.intersection(body).area < OVERLAP_AREA_TOLERANCE, wall.name


def test_facade_core_specs_now_have_their_core_on_the_facade() -> None:
    """The three layouts that changed in layout@1.2.0 keep their facade core, with a wider lane
    and footprint instead of a flight inside the wall."""
    for name in FACADE_CORE_SPECS:
        model = reference(name).model
        stairs = [el for el in model.elements if isinstance(el, Stair)]
        xs = [p[0] for s in stairs for p in stair_region(s)]
        width = reference(name).metrics.footprint_width_m  # type: ignore[union-attr]
        near = min(min(xs), width - max(xs))
        # exterior face + clearance, compared with the model tolerance (CLAUDE.md rule 8)
        assert near == pytest.approx(0.15 + 0.045, abs=EPS), name


# --- skeleton constraint ------------------------------------------------------------------------


def _skeleton(**kw: Any) -> Skeleton:
    base: dict[str, Any] = {
        "W": 8.0, "D": 10.0, "Ds": 5.0, "C": 1.2, "storeys": 2, "core_x0": 3.0, "lanes": 1,
        "lane_width": 1.2, "hall_x0": 4.2, "hall_x1": 6.4, "hall_side": "east",
        "garage_side": None,
    }  # fmt: skip
    return Skeleton(**{**base, **kw})


def test_interior_lane_fits_its_flight() -> None:
    stair = design_stair(3.0, PROFILE, DEFAULT_CONFIG)
    sk = _skeleton()
    west, east, centre = lane_faces(sk, 0, 0.3, 0.12)
    assert (round(west, 3), round(east, 3), centre) == (3.06, 4.14, 3.6)  # the lane middle
    assert flights_fit_lanes(sk, stair, DEFAULT_CONFIG)


def test_facade_lane_needs_room_for_the_exterior_wall() -> None:
    stair = design_stair(3.0, PROFILE, DEFAULT_CONFIG)
    assert not flights_fit_lanes(_skeleton(core_x0=0.0), stair, DEFAULT_CONFIG)
    widened = _skeleton(core_x0=0.0, lane_width=1.3)
    west, east, centre = lane_faces(widened, 0, 0.3, 0.12)
    assert (round(west, 3), round(east, 3), round(centre, 3)) == (0.15, 1.24, 0.695)
    assert flights_fit_lanes(widened, stair, DEFAULT_CONFIG)
    east_side = _skeleton(W=8.0, core_x0=6.7, lane_width=1.3, hall_side="west")
    assert flights_fit_lanes(east_side, stair, DEFAULT_CONFIG)


# --- opening fit before the search ------------------------------------------------------------


def _low(f2f: float, **features: Any) -> dict[str, Any]:
    return {
        "name": "Low storeys",
        "targets": {"storeys": 2, "gross_floor_area_m2": 200, "floor_to_floor_height_m": f2f},
        "rooms": [
            {"key": "kl", "type": "open_kitchen_living"},
            {"key": "bedroom", "type": "bedroom", "count": 3},
            {"key": "bathroom", "type": "bathroom"},
        ],
        "features": features,
    }


def test_sliding_doors_that_do_not_fit_the_storey_are_infeasible() -> None:
    """Was LAYOUT_INVALID ("engine bug") in layout@1.1.0: every candidate failed validation."""
    with pytest.raises(LayoutError) as exc:
        generate(_low(2.5, balconies=[{"level": 1}]))
    assert exc.value.code == "LAYOUT_INFEASIBLE"
    [issue] = exc.value.issues
    assert (issue.code, issue.constraint) == ("TYPE_GEOMETRY_MISMATCH", "type.fits_storey")
    assert issue.path == "/targets/floor_to_floor_height_m"
    assert issue.suggestion == "Raise the floor-to-floor height to at least 2.6 m."
    assert issue.measure is not None and (issue.measure.actual, issue.measure.limit) == (2.4, 2.3)


def test_optional_garden_door_is_left_out_of_a_low_storey() -> None:
    result = generate(_low(2.5))
    assert validate_model(result.model, material_ids=material_ids()) == []
    doors = [el for el in result.model.elements if isinstance(el, Door)]
    assert all(d.semantic_key != "door:garden" for d in doors)
    assert any("No garden door" in n for n in result.notes)
    assert any(d.semantic_key == "door:garden" for d in generate(_low(2.6)).model.elements)


def test_type_set_doors_must_fit_the_storey() -> None:
    tall = _replace_type(approved_generic_type_set(), "type.door.generic_sliding", height=3.5)
    with pytest.raises(LayoutError) as exc:
        _typed("01-family-house-280.spec.json", tall)
    assert exc.value.code == "LAYOUT_INFEASIBLE"
    assert any("type.door.generic_sliding" in i.message for i in exc.value.issues)
    thick = _replace_type(
        _replace_type(approved_generic_type_set(), "type.door.generic_interior", thickness=0.2),
        "type.door.generic_entrance",
        thickness=0.2,
    )
    for tid in (
        "type.door.generic_wet_room",
        "type.door.generic_sliding",
        "type.door.generic_garage",
    ):
        thick = _replace_type(thick, tid, thickness=0.2)
    with pytest.raises(LayoutError) as exc:
        _typed("01-family-house-280.spec.json", thick)
    assert {i.measure.quantity for i in exc.value.issues if i.measure} == {"door_thickness"}


def test_type_snapshot_that_does_not_fit_its_host() -> None:
    model = _typed("02-compact-bungalow-90.spec.json").model
    types = [
        t.model_copy(update={"params": t.params.model_copy(update={"height": 3.5})})
        if t.id == "type.door.generic_interior"
        else t
        for t in model.types
    ]
    broken = model.model_copy(update={"types": types})
    issues = [i for i in check_geometry(broken) if i.code == "TYPE_GEOMETRY_MISMATCH"]
    assert issues and all(i.constraint == "type.fits_host" for i in issues)
    assert "type.door.generic_interior" in issues[0].message
    codes = {i.code for i in validate_model(broken)}
    assert "TYPE_PARAM_MISMATCH" in codes  # the elements no longer match their type either


# --- determinism ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", FACADE_CORE_SPECS)
def test_facade_core_generation_is_reproducible(name: str) -> None:
    a = generate_layout(load_spec(name), PROFILE, id_namespace=GOLDEN_NAMESPACE, seed=3)
    b = generate_layout(load_spec(name), PROFILE, id_namespace=GOLDEN_NAMESPACE, seed=3)
    assert a.model.model_dump_json() == b.model.model_dump_json()
    assert geometry_sha256(_typed(name).model) == geometry_sha256(reference(name).model)


def test_geometry_does_not_depend_on_hash_seed() -> None:
    code = (
        "from tests.layout.helpers import reference;"
        "from app.modules.building.geometry_checks import check_geometry;"
        "import hashlib;"
        "m = reference('09-small-two-storey-120.spec.json').model;"
        "print(hashlib.sha256(m.model_dump_json().encode()).hexdigest(), len(check_geometry(m)))"
    )
    outputs = set()
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
        outputs.add(out.stdout.strip())
    assert len(outputs) == 1
    digest, findings = outputs.pop().split()
    model = reference("09-small-two-storey-120.spec.json").model
    assert digest == hashlib.sha256(model.model_dump_json().encode()).hexdigest()
    assert findings == "0"
