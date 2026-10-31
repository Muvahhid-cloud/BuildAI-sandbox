"""Design Intelligence V1.1: L-shaped single-storey footprints (docs/3d-engine.md §16.10)."""

import hashlib
import os
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from app.modules.building.elements import Door, Roof, Room, Wall, Window
from app.modules.building.enums import RoomType, Zone
from app.modules.building.evaluation import measure_footprint
from app.modules.building.geometry import wall_axis
from app.modules.building.geometry_checks import check_geometry
from app.modules.building.model import BuildingModel
from app.modules.building.primitives import EPS
from app.modules.building.specification import BuildingSpecification
from app.modules.building.validation import errors, validate_model
from app.modules.layout.build import envelope
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.engine import LayoutError, LayoutResult
from app.modules.layout.plan import Skeleton
from app.modules.layout.planner import SearchInput, l_skeletons, search
from app.modules.layout.program import expand_program
from app.modules.rules.spec_checks import check_spec
from tests.building.helpers import material_ids
from tests.layout.helpers import PROFILE, load_spec, reference
from tests.layout.test_design_intelligence import run

API_ROOT = Path(__file__).resolve().parents[2]
L_SPEC = "11-l-shaped-bungalow-160.spec.json"


def bungalow(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "targets": {"storeys": 1, "gross_floor_area_m2": 170},
        "rooms": [
            {"key": "living", "type": "living"},
            {"key": "kitchen", "type": "kitchen", "adjacent_to": ["dining"]},
            {"key": "dining", "type": "dining"},
            {"key": "bedroom", "type": "bedroom", "count": 3},
            {"key": "bathroom", "type": "bathroom", "count": 2},
        ],
    }
    base.update(over)
    return base


def l_required(**over: Any) -> dict[str, Any]:
    return bungalow(
        design={"footprint_shape": "l_shape"},
        requirements=[{"path": "/design/footprint_shape", "priority": "must"}],
        **over,
    )


@cache
def l_result() -> LayoutResult:
    return reference(L_SPEC)


def ground_rooms(model: BuildingModel) -> list[Room]:
    level = model.levels[0].id
    return [
        el
        for el in model.elements
        if isinstance(el, Room)
        and el.level_id == level
        and el.properties.room_type != RoomType.GARAGE
        and el.properties.zone != Zone.EXTERIOR
    ]


def poly(room: Room) -> Polygon:
    """Room outline in plan coordinates on the model's 1 mm grid (position + offset sums carry
    float noise, e.g. 10.299999999999999, that would leave zero-width slits in unions)."""
    return Polygon(
        [
            (round(room.position.x + p.x, 3), round(room.position.y + p.y, 3))
            for p in room.properties.boundary
        ]
    )


def house_walls(model: BuildingModel) -> list[Wall]:
    return [
        el
        for el in model.elements
        if isinstance(el, Wall) and el.semantic_key.startswith("wall:ext:")
    ]


# --- the envelope --------------------------------------------------------------------------------


def _sk(**kw: Any) -> Skeleton:
    base: dict[str, Any] = {
        "W": 14.0,
        "D": 9.0,
        "Ds": 4.0,
        "C": 1.2,
        "storeys": 1,
        "core_x0": 0.0,
        "lanes": 0,
        "lane_width": 0.0,
        "hall_x0": 0.0,
        "hall_x1": 2.2,
        "hall_side": "west",
        "garage_side": None,
    }
    base.update(kw)
    return Skeleton(**base)


def test_rectangular_envelope_is_unchanged() -> None:
    walls = envelope(_sk(), pitched=True)
    assert [k for k, *_ in walls] == ["S", "E", "N", "W"]
    assert {r for *_, r in walls} == {"roof:main"}


@pytest.mark.parametrize("side", ["west", "east"])
def test_l_envelope_is_a_closed_ccw_loop_with_one_inside_corner(side: str) -> None:
    sk = _sk(topology="l", wing_side=side, wing_depth=3.8, wing_length=6.0)
    walls = envelope(sk, pitched=True)
    assert len(walls) == 7
    for (_, _, end, _), (_, start, _, _) in zip(walls, walls[1:] + walls[:1], strict=True):
        assert end == start  # closed loop, each wall starts where the previous one ends
    ring = Polygon([start for _, start, _, _ in walls])
    assert ring.exterior.is_ccw
    assert ring.area == pytest.approx(sk.footprint_area)
    assert ring.area == pytest.approx(14 * 9 + (3.8 + 1.2) * 6)
    # Each wall belongs to one volume: wing walls support the wing roof when pitched.
    assert {r for k, *_, r in walls if k.startswith("wing:")} == {"roof:wing"}
    flat = envelope(sk, pitched=False)
    assert {r for *_, r in flat} == {"roof:main"}


# --- the generated L (reference spec 11) ---------------------------------------------------------


def test_reference_l_is_a_valid_l_shaped_model() -> None:
    model = l_result().model
    issues = validate_model(model, material_ids=material_ids())
    assert errors(issues) == []
    assert check_geometry(model) == []
    facts = measure_footprint(model)
    assert (facts.shape, facts.vertices, facts.reflex_corners) == ("l_shape", 6, 1)
    topology = l_result().topology
    assert topology is not None and topology.generated == "l_shape"


def test_footprint_shape_ignores_float_noise_between_room_outlines() -> None:
    """Regression (V1.2): room corners are position + boundary offset, so two rooms meeting at
    y = 17.8 could be 1e-12 apart; the union then had a zero-width slit and a valid L measured
    as "other (8 corners)", failing its own footprint requirement."""
    model = l_result().model
    noisy = []
    for el in model.elements:
        if isinstance(el, Room):
            moved = el.position.model_copy(update={"y": el.position.y + 3e-12})
            boundary = [p.model_copy(update={"y": p.y - 1e-12}) for p in el.properties.boundary]
            props = el.properties.model_copy(update={"boundary": boundary})
            el = el.model_copy(update={"position": moved, "properties": props})
        noisy.append(el)
    facts = measure_footprint(model.model_copy(update={"elements": noisy}))
    assert (facts.shape, facts.vertices, facts.reflex_corners) == ("l_shape", 6, 1)


def test_rooms_tile_the_footprint_inside_the_exterior_walls() -> None:
    model = l_result().model
    rooms = [poly(r) for r in ground_rooms(model)]
    union = unary_union(rooms)
    # No overlaps: the rooms' areas add up to the area they cover.
    assert sum(p.area for p in rooms) == pytest.approx(union.area, abs=1e-3)
    # The covered area is exactly the polygon the exterior walls enclose.
    envelope_ring = Polygon(
        [wall_axis(w)[0] for w in sorted(house_walls(model), key=lambda w: w.semantic_key)]
    )
    walls = unary_union([LineString(wall_axis(w)) for w in house_walls(model)])
    assert union.boundary.difference(walls.buffer(1e-3)).length == pytest.approx(0, abs=1e-6)
    assert union.area == pytest.approx(l_result().metrics.gross_floor_area_m2, abs=0.05)  # type: ignore[union-attr]
    assert envelope_ring.area > 0


def test_inside_corner_walls_meet_without_overlap() -> None:
    walls = house_walls(l_result().model)
    axes = {w.semantic_key: wall_axis(w) for w in walls}
    main_n = axes["wall:ext:L0:N"]
    # The inside corner: the main bar's garden wall shares an end point with the wing's inner
    # wall (wing:W for an east wing, wing:E for a west wing).
    corner = [
        (k, p)
        for k in ("wall:ext:L0:wing:W", "wall:ext:L0:wing:E")
        for p in axes[k]
        for q in main_n
        if abs(p[0] - q[0]) < EPS and abs(p[1] - q[1]) < EPS
    ]
    assert len(corner) == 1
    for a in walls:
        for b in walls:
            if a is not b:
                overlap = LineString(wall_axis(a)).intersection(LineString(wall_axis(b))).length
                assert overlap < 1e-6, (a.semantic_key, b.semantic_key)


def test_openings_sit_on_walls_of_their_rooms() -> None:
    model = l_result().model
    walls = {el.id: el for el in model.elements if isinstance(el, Wall)}
    for el in model.elements:
        if isinstance(el, (Door, Window)):
            host = walls[el.relationships[0].target_id]
            assert (
                el.position.x >= 0
                and el.position.x + el.dimensions.width <= host.dimensions.length + 1e-6
            )
    # The wing's rooms are lit through its outer wall, and the wing has its own roof.
    roofs = sorted(el.semantic_key for el in model.elements if isinstance(el, Roof))
    assert roofs == ["roof:garage", "roof:main", "roof:wing"]
    wing_walls = {w.id for w in house_walls(model) if ":wing:" in w.semantic_key}
    assert any(
        isinstance(el, Window) and el.relationships[0].target_id in wing_walls
        for el in model.elements
    )


def test_wing_garage_and_terrace_never_overlap() -> None:
    """The wing may stand on either side of the garage (V1.2): the garage stays on the street
    side of the garden facade, the wing beyond it, and the terrace stays clear of the wing."""
    model = l_result().model
    rooms = {r.semantic_key: r for r in model.elements if isinstance(r, Room)}
    garage, terrace = poly(rooms["room:garage"]), poly(rooms["room:terrace"])
    wing = next(w for w in house_walls(model) if w.semantic_key == "wall:ext:L0:wing:N")
    main_n = next(w for w in house_walls(model) if w.semantic_key == "wall:ext:L0:N")
    wing_x = sorted(p[0] for p in wall_axis(wing))
    d = wall_axis(main_n)[0][1]
    wing_box = Polygon([(wing_x[0], d), (wing_x[1], d), (wing_x[1], 99), (wing_x[0], 99)])
    assert garage.bounds[3] <= d + 1e-6  # the garage ends before the garden facade
    assert garage.intersection(wing_box).area < 1e-6
    assert terrace.intersection(wing_box).area < 1e-6


def test_l_generation_is_deterministic_across_hash_seeds() -> None:
    code = (
        "from tests.layout.helpers import reference;import hashlib;"
        f"print(hashlib.sha256(reference('{L_SPEC}').model.model_dump_json().encode()).hexdigest())"
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
    assert hashlib.sha256(l_result().model.model_dump_json().encode()).hexdigest() in hashes


def test_flat_roofed_l_has_one_l_shaped_roof() -> None:
    result = run(l_required(style={"roof": {"type": "flat"}}), patterns=False)
    roofs = [el for el in result.model.elements if isinstance(el, Roof)]
    assert [r.semantic_key for r in roofs] == ["roof:main"]
    assert len(roofs[0].properties.outline) == 6
    assert check_geometry(result.model) == []


# --- topology selection --------------------------------------------------------------------------


def test_required_l_searches_only_l_and_reports_it() -> None:
    result = run(l_required(), patterns=False)
    assert result.topology is not None
    assert result.topology.searched == ("l",) and result.topology.generated == "l_shape"
    assert result.topology.mandatory and result.evaluation is not None
    check = next(c for c in result.evaluation.requirements if c.kind == "footprint")
    assert check.met and check.priority == "must"


def test_a_required_l_that_does_not_fit_fails_with_the_reason() -> None:
    """9.3 m of plot: no L fits (since layout@1.7.0 an L of 170 m2 needs about 9.45 m), and
    the suggestion only offers a rectangle when one would actually fit."""
    data = l_required(site={"plot_width_m": 9.3})
    with pytest.raises(LayoutError) as info:
        run(data, patterns=False)
    assert info.value.code == "LAYOUT_INFEASIBLE"
    first = info.value.issues[0]
    assert first.path == "/design/footprint_shape" and "L-shaped" in first.message
    try:
        run(bungalow(site={"plot_width_m": 9.3}), patterns=False)
        rect_fits = True
    except LayoutError:
        rect_fits = False
    assert first.suggestion is not None
    assert ("rectangular" in first.suggestion) == rect_fits


def test_a_required_l_on_a_12_m_plot_is_generated_inside_the_plot() -> None:
    """V1.3 regression: until layout@1.6.0 this failed ("wider than the plot allows") because
    the main bar was sized only from fixed width/depth ratios; depth bars fit it."""
    result = run(l_required(site={"plot_width_m": 12}), patterns=False)
    facts = measure_footprint(result.model)
    assert (facts.shape, facts.vertices, facts.reflex_corners) == ("l_shape", 6, 1)
    xs = [
        r.position.x + p.x
        for r in result.model.elements
        if isinstance(r, Room)
        for p in r.properties.boundary
    ]
    assert min(xs) >= -1e-6 and max(xs) <= 12 + 1e-6


def test_a_preferred_l_is_generated_when_valid() -> None:
    data = bungalow(design={"footprint_shape": "l_shape"})
    result = run(data, patterns=False)
    assert result.topology is not None and result.topology.searched == ("rect", "l")
    assert result.topology.generated == "l_shape"
    assert "requested L-shaped footprint was generated" in result.topology.explanation


def test_a_preferred_l_on_two_storeys_falls_back_visibly() -> None:
    data = bungalow(
        targets={"storeys": 2, "gross_floor_area_m2": 200},
        design={"footprint_shape": "l_shape"},
    )
    spec = BuildingSpecification.model_validate({"name": "x", **data})
    issues = check_spec(spec, PROFILE, floor_structure_m=DEFAULT_CONFIG.floor_slab_thickness)
    assert [i.severity for i in issues if i.code == "SPEC_FOOTPRINT_UNSUPPORTED"] == ["warning"]
    result = run(data, patterns=False)
    assert result.topology is not None and result.topology.generated == "rectangular"
    assert any(w.code == "LAYOUT_TOPOLOGY_FALLBACK" for w in result.warnings)


def test_a_required_l_on_two_storeys_is_a_spec_error() -> None:
    data = l_required(targets={"storeys": 2, "gross_floor_area_m2": 200})
    spec = BuildingSpecification.model_validate({"name": "x", **data})
    issues = check_spec(spec, PROFILE, floor_structure_m=DEFAULT_CONFIG.floor_slab_thickness)
    assert [i.severity for i in issues if i.code == "SPEC_FOOTPRINT_UNSUPPORTED"] == ["error"]


def test_garden_alone_does_not_bring_an_l() -> None:
    data = bungalow(
        rooms=[{"key": "living", "type": "living", "faces": "rear"}, *bungalow()["rooms"][1:]],
        features={"terrace": {"attached_to": "living"}},
    )
    result = run(data)  # with the pattern library
    assert result.topology is not None and result.topology.searched == ("rect",)
    assert result.topology.generated == "rectangular"


def test_garden_plus_privacy_lets_an_l_compete_and_explains_the_choice() -> None:
    data = bungalow(
        rooms=[{"key": "living", "type": "living", "faces": "rear"}, *bungalow()["rooms"][1:]],
        design={"priorities": ["privacy"]},
    )
    result = run(data)
    assert result.topology is not None and result.topology.searched == ("rect", "l")
    assert "pattern.l_shaped_garden_wing" in result.topology.reason
    assert result.topology.built_valid["l"] >= 1 and result.topology.built_valid["rect"] >= 1
    assert "design score" in result.topology.explanation
    assert result.topology.generated in ("rectangular", "l_shape")


def test_rectangular_request_keeps_the_rectangle() -> None:
    result = run(
        bungalow(design={"footprint_shape": "rectangular", "priorities": ["privacy"]}),
    )
    assert result.topology is not None and result.topology.searched == ("rect",)
    assert result.topology.generated == "rectangular"


def test_l_skeletons_do_not_shift_rectangular_candidates() -> None:
    spec = load_spec("03-bungalow-150-terrace.spec.json")
    program = expand_program(spec, PROFILE, DEFAULT_CONFIG)
    inp = SearchInput(
        spec=spec,
        program=program,
        levels={r.key: 0 for r in program.rooms},
        stair=None,
        floor_area_per_storey=150,
        max_width=None,
        max_depth=None,
        garage_width=3.5,
        garage_depth=6.0,
        landing_depth=1.2,
        wishes={},
    )
    rect = search(inp, DEFAULT_CONFIG, 0)
    both = search(SearchInput(**{**inp.__dict__, "topologies": ("rect", "l")}), DEFAULT_CONFIG, 0)
    both_rect = [c for c in both if c.skeleton.topology == "rect"]

    def sig(cs: list[Any]) -> list[tuple[Any, ...]]:
        return sorted((round(c.score, 9), repr(c.skeleton), sorted(c.areas.items())) for c in cs)

    assert sig(rect) == sig(both_rect)
    assert any(c.skeleton.topology == "l" for c in both)
    assert l_skeletons(inp, DEFAULT_CONFIG, []) != []
