"""Property-based invariants of the layout engine (Hypothesis).

For any in-scope specification the engine either reports a user-fixable infeasibility or
returns a model that satisfies every model invariant, where every room is reachable from the
entrance, every requested room exists, and which is reproducible.
"""

from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from shapely import Polygon, box

from app.modules.building.elements import Room
from app.modules.building.enums import Zone
from app.modules.building.geometry import to_absolute
from app.modules.building.validation import validate_model
from app.modules.layout.engine import LayoutError
from tests.layout.helpers import generate

OPTIONAL = ["study", "wc", "laundry", "storage", "dining"]


@st.composite
def specs(draw: st.DrawFn) -> dict[str, Any]:
    storeys = draw(st.integers(1, 3))
    bedrooms = draw(st.integers(1, 5))
    rooms: list[dict[str, Any]] = [
        draw(
            st.sampled_from(
                [
                    {"key": "kitchen_living", "type": "open_kitchen_living"},
                    {"key": "kitchen", "type": "kitchen"},
                ]
            )
        ),
        {"key": "bedroom", "type": "bedroom", "count": bedrooms},
        {"key": "bathroom", "type": "bathroom", "count": draw(st.integers(1, 3))},
    ]
    if rooms[0]["type"] == "kitchen":
        rooms.append({"key": "living", "type": "living", "open_to": ["kitchen"]})
    for extra in draw(st.lists(st.sampled_from(OPTIONAL), unique=True, max_size=3)):
        rooms.append({"key": extra, "type": extra})
    if draw(st.booleans()):
        rooms[1] = {**rooms[1], "count": 1, "key": "bedroom"}
        rooms.append({"key": "master", "type": "bedroom", "features": ["en_suite"]})
    features: dict[str, Any] = {}
    if draw(st.booleans()):
        features["garage"] = {"cars": draw(st.integers(1, 2))}
    if storeys > 1 and draw(st.booleans()):
        features["balconies"] = [{"level": storeys - 1}]
    if draw(st.booleans()):
        features["terrace"] = {}
    gfa = draw(st.one_of(st.none(), st.integers(60, 120).map(lambda a: a * storeys * 1.0 + 20)))
    return {
        "name": "Property test",
        "targets": {"storeys": storeys, "gross_floor_area_m2": gfa},
        "style": {"roof": {"type": draw(st.sampled_from(["flat", "gable", "hip"]))}},
        "rooms": rooms,
        "features": features,
    }


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
    derandomize=True,  # reproducible in CI
)
@given(spec=specs(), seed=st.integers(0, 1000))
def test_generated_models_hold_the_invariants(spec: dict[str, Any], seed: int) -> None:
    try:
        result = generate(spec, seed=seed)
    except LayoutError as exc:
        assert exc.code == "LAYOUT_INFEASIBLE", exc.issues  # never an engine bug
        return
    model = result.model
    issues = validate_model(model)
    assert [i.message for i in issues if i.severity == "error"] == []
    assert [i.message for i in issues if i.code == "ROOM_UNREACHABLE"] == []

    # Every requested room exists.
    rooms = [el for el in model.elements if isinstance(el, Room)]
    for req in spec["rooms"]:
        n = sum(1 for r in rooms if r.semantic_key.startswith(f"room:{req['key']}"))
        assert n >= req.get("count", 1), req["key"]

    # Indoor rooms stay inside the house footprint (+ garage); no two rooms overlap
    # (validated), and all ids are unique (validated).
    metrics = result.metrics
    assert metrics is not None
    footprint = box(-10, 0, metrics.footprint_width_m + 10, metrics.footprint_depth_m)
    for r in rooms:
        if r.properties.zone == Zone.EXTERIOR:
            continue
        poly = Polygon(to_absolute(r.properties.boundary, r.position, r.rotation))
        assert footprint.buffer(1e-6).contains(poly), r.name

    # Reproducible.
    again = generate(spec, seed=seed)
    assert again.model.model_dump_json() == model.model_dump_json()
