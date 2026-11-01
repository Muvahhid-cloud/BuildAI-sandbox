"""V5 facade bay grid (docs/3d-engine.md §16.15).

Each facade line is divided into equal bays (LayoutConfig.bay_min_m..bay_max_m); windows stand
on the bay centres with one width per facade and storey. Measured on the built model with an
independent bay computation (the engine never grades itself).
"""

import math
from functools import cache

import pytest

from app.modules.building.elements import Wall, Window
from app.modules.building.fingerprint import geometry_sha256
from app.modules.building.model import BuildingModel
from app.modules.building.validation import errors, validate_model
from app.modules.layout.bays import Bays, bay_count, bays_of
from app.modules.layout.config import DEFAULT_CONFIG, LayoutConfig
from app.modules.layout.engine import LayoutResult
from app.modules.layout.golden import generate_reference
from app.modules.rules.model_checks import check_model
from tests.building.helpers import DATA_DIR, SPECS_DIR, material_ids
from tests.layout.helpers import PROFILE, SPEC_PATHS

ON = DEFAULT_CONFIG.model_copy(update={"facade_bays": True})
OFF = DEFAULT_CONFIG.model_copy(update={"facade_bays": False})

# geometry_sha256 of main at layout@1.9.0 (V4, before V5): the bay grid switched off must
# reproduce it exactly.
MAIN_GEOMETRY = {
    "01": "38cae1aa6091b02bc973e7674c6b83ab00bf9f768e3b6f6ad2e5d483e76a3da3",
    "02": "24b5761f78f6c7ccaad52366a676b89369cc9039039dd57c8b592bcc93bb7f46",
    "03": "4ac26ea6ba01a0a49966b9bc464d05b9f906166e8a0ac5c494d5b2ccc36e116c",
    "04": "8a02bfc6587a54cdf10d5fc55d62e08b827ce7175bfac2c082ecf64c2c3e582d",
    "05": "f7d8b48bec05d6ce240e9914da95ca3fecaa512f0fe301cc9c69c1f43503bd07",
    "06": "5bc878ee9a792c585351bf6889fa84762e21c7a8aed4872d80888f1fd563bb05",
    "07": "3469a95837e90f38c2b19e490e3eb58722579cebc6730841b3eb29cf672e2a1c",
    "08": "300cfea2cddb7216185e9c0d7d1bf47c999276629eafcbff6fec1a06c828fb8e",
    "09": "4e98450d82c1203d6300a30ba0bc1cf7e5dc32f3aafa46484132e29be0f2246b",
    "10": "4837e9536b67055bcc99229e9772be18cb31bbb68035dd4a3f2d2b4aab9dab45",
    "11": "4ad013ba7df5b5c2cabe012c7d3e02c29d7baa7294fb7621c992df2daf26ef54",
    "12": "3a2ee62ca00773463914e7e7d5360bd18282e9f6c783b2a44fa84e7e3b3f2405",
}
NAMES = [p.name for p in SPEC_PATHS]


@cache
def _gen(name: str, bays: bool) -> LayoutResult:
    return generate_reference(DATA_DIR, SPECS_DIR / name, config=ON if bays else OFF)


# --- bay arithmetic ---------------------------------------------------------------------------


def test_bays_are_equal_and_within_the_configured_range() -> None:
    for length in (6.0, 7.15, 9.05, 10.6, 13.2, 15.55, 21.0):
        b = bays_of(0.0, length, DEFAULT_CONFIG)
        assert DEFAULT_CONFIG.bay_min_m - 1e-9 <= b.width <= DEFAULT_CONFIG.bay_max_m + 1e-9
        assert math.isclose(b.width * b.count, length)
        assert b.axes == sorted(b.axes)
        assert all(
            math.isclose(b.axes[i + 1] - b.axes[i], b.width, abs_tol=2e-3)
            for i in range(b.count - 1)
        )


def test_a_facade_no_count_fits_takes_the_nearest_fit() -> None:
    # 8.45 m: 2 x 4.225 (0.025 above the range) beats 3 x 2.817 (0.183 below).
    assert bay_count(8.45, DEFAULT_CONFIG) == 2


def test_bay_count_takes_the_width_nearest_the_middle_of_the_range() -> None:
    assert bay_count(10.6, DEFAULT_CONFIG) == 3  # 3.53 m (2 x 5.3 and 4 x 2.65 are outside)
    assert bay_count(13.2, DEFAULT_CONFIG) == 4  # 3.30 m (3 x 4.4 is outside)
    assert bay_count(2.0, DEFAULT_CONFIG) == 1  # shorter than a bay: one axis in the middle
    wide = LayoutConfig.model_validate({**DEFAULT_CONFIG.model_dump(), "bay_max_m": 6.0})
    assert bay_count(10.6, wide) == 2  # 5.3 m is now nearer the middle of 3.0-6.0


def test_bay_lines_close_the_facade() -> None:
    b = Bays(1.0, 11.0, 4)
    assert b.lines == [1.0, 3.5, 6.0, 8.5, 11.0]
    assert b.axes == [2.25, 4.75, 7.25, 9.75]


# --- measured on the built model ----------------------------------------------------------------


def _bay_axes(model: BuildingModel) -> dict[tuple[bool, float], list[float]]:
    """Bay axes per facade line from the model's house exterior walls (independent of
    layout/bays.py: same rule, computed here from the stored walls)."""
    lo_b, hi_b = DEFAULT_CONFIG.bay_min_m, DEFAULT_CONFIG.bay_max_m
    extent: dict[tuple[bool, float], tuple[float, float]] = {}
    for w in model.elements:
        if not isinstance(w, Wall) or not w.semantic_key.startswith("wall:ext:"):
            continue
        a = w.rotation.z
        horizontal = abs(math.sin(a)) < 0.5
        x0, y0 = w.position.x, w.position.y
        x1, y1 = x0 + w.dimensions.length * math.cos(a), y0 + w.dimensions.length * math.sin(a)
        key = (horizontal, round(y0 if horizontal else x0, 3))
        s0, s1 = sorted((x0, x1) if horizontal else (y0, y1))
        lo, hi = extent.get(key, (s0, s1))
        extent[key] = (min(lo, s0), max(hi, s1))
    out: dict[tuple[bool, float], list[float]] = {}
    for key, (lo, hi) in extent.items():
        length = hi - lo
        n = min(
            range(1, int(length / lo_b) + 3),
            key=lambda n: (
                round(max(lo_b - length / n, length / n - hi_b, 0.0), 6),
                round(abs(length / n - (lo_b + hi_b) / 2), 6),
                n,
            ),
        )
        out[key] = [lo + (i + 0.5) * length / n for i in range(n)]
    return out


def windows_on_bays(model: BuildingModel) -> tuple[int, int]:
    """(on a bay axis within 5 cm, all) windows in the house's exterior walls."""
    walls = {e.id: e for e in model.elements if isinstance(e, Wall)}
    axes = _bay_axes(model)
    on = total = 0
    for w in model.elements:
        if not isinstance(w, Window):
            continue
        host = walls[next(r.target_id for r in w.relationships if r.kind == "hosted_by")]
        if not host.semantic_key.startswith("wall:ext:"):
            continue
        a = host.rotation.z
        horizontal = abs(math.sin(a)) < 0.5
        c = w.position.x + w.dimensions.width / 2
        x, y = host.position.x + c * math.cos(a), host.position.y + c * math.sin(a)
        key = (horizontal, round(y if horizontal else x, 3))
        along = x if horizontal else y
        total += 1
        on += any(abs(along - ax) < 0.05 for ax in axes.get(key, []))
    return on, total


@pytest.mark.parametrize("name", NAMES)
def test_bays_off_reproduce_main_exactly(name: str) -> None:
    assert geometry_sha256(_gen(name, bays=False).model) == MAIN_GEOMETRY[name[:2]]


@pytest.mark.parametrize("name", NAMES)
def test_bay_grid_houses_stay_valid_and_within_the_rules(name: str) -> None:
    model = _gen(name, bays=True).model
    issues = validate_model(model, material_ids=material_ids())
    assert errors(issues) == []
    assert not [i for i in issues if i.code == "ROOM_UNREACHABLE"]
    assert check_model(model, PROFILE) == []


def test_windows_move_onto_the_bay_axes() -> None:
    """Step 1 (windows only): off 8/149 on a bay axis; on, most rooms that hold an axis use it."""
    on = sum(windows_on_bays(_gen(n, bays=True).model)[0] for n in NAMES)
    off = sum(windows_on_bays(_gen(n, bays=False).model)[0] for n in NAMES)
    assert on >= off + 40, (on, off)
