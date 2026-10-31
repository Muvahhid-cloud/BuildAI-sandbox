"""Offline interpreter: user intent that spec 1.2.0 can carry (Design Intelligence V1)."""

from app.modules.ai.providers.mock_interpreter import interpret_offline
from app.modules.ai.schemas.generation import SpecificationDraft
from app.modules.building.specification import BuildingSpecification
from tests.ai.helpers import validate_spec


def spec_of(prompt: str) -> BuildingSpecification:
    draft = SpecificationDraft.model_validate(interpret_offline(prompt))
    assert draft.specification is not None, draft
    return draft.specification


def room(spec: BuildingSpecification, key: str) -> int:
    return next(i for i, r in enumerate(spec.rooms) if r.key == key)


def test_a_room_size_is_not_taken_as_the_house_size() -> None:
    """Historical bug: "a 40 m2 living room in a 220 m2 house" became a 40 m² house (and the
    layout failed); the living room size was lost."""
    spec = spec_of("I want a 40 m2 living room in a two-storey 220 m2 house with 3 bedrooms")
    assert spec.targets.gross_floor_area_m2 == 220
    i = room(spec, "living")
    assert spec.rooms[i].target_area_m2 == 40
    trace = spec.trace(f"/rooms/{i}/target_area_m2")
    assert trace is not None and trace.priority == "must" and trace.origin == "user_text"
    assert trace.quote is not None and "40 m2 living room" in trace.quote


def test_room_sizes_in_several_phrasings() -> None:
    spec = spec_of(
        "Modern two-storey house of 220 m2 with 4 bedrooms: a 40 m2 living room, a kitchen of "
        "about 16 m2 and a master bedroom of at least 20 m2."
    )
    living, kitchen, master = (
        spec.rooms[room(spec, k)] for k in ("living", "kitchen", "master_bedroom")
    )
    assert (living.target_area_m2, kitchen.target_area_m2) == (40, 16)
    assert master.target_area_m2 == 20 and master.min_area_m2 == 20 and master.max_area_m2 == 25
    assert spec.priority_of(f"/rooms/{room(spec, 'kitchen')}/target_area_m2") == "should"
    assert spec.priority_of(f"/rooms/{room(spec, 'master_bedroom')}/target_area_m2") == "must"
    assert spec.targets.gross_floor_area_m2 == 220


def test_kitchen_next_to_dining_is_kept_with_its_priority() -> None:
    """Historical bug: the adjacency request was dropped by the interpreter."""
    must = spec_of(
        "Two-storey 180 m2 house with 3 bedrooms; the kitchen must be next to the dining room"
    )
    k = room(must, "kitchen")
    assert must.rooms[k].adjacent_to == ["dining"]
    assert must.priority_of(f"/rooms/{k}/adjacent_to/0") == "must"
    plain = spec_of(
        "Two-storey 180 m2 house with 3 bedrooms and the kitchen next to the dining room"
    )
    assert plain.rooms[room(plain, "kitchen")].adjacent_to == ["dining"]
    assert plain.priority_of(f"/rooms/{room(plain, 'kitchen')}/adjacent_to/0") == "should"


def test_the_nearest_room_is_the_one_next_to_another() -> None:
    spec = spec_of(
        "Two-storey 140 m2 townhouse with 3 bedrooms and the kitchen next to the dining room."
    )
    assert spec.rooms[room(spec, "kitchen")].adjacent_to == ["dining"]
    assert all(not r.adjacent_to for r in spec.rooms if r.type == "bedroom")


def test_bedrooms_separated_from_living_spaces() -> None:
    spec = spec_of(
        "Single-storey house of 160 m2 with 3 bedrooms and 2 bathrooms. The bedrooms "
        "must be separated from the living spaces for privacy."
    )
    bedrooms = [r for r in spec.rooms if r.type == "bedroom"]
    assert bedrooms and all(
        set(r.separate_from) == {"living", "dining", "kitchen"} for r in bedrooms
    )
    assert "privacy" in spec.design.priorities
    assert all(t.priority == "must" for t in spec.requirements if "separate_from" in t.path)
    assert validate_spec(spec) == []


def test_priorities_and_plot() -> None:
    spec = spec_of(
        "Narrow urban plot 8 m wide and 30 m deep: a two-storey townhouse of 140 m2 "
        "with 3 bedrooms, plenty of natural light and privacy from the street."
    )
    assert spec.site is not None
    assert (spec.site.plot_width_m, spec.site.plot_depth_m) == (8, 30)
    assert spec.design.priorities == ["daylight", "privacy"]


def test_open_plan_living_dining_kitchen_becomes_one_sequence() -> None:
    spec = spec_of(
        "Two-storey family house of 180 m2 with 3 bedrooms and an open-plan living, "
        "dining and kitchen area."
    )
    assert spec.rooms[room(spec, "living")].open_to == ["dining"]
    assert spec.rooms[room(spec, "dining")].open_to == ["kitchen"]
    assert "open_plan" in spec.design.priorities


def test_courtyard_is_recorded_as_the_requested_shape_not_dropped() -> None:
    """V1.3: a courtyard is a footprint shape the engine cannot build yet; it is recorded as
    the (mandatory) request, so it is refused with the reason instead of becoming a
    rectangle with a side note (building/footprint.py CAPABILITIES)."""
    draft = SpecificationDraft.model_validate(
        interpret_offline("Single-storey courtyard house of 180 m2 with 3 bedrooms.")
    )
    spec = draft.specification
    assert spec is not None and spec.design.footprint_shape == "courtyard"
    assert spec.priority_of("/design/footprint_shape") == "must"
    assert not any("ourtyard" in u for u in draft.unsupported_requests)


def test_window_and_facing_wishes_are_traced() -> None:
    spec = spec_of(
        "Contemporary two-storey house of 200 m2 with 3 bedrooms. Panoramic windows "
        "on the rear facade facing the garden, not on the street side. The living "
        "room should face the garden."
    )
    assert spec.trace("/design/windows") is not None
    face = spec.trace(f"/rooms/{room(spec, 'living')}/faces")
    assert face is not None and face.priority == "should" and face.quote is not None


def test_render_facade_color_is_read() -> None:
    spec = spec_of("Two-storey house of 170 m2 with 3 bedrooms and a light grey render facade.")
    assert spec.design.facade_color == "light_grey"
    assert spec.style.facade_material == "render"


def test_footprint_shape_requests_are_read_with_their_priority() -> None:
    # V1.3: asking for a shape outright is a requirement; softened wording a preference.
    plain = spec_of("A single-storey L-shaped house of 170 m2 with 3 bedrooms.")
    assert plain.design.footprint_shape == "l_shape"
    assert plain.priority_of("/design/footprint_shape") == "must"
    soft = spec_of("A single-storey house of 170 m2 with 3 bedrooms, ideally L-shaped.")
    assert soft.priority_of("/design/footprint_shape") == "should"
    required = spec_of("L-shaped bungalow, 160 m2, 3 bedrooms; the L shape is required.")
    trace = required.trace("/design/footprint_shape")
    assert (
        trace is not None and trace.priority == "must" and trace.quote == "the l shape is required"
    )
    rect = spec_of("Rectangular house of 120 m2 with 2 bedrooms.")
    assert rect.design.footprint_shape == "rectangular"


def test_an_l_without_storeys_is_assumed_single_storey() -> None:
    spec = spec_of("L-shaped house of 170 m2 with 3 bedrooms.")
    assert spec.targets.storeys == 1
    assert any(a.path == "/targets/storeys" for a in spec.assumptions)


def test_garden_words_alone_do_not_ask_for_an_l() -> None:
    spec = spec_of("Single-storey house of 150 m2 with 3 bedrooms facing the garden.")
    assert spec.design.footprint_shape is None
