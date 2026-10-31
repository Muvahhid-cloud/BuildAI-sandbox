"""Design Intelligence V1.3: T-shaped footprints and shape capabilities in the layout engine
(docs/3d-engine.md §16.12). Everything is measured on the generated model."""

import hashlib
import json
import os
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from app.modules.building.elements import Roof, Room, Wall, Window
from app.modules.building.evaluation import _eight_corner_shape, measure_footprint
from app.modules.building.footprint import normalize_shape_requirement
from app.modules.building.geometry import wall_axis
from app.modules.building.geometry_checks import check_geometry
from app.modules.building.specification import BuildingSpecification
from app.modules.building.validation import errors, validate_model
from app.modules.layout.build import envelope
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.engine import LayoutError, LayoutResult
from app.modules.rules.spec_checks import check_spec
from tests.building.helpers import DATA_DIR, material_ids
from tests.layout.helpers import PROFILE, reference
from tests.layout.test_design_intelligence import run
from tests.layout.test_l_topology import _sk, bungalow, ground_rooms, house_walls, poly

API_ROOT = Path(__file__).resolve().parents[2]
T_SPEC = "12-t-shaped-bungalow-170.spec.json"
REPORTED = DATA_DIR / "fixtures" / "specs" / "regression" / "ai-yellow-long-l.spec.json"


def shaped(shape: str, priority: str = "must", **over: Any) -> dict[str, Any]:
    return bungalow(
        design={"footprint_shape": shape},
        requirements=[{"path": "/design/footprint_shape", "priority": priority}],
        **over,
    )


@cache
def t_result() -> LayoutResult:
    return reference(T_SPEC)


# --- geometry ---------------------------------------------------------------------------------


@pytest.mark.parametrize("side", ["west", "east"])
def test_t_envelope_is_a_closed_ccw_loop_with_two_inside_corners(side: str) -> None:
    sk = _sk(topology="t", wing_side=side, wing_depth=3.6, wing_length=5.0, wing_x0=4.5, W=14.0)
    walls = envelope(sk, pitched=True)
    assert [k for k, *_ in walls] == ["S", "E", "N:E", "wing:E", "wing:N", "wing:W", "N:W", "W"]
    for (_, _, end, _), (_, start, _, _) in zip(walls, walls[1:] + walls[:1], strict=True):
        assert end == start
    ring = Polygon([start for _, start, _, _ in walls])
    assert ring.exterior.is_ccw
    assert ring.area == pytest.approx(14 * 9 + (3.6 + 1.2) * 5.0)
    assert {r for k, *_, r in walls if k.startswith("wing:")} == {"roof:wing"}


Ring = list[tuple[float, float]]


def test_eight_corner_shapes_are_told_apart() -> None:
    t: Ring = [(0, 0), (14, 0), (14, 9), (9, 9), (9, 14), (5, 14), (5, 9), (0, 9)]
    u: Ring = [(0, 0), (14, 0), (14, 14), (10, 14), (10, 9), (4, 9), (4, 14), (0, 14)]
    z: Ring = [(0, 0), (8, 0), (8, 4), (14, 4), (14, 9), (6, 9), (6, 5), (0, 5)]

    def inside(ring: Ring) -> list[int]:
        out: list[int] = []
        n = len(ring)
        for i in range(n):
            (ax, ay), (bx, by), (cx, cy) = ring[i - 1], ring[i], ring[(i + 1) % n]
            if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) < 0:
                out.append(i)
        return out

    assert _eight_corner_shape(t, inside(t)) == "t_shape"
    assert _eight_corner_shape(u, inside(u)) == "u_shape"
    assert _eight_corner_shape(z, inside(z)) == "other"


def test_reference_t_is_a_valid_t_shaped_model() -> None:
    model = t_result().model
    assert errors(validate_model(model, material_ids=material_ids())) == []
    assert check_geometry(model) == []
    facts = measure_footprint(model)
    assert (facts.shape, facts.vertices, facts.reflex_corners) == ("t_shape", 8, 2)
    topology = t_result().topology
    assert topology is not None and topology.generated == "t_shape" and topology.mandatory


def test_t_rooms_tile_the_envelope_and_every_room_has_daylight() -> None:
    model = t_result().model
    rooms = [poly(r) for r in ground_rooms(model)]
    union = unary_union(rooms)
    assert sum(p.area for p in rooms) == pytest.approx(union.area, abs=1e-3)
    walls = unary_union([LineString(wall_axis(w)) for w in house_walls(model)])
    assert union.boundary.difference(walls.buffer(1e-3)).length == pytest.approx(0, abs=1e-6)
    assert len(house_walls(model)) == 8
    warnings = validate_model(model, material_ids=material_ids())
    assert not [i for i in warnings if i.code == "HABITABLE_ROOM_WITHOUT_WINDOW"]


def test_t_has_a_main_and_a_wing_roof_and_windows_in_the_wing() -> None:
    model = t_result().model
    roofs = sorted(el.semantic_key for el in model.elements if isinstance(el, Roof))
    assert roofs == ["roof:garage", "roof:main", "roof:wing"]
    wing = {w.id for w in house_walls(model) if ":wing:" in w.semantic_key}
    assert any(
        isinstance(el, Window) and el.relationships[0].target_id in wing for el in model.elements
    )


def test_flat_roofed_t_has_one_t_shaped_roof() -> None:
    result = run(shaped("t_shape", style={"roof": {"type": "flat"}}), patterns=False)
    roofs = [el for el in result.model.elements if isinstance(el, Roof)]
    assert [r.semantic_key for r in roofs] == ["roof:main"]
    assert len(roofs[0].properties.outline) == 8
    assert check_geometry(result.model) == []


def test_t_keeps_the_facade_colour() -> None:
    model = t_result().model
    design = model.design
    assert design is not None and design.facade_color is not None
    assert design.facade_color.name == "yellow"
    exterior = [
        w for w in model.elements if isinstance(w, Wall) and w.semantic_key.startswith("wall:ext:")
    ]
    assert {w.properties.finish_right_color for w in exterior} == {design.facade_color.hex}


def test_t_generation_is_deterministic_across_hash_seeds() -> None:
    code = (
        "from tests.layout.helpers import reference;import hashlib;"
        f"print(hashlib.sha256(reference('{T_SPEC}').model.model_dump_json().encode()).hexdigest())"
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
    assert hashlib.sha256(t_result().model.model_dump_json().encode()).hexdigest() in hashes


# --- capabilities and fallbacks -----------------------------------------------------------------


def test_a_preferred_t_competes_with_rectangles_and_wins_when_valid() -> None:
    result = run(shaped("t_shape", "should"), patterns=False)
    assert result.topology is not None and result.topology.searched == ("rect", "t")
    assert result.topology.generated == "t_shape"
    assert measure_footprint(result.model).shape == "t_shape"


@pytest.mark.parametrize("shape", ["u_shape", "courtyard"])
def test_a_required_shape_without_a_generator_is_refused_with_the_reason(shape: str) -> None:
    data = shaped(shape)
    spec = BuildingSpecification.model_validate({"name": "x", **data})
    issues = check_spec(spec, PROFILE, floor_structure_m=DEFAULT_CONFIG.floor_slab_thickness)
    found = [i for i in issues if i.code == "SPEC_FOOTPRINT_UNSUPPORTED"]
    assert [i.severity for i in found] == ["error"] and "cannot" in found[0].message
    # The engine itself (e.g. called without spec checks) never builds another shape either.
    with pytest.raises(LayoutError) as info:
        run(data, patterns=False)
    assert info.value.code == "LAYOUT_SHAPE_UNSUPPORTED"
    assert info.value.issues[0].path == "/design/footprint_shape"


def test_a_preferred_shape_without_a_generator_falls_back_visibly() -> None:
    result = run(shaped("u_shape", "should"), patterns=False)
    assert result.topology is not None
    assert result.topology.generated == "rectangular" and result.topology.searched == ("rect",)
    assert result.topology.limitation is not None and "U-shaped" in result.topology.limitation
    fallback = [w for w in result.warnings if w.code == "LAYOUT_TOPOLOGY_FALLBACK"]
    assert fallback and fallback[0].message.startswith("A U-shaped footprint was requested")


def test_a_t_on_two_storeys_is_refused_or_falls_back() -> None:
    two: dict[str, Any] = {"targets": {"storeys": 2, "gross_floor_area_m2": 220}}
    must = BuildingSpecification.model_validate({"name": "x", **shaped("t_shape", **two)})
    issues = check_spec(must, PROFILE, floor_structure_m=DEFAULT_CONFIG.floor_slab_thickness)
    assert [i.severity for i in issues if i.code == "SPEC_FOOTPRINT_UNSUPPORTED"] == ["error"]
    result = run(shaped("t_shape", "should", **two), patterns=False)
    assert result.topology is not None and result.topology.generated == "rectangular"
    assert any(w.code == "LAYOUT_TOPOLOGY_FALLBACK" for w in result.warnings)


# --- the reported request -------------------------------------------------------------------------


def test_the_reported_yellow_long_l_is_now_generated_as_an_l() -> None:
    """The real model's spec for "make me a long L designed house with the yellow walls"
    (stored run, layout@1.6.0): the L was a should and every L skeleton was too shallow, so a
    rectangle was generated. Now: required (read from the user's words) and laid out on
    depth bars."""
    raw = json.loads(REPORTED.read_text("utf-8"))
    spec = BuildingSpecification.model_validate(raw)
    assert spec.priority_of("/design/footprint_shape") == "should"
    fixed, note = normalize_shape_requirement(spec)
    assert note is not None and fixed.priority_of("/design/footprint_shape") == "must"
    for data in (raw, fixed.model_dump(mode="json")):
        result = run(data)
        facts = measure_footprint(result.model)
        assert (facts.shape, facts.vertices, facts.reflex_corners) == ("l_shape", 6, 1)
        assert result.model.design is not None and result.model.design.facade_color is not None
        assert result.model.design.facade_color.name == "yellow"
        assert not [w for w in result.warnings if w.code == "LAYOUT_TOPOLOGY_FALLBACK"]
        rooms = [r for r in result.model.elements if isinstance(r, Room)]
        assert sum(r.dimensions.area for r in rooms if r.properties.zone.value != "exterior") > 100
