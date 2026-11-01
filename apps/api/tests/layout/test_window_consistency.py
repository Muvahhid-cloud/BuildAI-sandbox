"""V6 window consistency (docs/3d-engine.md §16.16), measured on the built models.

Step 1: no awkward pairs — no room has two windows in one bay of a facade line and storey;
openings keep the profile's openings.min_clearance_m. The switch off reproduces main
(layout@1.11.0) exactly.
"""

import itertools
import math
from functools import cache

import pytest

from app.modules.building.elements import Door, Wall, Window
from app.modules.building.fingerprint import geometry_sha256
from app.modules.building.model import BuildingModel
from app.modules.building.validation import errors, validate_model
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.engine import LayoutResult
from app.modules.layout.golden import generate_reference
from app.modules.rules.model_checks import check_model
from tests.building.helpers import DATA_DIR, SPECS_DIR, material_ids
from tests.layout.helpers import PROFILE, SPEC_PATHS
from tests.layout.test_bay_grid import _bay_axes

OFF = DEFAULT_CONFIG.model_copy(update={"window_consistency": False})
NAMES = [p.name for p in SPEC_PATHS]

# geometry_sha256 of main at layout@1.11.0 (V5): window_consistency off reproduces it.
MAIN_GEOMETRY = {
    "01": "d27a9337ac765740fe1febb9fb050edbdbfaa30454081199937739926eb0a78d",
    "02": "d9222db431e4ce0296ad53b53f5610ae235803becc5795e4871987d5c8917f55",
    "03": "6867b05d110fe8627b87ecf537567e5fe3ecf47432d7c1865885b35e54d6d607",
    "04": "517e8836a3739c82d86d5c7bdf34e85b2d38a4280bdd14e0d2bc0d969e095cee",
    "05": "b7a25520afe174264c46d1e07d5cf5a094ff6c5fdbf2b3ea6a0af6a7f1f49b75",
    "06": "53602a30fbc92f761f2edbe300d06d6c7f333189bd1c48822f7ac1d30ff406a6",
    "07": "b012622d0e8254846b82bd3d623673af3a5b98436ec33a05d3dc971b0d36a7f3",
    "08": "887ff9fa878609127c0999848b634982dc4a6aabdd7c6f34a7b399490b6689e2",
    "09": "13d90b346d0ed32678a295efca2e1fd61fa8d1ed78b7ade12cb539cad410e1fe",
    "10": "74cfd41b8305366bcc9d755931ffe9eb719c6871c0e38a5fcfe5811a719a17e0",
    "11": "e7bcb40e06e51ca7c5680083b00012664238469441550b9ad25219b4a24bca13",
    "12": "f78411f89175299d8974c18940c83cff30691d6f507b81b7ed74f97e00fec8c4",
}


@cache
def _gen(name: str, on: bool) -> LayoutResult:
    return generate_reference(DATA_DIR, SPECS_DIR / name, config=DEFAULT_CONFIG if on else OFF)


def _openings(model: BuildingModel) -> list[tuple[Window | Door, Wall, float, float]]:
    """(opening, host, start, end) along the host wall."""
    walls = {e.id: e for e in model.elements if isinstance(e, Wall)}
    out = []
    for el in model.elements:
        if isinstance(el, Window | Door):
            host = walls[next(r.target_id for r in el.relationships if r.kind == "hosted_by")]
            out.append((el, host, el.position.x, el.position.x + el.dimensions.width))
    return out


def same_room_pairs(model: BuildingModel) -> int:
    """Pairs of windows of one room on one facade line and storey whose centres are less
    than half a bay apart (two windows in one bay)."""
    axes = _bay_axes(model)
    groups: dict[tuple[str, str], list[float]] = {}
    for el, host, a, b in _openings(model):
        if not isinstance(el, Window) or not host.semantic_key.startswith("wall:ext:"):
            continue
        groups.setdefault((str(host.id), el.semantic_key.split(":")[1]), []).append((a + b) / 2)
    walls = {str(e.id): e for e in model.elements if isinstance(e, Wall)}
    pairs = 0
    for (wall_id, _room), centres in groups.items():
        w = walls[wall_id]
        horizontal = abs(math.sin(w.rotation.z)) < 0.5
        line = axes.get((horizontal, round(w.position.y if horizontal else w.position.x, 3)))
        bay = (line[1] - line[0]) if line and len(line) > 1 else 3.6
        centres.sort()
        pairs += sum(1 for p, q in itertools.pairwise(centres) if q - p < bay / 2)
    return pairs


@pytest.mark.parametrize("name", NAMES)
def test_switched_off_reproduces_main(name: str) -> None:
    assert geometry_sha256(_gen(name, on=False).model) == MAIN_GEOMETRY[name[:2]]


@pytest.mark.parametrize("name", NAMES)
def test_consistent_houses_stay_valid_and_within_the_rules(name: str) -> None:
    model = _gen(name, on=True).model
    issues = validate_model(model, material_ids=material_ids())
    assert errors(issues) == []
    assert not [i for i in issues if i.code == "ROOM_UNREACHABLE"]
    assert check_model(model, PROFILE) == []


@pytest.mark.parametrize("name", NAMES)
def test_no_room_has_two_windows_in_one_bay(name: str) -> None:
    assert same_room_pairs(_gen(name, on=True).model) == 0


def test_main_had_such_pairs() -> None:
    """The regression V6 fixes: e.g. 08's east facade, a 0.6 m window beside a 1.1 m one."""
    assert sum(same_room_pairs(_gen(n, on=False).model) for n in NAMES) >= 10


@pytest.mark.parametrize("name", NAMES)
def test_openings_keep_the_profile_clearance(name: str) -> None:
    assert PROFILE.openings is not None
    clearance = PROFILE.openings.min_clearance_m
    by_wall: dict[str, list[tuple[float, float]]] = {}
    for _, host, a, b in _openings(_gen(name, on=True).model):
        by_wall.setdefault(str(host.id), []).append((a, b))
    for spans in by_wall.values():
        spans.sort()
        for (_, b0), (a1, _) in itertools.pairwise(spans):
            assert a1 - b0 >= clearance - 1e-6


def test_a_released_window_gives_its_span_back() -> None:
    """Regression (V6 step 1): WallPlan.place stores (start, start + width) unrounded; the
    span must be freed even when start + width carries float noise."""
    from app.modules.building.enums import WallKind
    from app.modules.layout.build import WallPlan, _free_span
    from app.modules.layout.plan import Segment

    wall = WallPlan(
        "wall:ext:L0:S", "W", 0, (0.0, 0.0), (6.0, 0.0), WallKind.EXTERIOR, 0.3, "brick", "a", "b"
    )
    seg = Segment("h", 0.0, 0.0, 6.0)
    offset = wall.place(seg, 1.1, margin=0.3, center=0.1 + 0.2 + 1.85)
    assert offset is not None and wall.occupied
    _free_span(wall, offset, 1.1)
    assert wall.occupied == []


def habitable_widths_per_wall(model: BuildingModel) -> float:
    """Average number of distinct widths of habitable-room windows (those with a design size
    class) per exterior wall and storey."""
    widths: dict[str, set[float]] = {}
    for el, host, _a, _b in _openings(model):
        if (
            isinstance(el, Window)
            and el.properties.size_class is not None
            and host.semantic_key.startswith("wall:ext:")
        ):
            widths.setdefault(str(host.id), set()).add(round(el.dimensions.width, 2))
    return sum(len(v) for v in widths.values()) / max(len(widths), 1)


def test_one_main_width_per_facade_and_storey() -> None:
    """Step 2: fewer distinct habitable window widths per wall and storey than main."""
    on = [habitable_widths_per_wall(_gen(n, on=True).model) for n in NAMES]
    off = [habitable_widths_per_wall(_gen(n, on=False).model) for n in NAMES]
    assert sum(on) < sum(off)
    assert all(a <= b + 1e-9 for a, b in zip(on, off, strict=True))
