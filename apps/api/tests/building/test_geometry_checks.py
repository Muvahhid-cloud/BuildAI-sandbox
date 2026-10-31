"""Geometric invariants (Phase 3.5 K2.5, building/geometry_checks.py).

Each test breaks one geometric property of the hand-authored demo house and asserts the
constraint that reports it; valid edge cases (touching, exactly fitting) must stay silent.
"""

import uuid
from typing import Any

import pytest

from app.modules.building.elements import Element, Relationship, Slab
from app.modules.building.enums import RelationshipKind
from app.modules.building.fixtures.demo_house import build_demo_house
from app.modules.building.geometry_checks import check_geometry
from app.modules.building.issues import Issue
from app.modules.building.migrations import load_model_json
from app.modules.building.model import BuildingModel
from app.modules.building.primitives import Rotation, Vec3
from app.modules.building.validation import validate_model
from tests.building.helpers import DATA_DIR, find, material_ids, with_element


@pytest.fixture(scope="module")
def model() -> BuildingModel:
    return build_demo_house()


def _issues(model: BuildingModel) -> list[Issue]:
    return check_geometry(model)


def _constraints(model: BuildingModel) -> set[str]:
    return {i.constraint for i in _issues(model) if i.constraint}


def _codes(model: BuildingModel) -> set[str]:
    return {i.code for i in _issues(model)}


def _about(model: BuildingModel, key: str) -> list[Issue]:
    _, el = find(model, key)
    return [i for i in _issues(model) if i.element_id == el.id]


def _without(model: BuildingModel, *keys: str) -> BuildingModel:
    ids = {find(model, k)[1].id for k in keys}
    return model.model_copy(update={"elements": [el for el in model.elements if el.id not in ids]})


def _with_added(model: BuildingModel, el: Element) -> BuildingModel:
    return model.model_copy(update={"elements": [*model.elements, el]})


def _moved_window(model: BuildingModel, key: str, **position: float) -> BuildingModel:
    _, win = find(model, key)
    return with_element(model, key, position=win.position.model_copy(update=position))


def _resized(model: BuildingModel, key: str, **dimensions: Any) -> BuildingModel:
    _, el = find(model, key)
    return with_element(model, key, dimensions=el.dimensions.model_copy(update=dimensions))


def _rels(model: BuildingModel, key: str, *extra: Relationship, keep: bool = True) -> BuildingModel:
    _, el = find(model, key)
    return with_element(model, key, relationships=[*(el.relationships if keep else []), *extra])


def _rel(model: BuildingModel, kind: RelationshipKind, key: str) -> Relationship:
    return Relationship(kind=kind, target_id=find(model, key)[1].id)


# --- valid models -------------------------------------------------------------------------


def test_demo_house_is_geometrically_valid(model: BuildingModel) -> None:
    assert _issues(model) == []


@pytest.mark.parametrize(
    "name", sorted(p.name for p in (DATA_DIR / "fixtures" / "historical").glob("*.json"))
)
def test_historical_1_0_0_fixtures_are_geometrically_valid(name: str) -> None:
    text = (DATA_DIR / "fixtures" / "historical" / name).read_text(encoding="utf-8")
    assert _issues(load_model_json(text)) == []


def test_findings_are_part_of_model_validation(model: BuildingModel) -> None:
    broken = _moved_window(model, "window:ent", x=11.5)
    issues = validate_model(broken, material_ids=material_ids())
    found = [i for i in issues if i.code == "OPENING_OUTSIDE_WALL"]
    assert found and found[0].constraint == "opening.within_length"


# --- 1. hosting ---------------------------------------------------------------------------


def test_opening_without_host(model: BuildingModel) -> None:
    broken = with_element(model, "window:ent", relationships=[])
    assert [i.constraint for i in _about(broken, "window:ent")] == ["host.exists"]


def test_opening_with_a_missing_host(model: BuildingModel) -> None:
    rel = Relationship(kind=RelationshipKind.HOSTED_BY, target_id=uuid.uuid4())
    broken = with_element(model, "window:ent", relationships=[rel])
    assert "HOST_NOT_FOUND" in _codes(broken)
    assert "DANGLING_RELATIONSHIP" in {i.code for i in validate_model(broken)}


def test_opening_with_two_hosts(model: BuildingModel) -> None:
    broken = _rels(model, "window:ent", _rel(model, RelationshipKind.HOSTED_BY, "wall:G-E"))
    issues = _about(broken, "window:ent")
    assert [i.code for i in issues] == ["HOST_AMBIGUOUS"]
    assert len(issues[0].related_ids) == 2


def test_opening_hosted_by_a_room(model: BuildingModel) -> None:
    rel = _rel(model, RelationshipKind.HOSTED_BY, "room:entrance")
    broken = with_element(model, "window:ent", relationships=[rel])
    assert [i.code for i in _about(broken, "window:ent")] == ["HOST_INCOMPATIBLE"]


def test_opening_on_another_level_than_its_host(model: BuildingModel) -> None:
    broken = with_element(model, "window:ent", level_id=model.levels[1].id)
    assert "host.same_level" in _constraints(broken)


@pytest.mark.parametrize(
    ("key", "change"),
    [
        ("window:ent", {"position": Vec3(x=0.3, y=0.1, z=0.9)}),
        ("window:ent", {"rotation": Rotation(z=0.5)}),
        ("door:front", {"position": Vec3(x=1.2, y=0, z=0.1)}),  # doors stand on the base
    ],
)
def test_opening_not_in_host_coordinates(
    model: BuildingModel, key: str, change: dict[str, Any]
) -> None:
    broken = with_element(model, key, **change)
    assert "INVALID_HOST_POSITION" in {i.code for i in _about(broken, key)}


# --- 2. opening geometry --------------------------------------------------------------------
# G-S runs from (0, 0) to (12, 0); walls join it at x = 0 and 12 (corners, 0.3 m) and at
# x = 4.8 and 7.4 (interior walls, 0.12 m). "window:ent" is 0.6 m wide, sill 0.9, height 1.3.


def test_opening_exactly_filling_the_wall_end_is_within_the_wall(model: BuildingModel) -> None:
    exact = _moved_window(model, "window:ent", x=11.4)  # ends at 12.0 = the wall's end
    constraints = {i.constraint for i in _about(exact, "window:ent")}
    assert "opening.within_length" not in constraints
    assert constraints == {"opening.clear_of_junctions"}  # ... but cuts into the corner wall


def test_opening_touching_a_junction_is_valid(model: BuildingModel) -> None:
    touching = _moved_window(model, "window:ent", x=11.25)  # ends at 11.85, the corner face
    assert _about(touching, "window:ent") == []


def test_opening_slightly_beyond_the_wall_end(model: BuildingModel) -> None:
    beyond = _moved_window(model, "window:ent", x=11.401)
    issue = next(i for i in _about(beyond, "window:ent") if i.code == "OPENING_OUTSIDE_WALL")
    assert issue.constraint == "opening.within_length"
    assert issue.measure is not None
    assert (issue.measure.actual, issue.measure.limit) == (12.001, 12.0)
    assert issue.related_ids == [find(model, "wall:G-S")[1].id]
    assert issue.path.endswith("/dimensions/width")


def test_opening_before_the_wall_start(model: BuildingModel) -> None:
    before = _moved_window(model, "window:ent", x=-0.2)
    assert "opening.within_length" in {i.constraint for i in _about(before, "window:ent")}


def test_opening_wider_than_its_wall(model: BuildingModel) -> None:
    wide = _resized(_moved_window(model, "window:ent", x=0.0), "window:ent", width=12.5)
    assert "OPENING_OUTSIDE_WALL" in {i.code for i in _about(wide, "window:ent")}


def test_opening_below_the_wall_base(model: BuildingModel) -> None:
    low = _moved_window(model, "window:ent", z=-0.1)
    assert "opening.above_base" in {i.constraint for i in _about(low, "window:ent")}


def test_opening_reaching_exactly_the_wall_top_is_valid(model: BuildingModel) -> None:
    assert _about(_moved_window(model, "window:ent", z=1.5), "window:ent") == []  # 1.5 + 1.3


def test_opening_taller_than_its_wall(model: BuildingModel) -> None:
    tall = _moved_window(model, "window:ent", z=1.501)
    issue = next(i for i in _about(tall, "window:ent"))
    assert (issue.code, issue.constraint) == ("OPENING_TOO_TALL", "opening.within_height")
    assert issue.measure is not None and issue.measure.limit == 2.8


def test_opening_in_a_t_junction(model: BuildingModel) -> None:
    crossing = _moved_window(model, "window:storage", x=4.65)  # across G-I2 at x = 4.8
    issues = _about(crossing, "window:storage")
    assert [i.code for i in issues] == ["OPENING_IN_WALL_JUNCTION"]
    assert issues[0].measure is not None and issues[0].measure.actual == pytest.approx(0.12)


def test_touching_openings_are_valid(model: BuildingModel) -> None:
    touching = _moved_window(model, "window:ent", x=3.0)  # ends where window:stair_g starts
    assert _about(touching, "window:ent") == []


def test_overlapping_openings(model: BuildingModel) -> None:
    overlapping = _moved_window(model, "window:ent", x=3.001)
    issues = [i for i in _issues(overlapping) if i.code == "OPENINGS_OVERLAP"]
    assert len(issues) == 1 and issues[0].constraint == "opening.no_overlap"
    assert issues[0].measure is not None and issues[0].measure.actual == pytest.approx(0.001)


def test_door_and_window_overlap(model: BuildingModel) -> None:
    _, door = find(model, "door:front")
    broken = _moved_window(model, "window:ent", x=1.5)
    issue = next(i for i in _issues(broken) if i.code == "OPENINGS_OVERLAP")
    assert door.id in {issue.element_id, *issue.related_ids}


def test_every_overlapping_pair_is_reported(model: BuildingModel) -> None:
    """A long window over the front door and window:stair_g overlaps both (not only its
    neighbour in the sorted order)."""
    long = _resized(_moved_window(model, "window:ent", x=0.3), "window:ent", width=4.0)
    pairs = [i for i in _issues(long) if i.code == "OPENINGS_OVERLAP"]
    assert len(pairs) == 2


def test_several_openings_on_one_wall_are_valid(model: BuildingModel) -> None:
    _, wall = find(model, "wall:G-S")
    hosted = [
        el
        for el in model.elements
        if any(
            r.kind == RelationshipKind.HOSTED_BY and r.target_id == wall.id
            for r in el.relationships
        )
    ]
    assert len(hosted) >= 5
    assert not [i for i in _issues(model) if wall.id in i.related_ids]


def test_door_thicker_than_its_wall(model: BuildingModel) -> None:
    thick = _resized(model, "door:front", thickness=0.35)
    assert "OPENING_THICKER_THAN_WALL" in {i.code for i in _about(thick, "door:front")}


# --- 3. walls -------------------------------------------------------------------------------


def test_oblique_wall(model: BuildingModel) -> None:
    oblique = with_element(model, "wall:G-I4", rotation=Rotation(z=0.3))
    assert "INVALID_WALL_GEOMETRY" in {i.code for i in _about(oblique, "wall:G-I4")}


def test_collinear_walls_overlap(model: BuildingModel) -> None:
    _, wall = find(model, "wall:G-I4")  # (4.8, 2.4) -> (7.4, 2.4)
    copy = wall.model_copy(
        update={
            "id": uuid.uuid4(),
            "semantic_key": "wall:copy",
            "position": Vec3(x=6.0, y=2.4, z=0),
            "relationships": [],
        }
    )
    issues = [i for i in _issues(_with_added(model, copy)) if i.code == "WALLS_OVERLAP"]
    assert len(issues) == 1 and issues[0].measure is not None
    assert issues[0].measure.actual == pytest.approx(1.4)


def test_open_exterior_envelope(model: BuildingModel) -> None:
    short = _resized(model, "wall:G-S", length=11.0)
    assert "wall.connected" in {i.constraint for i in _about(short, "wall:G-S")}


def test_wall_over_a_slab_opening(model: BuildingModel) -> None:
    moved = with_element(model, "wall:F-I1", position=Vec3(x=4.1, y=0, z=0))  # into the void
    assert "WALL_NOT_ON_SLAB" in {i.code for i in _about(moved, "wall:F-I1")}


# --- 4. rooms, doors, relationships ---------------------------------------------------------


def test_room_edge_along_no_wall(model: BuildingModel) -> None:
    open_east = _without(model, "wall:F-E", "window:bed2_e", "window:corr_e", "window:study_e")
    unenclosed = {i.element_id for i in _issues(open_east) if i.code == "INVALID_ROOM_BOUNDARY"}
    east_rooms = {find(model, k)[1].id for k in ("room:bedroom2", "room:corridor_f", "room:study")}
    assert unenclosed == east_rooms


def test_open_plan_and_stair_arrival_edges_are_enclosed(model: BuildingModel) -> None:
    """The entrance/staircase boundary has no wall (open plan) and corridor_f meets the stair
    void; both are valid. Without the slab opening the corridor edge is open."""
    assert "INVALID_ROOM_BOUNDARY" not in _codes(model)
    _, slab = find(model, "slab:floor_f")
    assert isinstance(slab, Slab)
    solid = with_element(
        model, "slab:floor_f", properties=slab.properties.model_copy(update={"holes": []})
    )
    corridor = find(model, "room:corridor_f")[1].id
    assert corridor in {i.element_id for i in _issues(solid) if i.code == "INVALID_ROOM_BOUNDARY"}


def test_wall_running_through_a_room(model: BuildingModel) -> None:
    _, wall = find(model, "wall:G-I4")
    through = wall.model_copy(
        update={
            "id": uuid.uuid4(),
            "semantic_key": "wall:through",
            "position": Vec3(x=1.0, y=8.0, z=0),
            "relationships": [],
        }
    )
    living = find(model, "room:living")[1].id
    issues = [i for i in _issues(_with_added(model, through)) if i.code == "ROOM_CROSSED_BY_WALL"]
    assert [i.element_id for i in issues] == [living]


def test_detached_balcony(model: BuildingModel) -> None:
    _, balcony = find(model, "room:balcony")
    moved = with_element(
        model, "room:balcony", position=balcony.position.model_copy(update={"y": 16.0})
    )
    issue = next(i for i in _about(moved, "room:balcony") if i.code == "ROOM_DETACHED")
    assert issue.severity == "warning"


def test_door_opening_to_no_room(model: BuildingModel) -> None:
    no_corridor = _without(model, "room:corridor_g")
    doors = {i.element_id for i in _issues(no_corridor) if i.code == "DOOR_TO_NOWHERE"}
    assert find(model, "door:ent_corr")[1].id in doors


def test_relationship_between_wrong_element_types(model: BuildingModel) -> None:
    broken = _rels(model, "furniture:sofa", _rel(model, RelationshipKind.HOSTED_BY, "wall:G-S"))
    assert "RELATIONSHIP_INVALID" in {i.code for i in _about(broken, "furniture:sofa")}
    reserved = _rels(model, "furniture:sofa", _rel(model, RelationshipKind.SERVES, "room:living"))
    assert "RELATIONSHIP_INVALID" in {i.code for i in _about(reserved, "furniture:sofa")}


@pytest.mark.parametrize(
    ("key", "kind", "target"),
    [
        ("door:front", RelationshipKind.CONNECTS, "room:living"),
        ("wall:G-I4", RelationshipKind.BOUNDS, "room:living"),
        ("room:living", RelationshipKind.ADJACENT_TO, "room:kitchen"),
        ("furniture:sofa", RelationshipKind.LOCATED_IN, "room:kitchen"),
        ("stair:main", RelationshipKind.LOCATED_IN, "room:living"),
        ("railing:balcony_n", RelationshipKind.LOCATED_IN, "room:study"),
    ],
)
def test_relationship_contradicting_the_geometry(
    model: BuildingModel, key: str, kind: RelationshipKind, target: str
) -> None:
    broken = _rels(model, key, _rel(model, kind, target))
    found = [i for i in _about(broken, key) if i.code == "RELATIONSHIP_INCONSISTENT"]
    assert len(found) == 1 and found[0].related_ids == [find(model, target)[1].id]


# --- 5. levels and stairs ------------------------------------------------------------------


def test_level_elevations_must_stack(model: BuildingModel) -> None:
    levels = [model.levels[0], model.levels[1].model_copy(update={"elevation": 3.5})]
    issue = next(i for i in _issues(model.model_copy(update={"levels": levels})))
    assert (issue.code, issue.path) == ("LEVEL_ELEVATION_MISMATCH", "/levels/1/elevation")


def test_stair_cutting_into_a_wall(model: BuildingModel) -> None:
    moved = with_element(model, "stair:main", position=Vec3(x=4.8, y=0.9, z=0))
    codes = {i.code for i in _about(moved, "stair:main")}
    assert {"STAIR_INTERSECTS_WALL", "STAIR_SLAB_CONFLICT"} <= codes


def test_stair_through_a_solid_slab(model: BuildingModel) -> None:
    _, slab = find(model, "slab:floor_f")
    assert isinstance(slab, Slab)
    solid = with_element(
        model, "slab:floor_f", properties=slab.properties.model_copy(update={"holes": []})
    )
    issue = next(i for i in _about(solid, "stair:main") if i.code == "STAIR_SLAB_CONFLICT")
    assert issue.related_ids == [slab.id] and issue.measure is not None


def test_stair_outside_the_building(model: BuildingModel) -> None:
    outside = with_element(model, "stair:main", position=Vec3(x=-5.0, y=0.9, z=0))
    codes = {i.code for i in _about(outside, "stair:main")}
    assert {"STAIR_OUTSIDE_ROOMS", "STAIR_ACCESS_INVALID"} <= codes


def test_oblique_stair(model: BuildingModel) -> None:
    oblique = with_element(model, "stair:main", rotation=Rotation(z=1.0))
    assert [i.code for i in _about(oblique, "stair:main")] == ["STAIR_GEOMETRY_INVALID"]


def test_stair_between_the_wrong_levels(model: BuildingModel) -> None:
    _, stair = find(model, "stair:main")
    same = stair.properties.model_copy(update={"to_level_id": model.levels[0].id})
    issues = validate_model(with_element(model, "stair:main", properties=same))
    assert "STAIR_LEVELS" in {i.code for i in issues}


# --- 6. slabs and roofs ---------------------------------------------------------------------


def test_overlapping_slabs(model: BuildingModel) -> None:
    _, slab = find(model, "slab:balcony")
    moved = with_element(
        model, "slab:balcony", position=slab.position.model_copy(update={"y": 8.0})
    )
    assert "SLABS_OVERLAP" in {i.code for i in _about(moved, "slab:balcony")}


def test_supporting_walls_must_meet_the_slab(model: BuildingModel) -> None:
    thick = _resized(model, "slab:floor_f", thickness=0.3)  # underside 2.7, walls 2.8 high
    issues = [i for i in _about(thick, "slab:floor_f") if i.code == "SLAB_RELATIONSHIP_INVALID"]
    assert len(issues) == 4  # the four ground-floor facades carry it
    assert issues[0].measure is not None and issues[0].measure.limit == pytest.approx(2.7)


@pytest.mark.parametrize(("dz", "word"), [(0.3, "floats"), (-0.3, "cuts")])
def test_roof_must_bear_on_its_walls(model: BuildingModel, dz: float, word: str) -> None:
    _, roof = find(model, "roof:main")
    moved = with_element(
        model, "roof:main", position=roof.position.model_copy(update={"z": roof.position.z + dz})
    )
    issues = [i for i in _about(moved, "roof:main") if i.code == "ROOF_SUPPORT_INVALID"]
    assert issues and word in issues[0].message


def test_roof_overhang_must_match_its_outline(model: BuildingModel) -> None:
    wrong = _resized(model, "roof:main", overhang=0.6)
    issues = [i for i in _about(wrong, "roof:main") if i.code == "ROOF_OVERHANG_MISMATCH"]
    assert len(issues) == 4


def test_roof_must_cover_its_supports(model: BuildingModel) -> None:
    _, roof = find(model, "roof:main")
    shifted = with_element(
        model, "roof:main", position=roof.position.model_copy(update={"x": roof.position.x + 1.0})
    )
    assert "ROOF_FOOTPRINT_INVALID" in {i.code for i in _about(shifted, "roof:main")}


@pytest.mark.parametrize("change", [{"pitch_deg": 0.0}, {"parapet_height": 0.3}])
def test_invalid_pitched_roof(model: BuildingModel, change: dict[str, float]) -> None:
    _, roof = find(model, "roof:main")
    props = roof.properties.model_copy(update=change)
    broken = with_element(model, "roof:main", properties=props)
    assert "ROOF_GEOMETRY_INVALID" in {i.code for i in _about(broken, "roof:main")}


def test_roof_without_supporting_walls(model: BuildingModel) -> None:
    unsupported = model
    for side in "SENW":
        _, wall = find(model, f"wall:F-{side}")
        rels = [r for r in wall.relationships if r.kind != RelationshipKind.SUPPORTS]
        unsupported = with_element(unsupported, f"wall:F-{side}", relationships=rels)
    issue = next(i for i in _about(unsupported, "roof:main"))
    assert (issue.code, issue.severity) == ("ROOF_UNSUPPORTED", "warning")


# --- shape of the findings -------------------------------------------------------------------


def test_every_finding_names_a_catalogued_constraint(model: BuildingModel) -> None:
    from app.modules.building.constraints import CONSTRAINTS

    broken = _moved_window(_resized(model, "slab:floor_f", thickness=0.3), "window:ent", x=4.5)
    issues = _issues(broken)
    assert issues
    for issue in issues:
        c = CONSTRAINTS[issue.constraint or ""]
        assert (issue.code, issue.severity) == (c.code, c.severity)
        assert issue.path.startswith("/")


def test_checks_never_modify_the_model(model: BuildingModel) -> None:
    before = model.model_dump_json()
    broken = _moved_window(model, "window:ent", x=11.5)
    _issues(broken)
    assert model.model_dump_json() == before
    assert find(broken, "window:ent")[1].position.x == 11.5


def test_findings_are_deterministic(model: BuildingModel) -> None:
    broken = _without(model, "room:corridor_g", "wall:F-E")
    assert _issues(broken) == _issues(broken)
