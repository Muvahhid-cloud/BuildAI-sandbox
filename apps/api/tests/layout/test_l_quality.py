"""Design Intelligence V1.2: L layout quality (docs/3d-engine.md §16.11).

Measured on generated models: the wing's last room takes the gallery's end, the main corridor's
dead ends go to rooms, kitchen and dining meet where the corridor ends, the garden band is sized
for the rooms that belong on the garden, and the evaluation measures garden frontage.
"""

from functools import cache
from typing import Any

import pytest
from shapely.geometry import LineString, Polygon

from app.modules.building.elements import Room, Wall
from app.modules.building.enums import RoomType, Zone
from app.modules.building.geometry import wall_axis
from app.modules.building.specification import BuildingSpecification
from app.modules.building.summary import summarize
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.engine import LayoutResult, _orientation
from app.modules.layout.planner import (
    SearchInput,
    Zoning,
    _joinable,
    door_reach,
    garden_demands,
    l_circulation_area,
    search,
)
from app.modules.layout.program import RoomRequest, expand_program
from tests.layout.helpers import PROFILE
from tests.layout.test_design_intelligence import run
from tests.layout.test_l_topology import bungalow, l_required

CIRCULATION = {RoomType.CORRIDOR, RoomType.ENTRANCE, RoomType.HALL, RoomType.STAIRCASE}


def garden_l(**over: Any) -> dict[str, Any]:
    """A required L whose living and dining rooms should face the garden; kitchen next to
    dining (the V1.1 benchmark's weak spot)."""
    return l_required(
        rooms=[
            {"key": "living", "type": "living", "faces": "rear"},
            {"key": "kitchen", "type": "kitchen", "adjacent_to": ["dining"]},
            {"key": "dining", "type": "dining", "faces": "rear"},
            {"key": "bedroom", "type": "bedroom", "count": 3},
            {"key": "bathroom", "type": "bathroom", "count": 2},
        ],
        **over,
    )


@cache
def garden_result() -> LayoutResult:
    return run(garden_l(), patterns=False)


@cache
def garage_result() -> LayoutResult:
    return run(garden_l(features={"garage": {"cars": 1}}), patterns=False)


def polys(result: LayoutResult) -> dict[str, Polygon]:
    level = result.model.levels[0].id
    return {
        el.semantic_key: Polygon(  # on the model's 1 mm grid (sums carry float noise)
            [
                (round(el.position.x + p.x, 3), round(el.position.y + p.y, 3))
                for p in el.properties.boundary
            ]
        )
        for el in result.model.elements
        if isinstance(el, Room) and el.level_id == level
    }


def room_types(result: LayoutResult) -> dict[str, RoomType]:
    return {
        el.semantic_key: el.properties.room_type
        for el in result.model.elements
        if isinstance(el, Room)
    }


def inside_area(result: LayoutResult) -> tuple[float, float]:
    """(circulation area, area of all rooms inside the house) on the ground floor."""
    total = circ = 0.0
    for el in result.model.elements:
        if not isinstance(el, Room) or el.properties.zone == Zone.EXTERIOR:
            continue
        if el.properties.room_type == RoomType.GARAGE:
            continue
        total += el.dimensions.area
        circ += el.dimensions.area if el.properties.room_type in CIRCULATION else 0.0
    return circ, total


def shared(result: LayoutResult, a: str, b: str) -> float:
    p = polys(result)
    return float(p[a].exterior.intersection(p[b].exterior).length)


def exterior_wall(result: LayoutResult, suffix: str) -> LineString:
    wall = next(
        el
        for el in result.model.elements
        if isinstance(el, Wall) and el.semantic_key.endswith(f":{suffix}")
    )
    return LineString(wall_axis(wall))


# --- the wing's end and the corridor's ends ---------------------------------------------------


def req(key: str, t: RoomType, area: float = 12.0) -> RoomRequest:
    return RoomRequest(
        key=key,
        spec_key=key,
        spec_index=0,
        type=t,
        name=key,
        target_area=area,
        explicit_target=False,
        min_area=6.0,
        min_width=2.4,
        zone=Zone.PRIVATE,
        level=None,
    )


def test_door_reach_is_a_door_and_its_margins() -> None:
    cfg = DEFAULT_CONFIG
    living, bath = req("l", RoomType.LIVING, 30), req("b", RoomType.BATHROOM, 6)
    assert door_reach(living, cfg) == pytest.approx(cfg.interior_door[0] + 2 * cfg.door_margin)
    assert door_reach(bath, cfg) == pytest.approx(cfg.wet_room_door[0] + 2 * cfg.door_margin)


@pytest.mark.parametrize("result", [garden_result, garage_result])
def test_the_gallery_stops_in_the_wing_end_room(result: Any) -> None:
    r = result()
    p, types = polys(r), room_types(r)
    corridor = p["room:corridor_0"]
    wing_end = exterior_wall(r, "wing:N")
    # The corridor never reaches the wing's end wall: the last room takes the gallery's end.
    assert corridor.exterior.intersection(wing_end.buffer(1e-3)).length < 1e-6
    end_rooms = [
        k
        for k, poly in p.items()
        if types[k] not in CIRCULATION
        and poly.exterior.intersection(wing_end.buffer(1e-3)).length > 1e-6
    ]
    assert len(end_rooms) == 1
    # ... across the whole wing width (rooms and gallery).
    assert p[end_rooms[0]].exterior.intersection(wing_end.buffer(1e-3)).length == pytest.approx(
        wing_end.length,
        abs=0.01,  # the 1 mm buffer adds about 2 mm at the ends
    )


def test_corridor_ends_go_to_rooms_and_every_room_keeps_its_door() -> None:
    r = garden_result()
    circ, total = inside_area(r)
    assert circ / total <= 0.21  # V1.1 gave about 24 % for L houses like this one
    # Every room still opens onto circulation (validation would reject it otherwise, and the
    # engine only accepts valid models); the corridor touches neither end of the main bar.
    corridor = polys(r)["room:corridor_0"]
    x0, _, x1, _ = corridor.bounds
    walls = [exterior_wall(r, "W"), exterior_wall(r, "E")]
    touching = [w for w in walls if corridor.exterior.intersection(w.buffer(1e-3)).length > 1e-6]
    assert len(touching) < 2, (x0, x1)


def test_kitchen_and_dining_meet_where_the_corridor_ends() -> None:
    r = garden_result()
    assert shared(r, "room:kitchen", "room:dining") >= 0.9
    on_rear = set(summarize(r.model).rooms_on_facade.get("rear", []))
    assert {"room:living", "room:dining"} <= on_rear
    assert r.evaluation is not None and r.evaluation.hard_ok


def test_the_corridor_end_with_the_garage_door_is_kept() -> None:
    r = garage_result()
    garage = polys(r)["room:garage"]
    corridor = polys(r)["room:corridor_0"]
    # The garage door into the house sits on the corridor's end: they still meet.
    assert corridor.exterior.intersection(garage.exterior).length >= 0.9
    assert r.evaluation is not None and r.evaluation.hard_ok


def test_joins_respect_privacy_and_separations() -> None:
    kitchen, dining = req("kitchen", RoomType.KITCHEN), req("dining", RoomType.DINING)
    bedroom, bath = req("bedroom", RoomType.BEDROOM), req("bath", RoomType.BATHROOM)
    none = Zoning({}, [])
    assert _joinable(kitchen, dining, none)
    assert _joinable(bedroom, bath, none)
    assert not _joinable(bedroom, dining, none)  # privacy: no bedroom next to a day room
    apart = Zoning({}, [], [(frozenset({"kitchen"}), frozenset({"dining"}), 1.2)])
    assert not _joinable(kitchen, dining, apart)


def _inp(data: dict[str, Any], topologies: tuple[str, ...] = ("l",)) -> SearchInput:
    spec = BuildingSpecification.model_validate({"name": "x", **data})
    program = expand_program(spec, PROFILE, DEFAULT_CONFIG)
    wishes = {r.key: "north" for r in program.rooms if r.spec_key in ("living", "dining")}
    return SearchInput(
        spec=spec,
        program=program,
        levels={r.key: 0 for r in program.rooms},
        stair=None,
        floor_area_per_storey=spec.targets.gross_floor_area_m2 or 170,
        max_width=None,
        max_depth=None,
        garage_width=0.0,
        garage_depth=6.0,
        landing_depth=1.2,
        wishes=wishes,
        topologies=topologies,
    )


def test_every_l_candidate_keeps_doors_on_its_corridor() -> None:
    """Invariant over the whole search: cuts lie inside the bar, are long enough, are owned
    by one of the joined rooms, and leave every street/garden-side room a door's reach of
    corridor; the circulation estimate never grows with the cuts."""
    inp = _inp(garden_l())
    cfg = DEFAULT_CONFIG
    candidates = search(inp, cfg, 0)
    assert candidates and all(c.skeleton.topology == "l" for c in candidates)
    with_cuts = 0
    for cand in candidates:
        sk, lvl = cand.skeleton, cand.levels[0]
        cx0 = max([c.x1 for c in lvl.cuts if c.x0 < 1e-9], default=0.0)
        cx1 = min([c.x0 for c in lvl.cuts if c.x0 >= 1e-9], default=sk.W)
        for cut in lvl.cuts:
            assert 0.0 <= cut.x0 < cut.x1 <= sk.W
            assert cut.length >= cfg.remainder_min_depth - 1e-9
            assert cut.owner in cut.joins
        gx0, gx1 = sk.gallery_x
        assert cx0 <= gx0 + 1e-9 and gx1 <= cx1 + 1e-9  # the gallery still meets the corridor
        for lay in lvl.strips:
            if lay.strip.side not in ("north", "south"):
                continue
            x = lay.strip.x0
            for col in lay.columns:
                x1 = x + col.width
                if col.kind != "tuck":
                    contact = min(x1, cx1) - max(x, cx0)
                    assert contact >= door_reach(col.room, cfg) - 1e-6, (col.room.key, contact)
                x = x1
        no_cuts = l_circulation_area(sk, type(lvl)(lvl.index, lvl.strips, lvl.merged_strips))
        assert l_circulation_area(sk, lvl) <= no_cuts + 1e-9
        with_cuts += bool(lvl.cuts)
    assert with_cuts > 0


# --- garden frontage -------------------------------------------------------------------------


def test_garden_demand_counts_the_rooms_that_belong_on_the_garden() -> None:
    inp = _inp(garden_l())
    targets = {r.key: r.target_area for r in inp.program.rooms}
    demands = garden_demands(inp)
    # Living and dining face the garden; the kitchen is not counted (it can meet the dining
    # room where the corridor ends).
    assert demands == [pytest.approx(targets["living"] + targets["dining"])]
    plain = _inp(bungalow(design={"footprint_shape": "l_shape"}))
    plain = SearchInput(**{**plain.__dict__, "wishes": {}})
    t = {r.key: r.target_area for r in plain.program.rooms}
    assert garden_demands(plain) == [
        pytest.approx(t["living"]),
        pytest.approx(t["living"] + t["dining"]),
    ]


def test_garden_frontage_is_measured_when_the_garden_was_asked_for() -> None:
    r = garden_result()
    assert r.evaluation is not None
    crit = {c.key: c for c in r.evaluation.criteria}
    assert "garden_frontage" in crit
    frontage = crit["garden_frontage"]
    assert 0 < frontage.score <= 1 and "garden facade" in frontage.explanation
    plain = run(bungalow(), patterns=False)  # no garden intent: no frontage criterion
    assert plain.evaluation is not None
    assert "garden_frontage" not in {c.key for c in plain.evaluation.criteria}


def test_living_spaces_stay_out_of_the_bedroom_wing() -> None:
    r = garden_result()
    p, types = polys(r), room_types(r)
    wing_x = sorted(pt[0] for pt in exterior_wall(r, "wing:N").coords)
    d = max(pt[1] for pt in exterior_wall(r, "N").coords)
    wing = Polygon([(wing_x[0], d), (wing_x[1], d), (wing_x[1], 99), (wing_x[0], 99)])
    day = {RoomType.LIVING, RoomType.DINING, RoomType.KITCHEN}
    assert all(p[k].intersection(wing).area < 1e-6 for k, t in types.items() if t in day)


# --- topology comparison ---------------------------------------------------------------------


def test_a_requested_l_is_compared_across_more_l_footprints() -> None:
    result = run(bungalow(design={"footprint_shape": "l_shape"}), patterns=False)
    assert result.topology is not None
    built = result.topology.built_valid
    assert built["l"] > built["rect"]
    assert built["l"] <= DEFAULT_CONFIG.l_requested_builds


def test_a_pattern_suggested_l_gets_no_extra_attempts() -> None:
    data = bungalow(
        rooms=[{"key": "living", "type": "living", "faces": "rear"}, *bungalow()["rooms"][1:]],
        design={"priorities": ["privacy"]},
    )
    result = run(data)
    assert result.topology is not None and result.topology.searched == ("rect", "l")
    share = DEFAULT_CONFIG.candidates_to_build // 2
    assert result.topology.built_valid["l"] <= share
    assert result.topology.built_valid["rect"] <= share


# --- reporting -------------------------------------------------------------------------------


def test_facade_warning_is_measured_on_the_walls_not_on_the_plan_depth() -> None:
    """A wing room reaches past the main bar's depth without being on the garden facade; the
    V1.1 check (max y > D) counted it as facing the rear. Bathrooms that should face the rear
    are warned about exactly when they do not reach a rear-facing exterior wall."""
    r = garden_result()
    data = garden_l()
    data["rooms"] = [*data["rooms"][:4], {**data["rooms"][4], "faces": "rear"}]
    spec = BuildingSpecification.model_validate({"name": "x", **data})
    program = expand_program(spec, PROFILE, DEFAULT_CONFIG)
    rear = set(summarize(r.model).rooms_on_facade.get("rear", []))
    issues = _orientation(r.model, program, spec)
    warned = {i.message.split(" could not")[0] for i in issues}
    rooms = {el.semantic_key: el for el in r.model.elements if isinstance(el, Room)}
    baths = [f"room:{inst.key}" for inst in program.instances("bathroom")]
    assert baths
    for key in baths:
        assert (rooms[key].name in warned) == (key not in rear)
    for issue in issues:  # the holders named are rooms of the house only
        assert "Garage" not in issue.message and "Terrace" not in issue.message
