from collections import Counter

from app.modules.building.elements import Door, Furniture, Room, Stair, Wall, Window
from app.modules.building.enums import Layer, RelationshipKind
from app.modules.building.fixtures.demo_house import build_demo_house, demo_house_json, uid
from app.modules.building.model import BuildingModel
from app.modules.building.validation import validate_model
from tests.building.helpers import FIXTURE_PATH, material_ids


def test_demo_house_has_no_errors_or_warnings() -> None:
    issues = validate_model(build_demo_house(), material_ids=material_ids())
    assert issues == []


def test_committed_fixture_matches_generator() -> None:
    # The fixture is committed for the web app and tests; regenerate with `pnpm fixtures`.
    assert FIXTURE_PATH.read_text(encoding="utf-8") == demo_house_json()


def test_fixture_round_trips_through_the_schema() -> None:
    model = BuildingModel.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert model == build_demo_house()


def test_ids_are_unique_and_stable() -> None:
    model = build_demo_house()
    ids = [model.id, *(lvl.id for lvl in model.levels), *(el.id for el in model.elements)]
    assert len(ids) == len(set(ids))
    for el in model.elements:  # uuid5(semantic_key) => stable across regenerations
        assert el.id == uid(el.semantic_key)
    assert build_demo_house() == model  # deterministic


def test_contains_every_required_element_type() -> None:
    model = build_demo_house()
    counts = Counter(el.type for el in model.elements)
    for t in ("wall", "room", "door", "window", "slab", "stair", "roof", "furniture"):
        assert counts[t] > 0, t
    assert [lvl.name for lvl in model.levels] == ["Floor 1", "Floor 2"]
    walls = [el for el in model.elements if isinstance(el, Wall)]
    assert {w.properties.wall_kind for w in walls} == {"exterior", "interior"}


def test_required_rooms_per_floor() -> None:
    model = build_demo_house()
    by_level = {lvl.id: lvl.name for lvl in model.levels}
    rooms: dict[str, set[str]] = {}
    for el in model.elements:
        if isinstance(el, Room) and el.level_id:
            rooms.setdefault(by_level[el.level_id], set()).add(el.name)
    assert {
        "Entrance",
        "Living room",
        "Kitchen",
        "Dining area",
        "Bathroom",
        "Corridor",
        "Staircase",
    } <= rooms["Floor 1"]
    assert {
        "Master bedroom",
        "Bedroom 2",
        "Bedroom 3",
        "Bathroom",
        "Corridor",
        "Balcony",
    } <= rooms["Floor 2"]


def test_relationships_are_meaningful() -> None:
    model = build_demo_house()
    by_id = {el.id: el for el in model.elements}
    for el in model.elements:
        kinds = [r.kind for r in el.relationships]
        if isinstance(el, Door | Window):
            (host,) = [r.target_id for r in el.relationships if r.kind == "hosted_by"]
            assert isinstance(by_id[host], Wall)
        if isinstance(el, Door):
            assert 1 <= kinds.count(RelationshipKind.CONNECTS) <= 2, el.name
        if isinstance(el, Furniture):
            assert el.layer == Layer.FURNITURE
            assert kinds == [RelationshipKind.LOCATED_IN], el.name
        if isinstance(el, Wall):
            assert RelationshipKind.BOUNDS in kinds, el.name
    stair = next(el for el in model.elements if isinstance(el, Stair))
    assert stair.properties.from_level_id == model.levels[0].id
    assert stair.properties.to_level_id == model.levels[1].id


def test_stair_is_comfortable() -> None:
    stair = next(el for el in build_demo_house().elements if isinstance(el, Stair))
    r, t = stair.properties.riser_height, stair.properties.tread_depth
    assert 0.15 <= r <= 0.19
    assert 0.25 <= t <= 0.32
    assert 0.60 <= 2 * r + t <= 0.65  # comfort rule from generic-residential@1
