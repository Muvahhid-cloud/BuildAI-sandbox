"""V7 bay-aware rooms (docs/3d-engine.md §16.17), measured on the built models.

Step 1 (quick wins): service windows take the wall's main width, windows of two rooms in one
bay are separated, upper stair windows stack on a window below. Each step has a switch that
reproduces main exactly.
"""

import itertools
import math
from functools import cache

import pytest

from app.modules.building.elements import Window
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
from tests.layout.test_facade_grid import aligned_upper_windows
from tests.layout.test_window_consistency import _openings

NAMES = [p.name for p in SPEC_PATHS]
STEP1_OFF = DEFAULT_CONFIG.model_copy(update={"window_quick_wins": False})

# geometry_sha256 of main at layout@1.14.0 (V6): every V7 switch off reproduces it.
MAIN_GEOMETRY = {
    "01": "176e30b32d072f84ebbcfeec3c4b6c54f1412dc9dea0d02d816f595e7ea65878",
    "02": "59c57fb0761a77e2d72d224ac2950da16aee0b8e4c33551c703083e2fa7f1b90",
    "03": "cc1a94126b92c2be2f9d7bffa0be62e93b5848d1216253a3176e010bf1013a26",
    "04": "523b7ba829b4e020d32f9fa7134f7b8fde25e479b6849762904dfc5c9305a7c5",
    "05": "071902a1ceeef43c01eb251ff079f384356b3733208d4c623bec0798b7fdd135",
    "06": "b93c583933b8d7201b9a5e2fc7a7846c6004e8d01c15bfbd757ac48e3eb8431b",
    "07": "7a0f50209be8c2a18e710b936b2d75afc927568711acae6480ac0fdc51e2f96f",
    "08": "63317a4b76be62f4d34c977f6b3ac0b79d3289d0b9a58d6b8609ea042cd98c00",
    "09": "b7956b83ab0dc3e07c951069bb8117fc84ee0b14ef382b90c7f89afd747dc939",
    "10": "02823db8233f34e793c656a9c621baefcdb2671784389cd8565f2a073c08a7d6",
    "11": "8cb4b800ea2458b2f432659803a512c339d60b73dfb387949962974ebd485e0b",
    "12": "e9e99368264af98ba2cd57f56e80ae6ced7be577d4946f36022992f989a01241",
}


@cache
def _gen(name: str, on: bool) -> LayoutResult:
    return generate_reference(
        DATA_DIR, SPECS_DIR / name, config=DEFAULT_CONFIG if on else STEP1_OFF
    )


def shared_bays(model: BuildingModel) -> int:
    """Pairs of windows (any rooms) on one exterior wall whose centres are less than half a
    bay apart."""
    axes = _bay_axes(model)
    by_wall: dict[str, list[float]] = {}
    bay: dict[str, float] = {}
    for el, host, a, b in _openings(model):
        if not isinstance(el, Window) or not host.semantic_key.startswith("wall:ext:"):
            continue
        horizontal = abs(math.sin(host.rotation.z)) < 0.5
        line = axes.get((horizontal, round(host.position.y if horizontal else host.position.x, 3)))
        bay[str(host.id)] = (line[1] - line[0]) if line and len(line) > 1 else 3.6
        by_wall.setdefault(str(host.id), []).append((a + b) / 2)
    n = 0
    for k, cs in by_wall.items():
        cs.sort()
        n += sum(1 for p, q in itertools.pairwise(cs) if q - p < bay[k] / 2)
    return n


@pytest.mark.parametrize("name", NAMES)
def test_step1_off_reproduces_main(name: str) -> None:
    assert geometry_sha256(_gen(name, on=False).model) == MAIN_GEOMETRY[name[:2]]


@pytest.mark.parametrize("name", NAMES)
def test_houses_stay_valid_and_within_the_rules(name: str) -> None:
    model = _gen(name, on=True).model
    issues = validate_model(model, material_ids=material_ids())
    assert errors(issues) == []
    assert not [i for i in issues if i.code == "ROOM_UNREACHABLE"]
    assert check_model(model, PROFILE) == []


def test_fewer_windows_of_two_rooms_in_one_bay() -> None:
    on = sum(shared_bays(_gen(n, on=True).model) for n in NAMES)
    off = sum(shared_bays(_gen(n, on=False).model) for n in NAMES)
    assert on < off


def test_service_windows_keep_their_privacy_sill() -> None:
    sill = DEFAULT_CONFIG.service_window[2]
    for name in NAMES:
        for el, _host, _a, _b in _openings(_gen(name, on=True).model):
            if (
                isinstance(el, Window)
                and el.properties.size_class is None
                and el.dimensions.height <= DEFAULT_CONFIG.service_window[1] + 1e-6
            ):
                assert el.position.z >= sill - 1e-6


def test_04_upper_corridor_window_stands_on_the_hall_window() -> None:
    a_on, _ = aligned_upper_windows(_gen("04-narrow-plot-townhouse.spec.json", on=True).model)
    a_off, _ = aligned_upper_windows(_gen("04-narrow-plot-townhouse.spec.json", on=False).model)
    assert a_on == a_off + 1


def test_stacking_stays_at_or_above_65_percent() -> None:
    multi = [n for n in NAMES if n[:2] in ("01", "04", "05", "06", "07", "08", "09")]
    a = t = 0
    for n in multi:
        x, y = aligned_upper_windows(_gen(n, on=True).model)
        a += x
        t += y
    assert a / t >= 0.65


def test_separating_windows_always_terminates() -> None:
    """Regression (V7 step 1): on the benchmark's T-shaped villa, separating windows of two
    rooms looped forever (a moved window formed a new pair and moved back). A window now moves
    at most once. Guarded by an alarm so a regression fails instead of hanging."""
    import json
    import signal

    from evals.design_benchmark import run_case

    data = json.loads(
        (DATA_DIR / "fixtures" / "benchmark" / "design-benchmark.v1.json").read_text("utf-8")
    )
    cases = data["cases"] if isinstance(data, dict) else data
    case = next(c for c in cases if c["id"] == "shape-t-villa")

    def timeout(_signum: int, _frame: object) -> None:
        raise TimeoutError("window separation did not terminate")

    previous = signal.signal(signal.SIGALRM, timeout)
    signal.alarm(120)
    try:
        result = run_case(case)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    assert result.status == "model"
