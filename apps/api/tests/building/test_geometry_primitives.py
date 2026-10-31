"""Geometric primitives of K2.5: host-relative interval arithmetic, wall frames, stair and roof
heights, derived coordination axes, and the constraint catalog."""

import math
import re

import pytest

from app.modules.building.axes import derive_axes
from app.modules.building.constraints import CONSTRAINTS
from app.modules.building.elements import Roof, Stair, Wall
from app.modules.building.enums import RoofType, WallAlignment
from app.modules.building.fixtures.demo_house import build_demo_house
from app.modules.building.geometry import (
    is_axis_aligned,
    roof_underside,
    stair_region,
    stair_rises_above,
    wall_frame,
)
from app.modules.building.hosting import free_intervals, junction_zones, merge, overlap
from app.modules.building.primitives import Rotation
from tests.building.helpers import DATA_DIR, find

# --- intervals ------------------------------------------------------------------------------


def test_overlap_counts_only_shared_length() -> None:
    assert overlap((0, 1), (1, 2)) == 0  # touching
    assert overlap((0, 1), (0.5, 3)) == 0.5
    assert overlap((0, 5), (1, 2)) == 1


def test_free_intervals_keep_the_gap() -> None:
    assert free_intervals([(0.0, 10.0)], [(4.0, 5.0)], gap=0.5) == [(0.0, 3.5), (5.5, 10.0)]
    assert free_intervals([(0.0, 10.0)], [(0.0, 10.0)]) == []
    assert free_intervals([(0.0, 2.0), (3.0, 6.0)], [(1.0, 4.0)]) == [(0.0, 1.0), (4.0, 6.0)]


def test_merge_joins_touching_intervals() -> None:
    assert merge([(3.0, 4.0), (0.0, 1.0), (1.0, 2.0)]) == [(0.0, 2.0), (3.0, 4.0)]


# --- junction zones -------------------------------------------------------------------------

AXIS = ((0.0, 0.0), (10.0, 0.0))
BODY = (-0.15, 0.15)  # a 0.3 m wall


def test_l_corners_occupy_the_wall_ends() -> None:
    corners = [(((0.0, 0.0), (0.0, 5.0)), 0.3), (((10.0, 5.0), (10.0, 0.0)), 0.3)]
    assert junction_zones(AXIS, BODY, corners) == [(0.0, 0.15), (9.85, 10.0)]


def test_t_junction_from_either_side() -> None:
    tees = [(((4.0, 0.0), (4.0, 3.0)), 0.12), (((6.0, -3.0), (6.0, 0.0)), 0.12)]
    zones = junction_zones(AXIS, BODY, tees)
    assert [(round(a, 3), round(b, 3)) for a, b in zones] == [(3.94, 4.06), (5.94, 6.06)]


def test_wall_ending_on_the_outer_face_is_a_junction() -> None:
    # e.g. a garage wall that stops at the house wall's outer face
    outer = [(((5.0, -3.0), (5.0, -0.15)), 0.3)]
    assert junction_zones(AXIS, BODY, outer) == [(4.85, 5.15)]


def test_crossing_wall_is_a_junction() -> None:
    assert junction_zones(AXIS, BODY, [(((2.0, -1.0), (2.0, 1.0)), 0.2)]) == [(1.9, 2.1)]


def test_parallel_collinear_and_distant_walls_are_not_junctions() -> None:
    others = [
        (((10.0, 0.0), (15.0, 0.0)), 0.3),  # collinear continuation
        (((0.0, 2.0), (10.0, 2.0)), 0.3),  # parallel
        (((12.0, -1.0), (12.0, 1.0)), 0.3),  # beyond the end
        (((5.0, 0.5), (5.0, 3.0)), 0.3),  # stops short of the wall body
    ]
    assert junction_zones(AXIS, BODY, others) == []


# --- walls, stairs, roofs -----------------------------------------------------------------------


def test_wall_frame_follows_the_alignment() -> None:
    _, wall = find(build_demo_house(), "wall:G-S")
    assert isinstance(wall, Wall)
    assert (wall_frame(wall).v0, wall_frame(wall).v1) == (-0.15, 0.15)
    left = wall.model_copy(
        update={"properties": wall.properties.model_copy(update={"alignment": WallAlignment.LEFT})}
    )
    f = wall_frame(left)
    assert (f.v0, f.v1) == (0.0, 0.3)
    assert f.at(1.0, 0.3) == pytest.approx((1.0, 0.3))  # +v = left = +y for a wall along +x
    assert f.local((2.0, -0.1)) == pytest.approx((2.0, -0.1))


def test_axis_alignment() -> None:
    assert all(is_axis_aligned(a) for a in (0.0, math.pi / 2, -math.pi / 2, math.pi, 1.570796))
    assert not is_axis_aligned(0.3)


def test_stair_region_and_rise() -> None:
    _, stair = find(build_demo_house(), "stair:main")  # 16 risers of 0.1875, treads 0.26
    assert isinstance(stair, Stair)
    xs = sorted({round(p[0], 3) for p in stair_region(stair)})
    ys = sorted({round(p[1], 3) for p in stair_region(stair)})
    assert (xs, ys) == ([3.55, 4.65], [0.9, 4.8])
    assert stair_rises_above(stair, 2.8) == pytest.approx(14 * 0.26)  # tread 15 is at 2.8125
    assert stair_rises_above(stair, 0.0) == 0.0
    assert stair_rises_above(stair, 3.0) is None  # no tread above the arrival floor


def test_roof_underside_for_each_roof_type() -> None:
    _, roof = find(build_demo_house(), "roof:main")  # hip, 25°, eaves at -0.65, overhang 0.5
    assert isinstance(roof, Roof)
    base = roof.position.z - roof.dimensions.thickness
    slope = math.tan(math.radians(25))
    corner = (-0.15, -0.15)  # outer corner of the walls: 0.5 m from both eaves
    assert roof_underside(roof, corner) == pytest.approx(base + 0.5 * slope)
    assert roof_underside(roof, corner) == pytest.approx(2.8, abs=0.001)  # the wall tops
    gable = roof.model_copy(
        update={"properties": roof.properties.model_copy(update={"roof_type": RoofType.GABLE})}
    )
    # ridge along x: rises from the north and south eaves only
    assert roof_underside(gable, (-0.15, 5.0)) == pytest.approx(base + 5.65 * slope)
    flat = roof.model_copy(
        update={"properties": roof.properties.model_copy(update={"roof_type": RoofType.FLAT})}
    )
    assert roof_underside(flat, (6.0, 5.0)) == base


# --- axes -----------------------------------------------------------------------------------------


def test_axes_are_derived_from_the_walls() -> None:
    model = build_demo_house()
    axes = derive_axes(model)
    keys = [a.key for a in axes]
    assert keys == sorted(set(keys), key=keys.index)  # unique
    walls = [el for el in model.elements if isinstance(el, Wall)]
    assert sum(len(a.wall_ids) for a in axes) == len(walls)
    south = next(a for a in axes if a.key == "y=0.000")
    assert {find(model, k)[1].id for k in ("wall:G-S", "wall:F-S")} <= set(south.wall_ids)
    assert south.wall_ids[0] == find(model, "wall:G-S")[1].id  # lower level first


def test_oblique_walls_have_no_axis() -> None:
    model = build_demo_house()
    i, wall = find(model, "wall:G-I4")
    elements = list(model.elements)
    elements[i] = wall.model_copy(update={"rotation": Rotation(z=0.3)})
    axes = derive_axes(model.model_copy(update={"elements": elements}))
    assert wall.id not in {w for a in axes for w in a.wall_ids}


# --- constraint catalog -------------------------------------------------------------------------


def test_constraint_catalog_is_well_formed() -> None:
    for cid, c in CONSTRAINTS.items():
        assert cid == c.id and re.fullmatch(r"[a-z_]+\.[a-z_]+", cid)
        assert re.fullmatch(r"[A-Z][A-Z_]+", c.code) and c.statement


def test_every_constraint_is_documented() -> None:
    doc = (DATA_DIR.parent / "docs" / "building-model.md").read_text(encoding="utf-8")
    missing = [c.id for c in CONSTRAINTS.values() if f"`{c.id}`" not in doc]
    missing += [c.code for c in CONSTRAINTS.values() if f"`{c.code}`" not in doc]
    assert missing == []
