"""K3 in the layout engine: design intent and design systems change the generated model.

Everything is checked on the generated BuildingModel (walls, windows, rooms, materials), not on
the specification: the yellow facade must be on the walls, the panoramic windows on the rear
walls, the living spaces in the rear band — and the model must stay geometrically valid (K2.5).
"""

import os
import subprocess
import sys
from collections import Counter
from functools import cache
from typing import Any

import pytest

from app.modules.building.appearance import PALETTE
from app.modules.building.design_checks import check_model_design, window_facades
from app.modules.building.elements import Door, Furniture, Room, Wall, Window
from app.modules.building.enums import DoorKind, RoomType, WallKind
from app.modules.building.hosting import overlap
from app.modules.building.model import BuildingModel
from app.modules.building.specification import BuildingSpecification, FacadeSide, WindowStyle
from app.modules.building.summary import summarize
from app.modules.building.validation import errors, validate_model
from app.modules.catalog.design_systems import resolve_design
from app.modules.layout.engine import LayoutResult, generate_layout
from tests.building.helpers import DATA_DIR, material_ids
from tests.catalog.helpers import approved_design_registry
from tests.layout.helpers import NAMESPACE, PROFILE, generate

API_ROOT = DATA_DIR.parent / "apps" / "api"

# The program of the K3 live test, as a specification (what the AI is expected to produce).
LIVE_LIKE: dict[str, Any] = {
    "name": "Modern family house",
    "targets": {"storeys": 2, "gross_floor_area_m2": 220},
    "style": {"architectural_style": "modern", "roof": {"type": "gable", "pitch_deg": 30}},
    "rooms": [
        {
            "key": "living",
            "type": "living",
            "target_area_m2": 40,
            "level": 0,
            "faces": "rear",
            "adjacent_to": ["dining"],
        },
        {"key": "kitchen", "type": "kitchen", "level": 0, "open_to": ["dining"]},
        {"key": "dining", "type": "dining", "level": 0, "faces": "rear"},
        {"key": "guest_wc", "type": "wc", "level": 0},
        {"key": "laundry", "type": "laundry", "level": 0},
        {"key": "master", "type": "bedroom", "level": 1, "features": ["en_suite"]},
        {"key": "bedroom", "type": "bedroom", "count": 2, "level": 1},
        {"key": "bathroom", "type": "bathroom", "level": 1},
    ],
    "features": {"garage": {"cars": 2}},
    "design": {
        "facade_color": "yellow",
        "windows": {
            "emphasis": "panoramic",
            "preferred_facades": ["rear"],
            "excluded_facades": ["front"],
        },
    },
}


def with_changes(**changes: Any) -> dict[str, Any]:
    return {**LIVE_LIKE, **changes}


@cache
def live_like() -> LayoutResult:
    return generate(LIVE_LIKE)


@cache
def plain() -> LayoutResult:
    return generate(
        with_changes(
            design={},
            rooms=[{k: v for k, v in r.items() if k != "faces"} for r in LIVE_LIKE["rooms"]],
        )
    )


def designed(spec: dict[str, Any], design_id: str) -> LayoutResult:
    registry = approved_design_registry()
    resolution = resolve_design(registry, design_id)
    assert resolution.snapshot is not None and resolution.types is not None
    return generate_layout(
        BuildingSpecification.model_validate(spec),
        PROFILE,
        id_namespace=NAMESPACE,
        material_ids=material_ids(),
        type_set=resolution.types.type_set,
        design_system=resolution.snapshot,
    )


def exterior_walls(model: BuildingModel) -> list[Wall]:
    return [
        el
        for el in model.elements
        if isinstance(el, Wall) and el.properties.wall_kind == WallKind.EXTERIOR
    ]


def windows_by(model: BuildingModel) -> Counter[tuple[str | None, str | None]]:
    facades = window_facades(model)
    return Counter(
        (
            facades[w.id].value if facades[w.id] else None,  # type: ignore[union-attr]
            w.properties.size_class.value if w.properties.size_class else None,
        )
        for w in model.elements
        if isinstance(w, Window)
    )


# --- appearance -------------------------------------------------------------------------------


def test_yellow_facade_is_on_every_exterior_wall() -> None:
    model = live_like().model
    walls = exterior_walls(model)
    assert walls and {w.properties.finish_right_color for w in walls} == {PALETTE["yellow"]}
    garage = [w for w in walls if w.semantic_key.startswith("wall:garage:")]
    assert garage  # the garage facade is part of the house facade
    # Appearance only: the construction/finish material stays the render material.
    assert {w.material_id for w in walls} == {"exterior_wall"}
    assert {w.properties.finish_right_id for w in walls} == {"exterior_wall"}
    # Interior faces and interior walls are not colored.
    inner = [el for el in model.elements if isinstance(el, Wall) and el not in walls]
    assert all(w.properties.finish_left_color is None for w in walls)
    assert all(w.properties.finish_right_color is None for w in inner)
    assert model.design is not None and model.design.facade_color is not None
    assert model.design.facade_color.source == "user"
    assert summarize(model).facade_colors == [PALETTE["yellow"]]


def test_without_a_color_walls_keep_their_material_color() -> None:
    model = plain().model
    assert {w.properties.finish_right_color for w in exterior_walls(model)} == {None}
    assert model.design is None


def test_hex_color_is_accepted() -> None:
    model = generate(with_changes(design={"facade_color": "#336699"})).model
    assert {w.properties.finish_right_color for w in exterior_walls(model)} == {"#336699"}


# --- windows ------------------------------------------------------------------------------------


def test_panoramic_windows_are_on_the_rear_facade_only() -> None:
    counts = windows_by(live_like().model)
    assert counts[("rear", "panoramic")] >= 2
    panoramic_sides = {side for (side, size), n in counts.items() if size == "panoramic" and n}
    assert panoramic_sides == {"rear"}
    # The excluded front facade has main windows, but only standard ones.
    front_sizes = {size for (side, size) in counts if side == "front" and size is not None}
    assert front_sizes == {"standard"}


def test_without_intent_windows_follow_the_building_style_everywhere() -> None:
    model = generate(
        with_changes(design={}, style={"window_style": "panoramic", "roof": {"type": "gable"}})
    ).model
    sizes = {size for (_, size) in windows_by(model) if size is not None}
    assert sizes == {"panoramic"}


def test_large_windows_preferred_on_the_right_facade() -> None:
    model = generate(
        with_changes(design={"windows": {"emphasis": "large", "preferred_facades": ["right"]}})
    ).model
    counts = windows_by(model)
    assert counts[("right", "large")] >= 1
    assert {side for (side, size) in counts if size == "large"} == {"right"}


def test_windows_do_not_overlap_and_stay_inside_their_walls() -> None:
    model = live_like().model
    walls = {w.id: w for w in model.elements if isinstance(w, Wall)}
    hosted: dict[Any, list[tuple[float, float]]] = {}
    for el in model.elements:
        if isinstance(el, Window | Door):
            host = next(r.target_id for r in el.relationships if r.kind.value == "hosted_by")
            span = (el.position.x, el.position.x + el.dimensions.width)
            assert span[0] >= 0 and span[1] <= walls[host].dimensions.length + 1e-6
            if isinstance(el, Window):
                assert el.position.z + el.dimensions.height <= walls[host].dimensions.height
            hosted.setdefault(host, []).append(span)
    for spans in hosted.values():
        for i, a in enumerate(spans):
            for b in spans[i + 1 :]:
                assert overlap(a, b) <= 1e-6


def test_design_generation_passes_k2_5_and_design_checks() -> None:
    result = live_like()
    issues = validate_model(result.model, material_ids=material_ids())
    assert errors(issues) == []
    assert not [i for i in issues if i.code == "ROOM_UNREACHABLE"]
    assert check_model_design(result.model) == []
    assert not [w for w in result.warnings if w.code.startswith(("WINDOW_", "ROOM_FACADE"))]


def test_k2_5_rejects_an_invalid_window_placement() -> None:
    model = live_like().model
    target = next(
        w
        for w in model.elements
        if isinstance(w, Window) and w.properties.size_class == WindowStyle.PANORAMIC
    )
    moved = target.model_copy(
        update={"position": target.position.model_copy(update={"x": target.position.x + 50})}
    )
    broken = model.model_copy(
        update={"elements": [moved if el.id == target.id else el for el in model.elements]}
    )
    codes = {i.code for i in errors(validate_model(broken, material_ids=material_ids()))}
    assert codes  # the opening no longer fits its host wall
    assert any("OPENING" in c or "HOST" in c for c in codes), codes


def test_emphasised_window_on_an_excluded_facade_is_rejected() -> None:
    model = live_like().model
    facades = window_facades(model)
    target = next(
        w
        for w in model.elements
        if isinstance(w, Window)
        and facades[w.id] == FacadeSide.FRONT
        and w.properties.size_class == WindowStyle.STANDARD
    )
    tampered = target.model_copy(
        update={
            "properties": target.properties.model_copy(update={"size_class": WindowStyle.PANORAMIC})
        }
    )
    model = model.model_copy(
        update={"elements": [tampered if el.id == target.id else el for el in model.elements]}
    )
    issues = check_model_design(model)
    assert [i.code for i in issues] == ["WINDOW_FACADE_CONFLICT"]
    assert issues[0].element_id == target.id and issues[0].severity == "error"


def test_unsatisfiable_window_preference_is_reported() -> None:
    model = live_like().model
    assert model.design is not None and model.design.windows is not None
    design = model.design.model_copy(
        update={
            "windows": model.design.windows.model_copy(
                update={"preferred_facades": [FacadeSide.REAR, FacadeSide.LEFT]}
            )
        }
    )
    issues = check_model_design(model.model_copy(update={"design": design}))
    assert [(i.code, i.severity) for i in issues] == [
        ("WINDOW_PREFERENCE_UNSATISFIABLE", "warning")
    ]
    assert "left" in issues[0].message


def test_appearance_that_differs_from_the_design_record_is_rejected() -> None:
    model = live_like().model
    wall = exterior_walls(model)[0]
    tampered = wall.model_copy(
        update={"properties": wall.properties.model_copy(update={"finish_right_color": "#000000"})}
    )
    model = model.model_copy(
        update={"elements": [tampered if el.id == wall.id else el for el in model.elements]}
    )
    assert [i.code for i in check_model_design(model)] == ["APPEARANCE_INVALID"]


# --- rooms facing the garden -----------------------------------------------------------------


def test_living_and_dining_face_the_rear() -> None:
    result = live_like()
    rear = set(summarize(result.model).rooms_on_facade["rear"])
    assert {"room:living", "room:dining"} <= rear
    depth = result.metrics.footprint_depth_m  # type: ignore[union-attr]
    for el in result.model.elements:
        if isinstance(el, Room) and el.properties.room_type in (RoomType.LIVING, RoomType.DINING):
            assert max(el.position.y + p.y for p in el.properties.boundary) == pytest.approx(depth)


def test_room_facing_the_street_is_honoured() -> None:
    rooms = [dict(r) for r in LIVE_LIKE["rooms"]]
    rooms[0] = {**rooms[0], "faces": "front"}  # living room to the street side
    result = generate(with_changes(rooms=rooms, design={}))
    assert "room:living" in summarize(result.model).rooms_on_facade["front"]


# --- design systems (approved in a temporary copy only) ----------------------------------------


def test_design_system_changes_visible_choices() -> None:
    spec = with_changes(
        style={
            "architectural_style": "modern",
            "roof": {"type": "flat"},
            "design_system": "modern-minimal",
        },
        design={},
    )
    result = designed(spec, "modern-minimal")
    model = result.model
    assert errors(validate_model(model, material_ids=material_ids())) == []
    assert model.design is not None and model.design.design_system is not None
    assert model.design.design_system.id == "modern-minimal"
    # Design-system default facade color (white), no user color given.
    assert (
        model.design.facade_color is not None
        and model.design.facade_color.source == "design_system"
    )
    assert {w.properties.finish_right_color for w in exterior_walls(model)} == {PALETTE["white"]}
    floors = {
        el.properties.room_type: el.properties.floor_material_id
        for el in model.elements
        if isinstance(el, Room)
    }
    assert floors[RoomType.LIVING] == "oak_light" and floors[RoomType.BATHROOM] == "stone_tile"
    furniture = {el.material_id for el in model.elements if isinstance(el, Furniture)}
    assert "oak_light" in furniture and "wood" not in furniture
    entrance = next(
        el
        for el in model.elements
        if isinstance(el, Door) and el.properties.door_kind == DoorKind.ENTRANCE
    )
    assert entrance.type_ref == "type.door.minimal_entrance" and entrance.material_id == "metal"
    stair_railing = next(el for el in model.elements if el.semantic_key.startswith("railing:stair"))
    assert stair_railing.properties.railing_kind.value == "glass"  # type: ignore[union-attr]
    assert {t.id for t in model.types} <= set(model.design.design_system.type_ids)
    assert check_model_design(model) == []
    assert "design modern-minimal" in model.metadata.generator


def test_user_color_overrides_the_design_system_default() -> None:
    spec = with_changes(
        style={
            "architectural_style": "modern",
            "roof": {"type": "flat"},
            "design_system": "modern-minimal",
        },
        design={"facade_color": "yellow"},
    )
    model = designed(spec, "modern-minimal").model
    assert {w.properties.finish_right_color for w in exterior_walls(model)} == {PALETTE["yellow"]}
    assert model.design is not None and model.design.facade_color.source == "user"  # type: ignore[union-attr]


def test_classic_brick_system() -> None:
    spec = with_changes(
        style={
            "architectural_style": "classic",
            "roof": {"type": "hip"},
            "facade_material": "brick",
            "design_system": "classic-brick",
        },
        design={},
    )
    model = designed(spec, "classic-brick").model
    walls = exterior_walls(model)
    assert {w.material_id for w in walls} == {"brick"}
    assert {w.properties.finish_right_color for w in walls} == {None}  # brick keeps its color
    frames = {
        w.properties.frame_material_id
        for w in model.elements
        if isinstance(w, Window) and w.properties.size_class is not None
    }
    assert frames == {"window_frame_white"}


def test_off_system_finishes_are_rejected() -> None:
    spec = with_changes(
        style={
            "architectural_style": "modern",
            "roof": {"type": "flat"},
            "design_system": "modern-minimal",
        },
        design={},
    )
    model = designed(spec, "modern-minimal").model
    room = next(
        el
        for el in model.elements
        if isinstance(el, Room) and el.properties.room_type == RoomType.LIVING
    )
    tampered = room.model_copy(
        update={"properties": room.properties.model_copy(update={"floor_material_id": "parquet"})}
    )
    broken = model.model_copy(
        update={"elements": [tampered if el.id == room.id else el for el in model.elements]}
    )
    assert [i.code for i in check_model_design(broken)] == ["DESIGN_OFF_SYSTEM"]


# --- determinism --------------------------------------------------------------------------------


def test_design_generation_is_deterministic() -> None:
    a = generate(LIVE_LIKE).model.model_dump_json()
    b = generate(LIVE_LIKE).model.model_dump_json()
    assert a == b


def test_design_generation_does_not_depend_on_hash_seed() -> None:
    code = (
        "from tests.layout.test_design_layout import LIVE_LIKE, designed;"
        "from tests.layout.helpers import generate;"
        "import hashlib;"
        "spec = dict(LIVE_LIKE, style={'architectural_style': 'modern', 'roof': {'type': 'flat'},"
        " 'design_system': 'modern-minimal'});"
        "a = generate(LIVE_LIKE).model.model_dump_json();"
        "b = designed(spec, 'modern-minimal').model.model_dump_json();"
        "print(hashlib.sha256((a + b).encode()).hexdigest())"
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
