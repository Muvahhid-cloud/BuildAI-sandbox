"""V4 facade grid in the layout engine (layout@1.9.0, docs/3d-engine.md §16.14).

The storeys share a facade grid: room partitions snap to the partitions of the other storeys
where the rooms keep their minimums and permitted areas, windows are placed from the top
storey down and stack on shared axes, garden and terrace doors stand under an upper window
axis, and rooms below take rhythm windows under the axes above. The alignment is measured on
the built model, independently of the engine's own bookkeeping.
"""

import math

import pytest

from app.modules.building.elements import Door, Wall, Window
from app.modules.building.enums import DoorKind, RoomType, WallKind, Zone
from app.modules.building.model import BuildingModel
from app.modules.building.validation import errors, validate_model
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.golden import generate_reference
from app.modules.layout.plan import Column, Strip, StripLayout
from app.modules.layout.planner import Unit, facade_partitions, layout_strip
from app.modules.layout.program import RoomRequest
from app.modules.rules.model_checks import check_model
from tests.building.helpers import DATA_DIR, SPECS_DIR, material_ids
from tests.layout.helpers import PROFILE, reference

# Multi-storey reference houses (the single-storey ones have nothing to stack).
MULTI = [
    "01-family-house-280.spec.json",
    "04-narrow-plot-townhouse.spec.json",
    "05-three-storey-villa-360.spec.json",
    "06-no-area-given.spec.json",
    "07-panoramic-modern-200.spec.json",
    "08-classic-brick-220.spec.json",
    "09-small-two-storey-120.spec.json",
]


def _centre(model: BuildingModel, el: Window | Door) -> tuple[float, float, float, int]:
    """Plan centre of an opening, its host's direction and storey (measured on the model)."""
    walls = {e.id: e for e in model.elements if isinstance(e, Wall)}
    levels = {lv.id: lv.index for lv in model.levels}
    host = walls[next(r.target_id for r in el.relationships if r.kind == "hosted_by")]
    a = host.rotation.z
    c = el.position.x + el.dimensions.width / 2
    return (
        round(host.position.x + c * math.cos(a), 3),
        round(host.position.y + c * math.sin(a), 3),
        round(a, 3),
        levels[host.level_id] if host.level_id else 0,
    )


def aligned_upper_windows(model: BuildingModel) -> tuple[int, int]:
    """(aligned, total) windows in exterior walls above the ground floor; aligned = a window
    of a lower storey has the same plan centre (5 cm) on the same facade direction."""
    walls = {e.id: e for e in model.elements if isinstance(e, Wall)}
    windows = [e for e in model.elements if isinstance(e, Window)]

    def exterior(w: Window) -> bool:
        host = walls[next(r.target_id for r in w.relationships if r.kind == "hosted_by")]
        return host.properties.wall_kind == WallKind.EXTERIOR

    centres = [_centre(model, w) for w in windows]
    upper = [c for w, c in zip(windows, centres, strict=True) if c[3] > 0 and exterior(w)]
    aligned = sum(
        1
        for c in upper
        if any(
            d[3] < c[3] and abs(d[0] - c[0]) < 0.05 and abs(d[1] - c[1]) < 0.05 and d[2] == c[2]
            for d in centres
        )
    )
    return aligned, len(upper)


def test_most_upper_windows_stand_on_a_window_below() -> None:
    """Baseline layout@1.8.0 (V3 axis snapping only): 41 of 84. The grid must keep most."""
    aligned = total = 0
    for name in MULTI:
        a, t = aligned_upper_windows(reference(name).model)
        aligned += a
        total += t
    assert aligned >= 58 and aligned / total > 0.65, (aligned, total)


def test_switching_the_grid_off_restores_the_v3_composition() -> None:
    """facade_grid_snap = 0 is the layout@1.8.0 behaviour (V3 axes, storeys bottom up)."""
    # V5 adds the facade bays on top of the grid: both off is layout@1.8.0.
    off = DEFAULT_CONFIG.model_copy(update={"facade_grid_snap": 0.0, "facade_bays": False})
    aligned = total = 0
    for name in MULTI:
        a, t = aligned_upper_windows(
            generate_reference(DATA_DIR, SPECS_DIR / name, config=off).model
        )
        aligned += a
        total += t
    assert (aligned, total) == (41, 84)


@pytest.mark.parametrize("name", MULTI)
def test_grid_houses_stay_valid_and_within_the_rules(name: str) -> None:
    model = reference(name).model
    issues = validate_model(model, material_ids=material_ids())
    assert errors(issues) == []
    assert not [i for i in issues if i.code == "ROOM_UNREACHABLE"]
    assert check_model(model, PROFILE) == []


@pytest.mark.parametrize(
    "name",
    [
        "04-narrow-plot-townhouse.spec.json",
        "06-no-area-given.spec.json",
        "07-panoramic-modern-200.spec.json",
    ],
)
def test_a_garden_door_stands_under_an_upper_window_where_it_fits(name: str) -> None:
    """The garden door is centred on a window axis of the storey above (full width only; in
    05 and 08 no axis leaves room for the whole door, so it keeps its centre)."""
    model = reference(name).model
    door = next(
        e
        for e in model.elements
        if isinstance(e, Door)
        and e.properties.door_kind == DoorKind.SLIDING
        and _centre(model, e)[3] == 0
    )
    x, y, a, _ = _centre(model, door)
    above = [
        c
        for c in (_centre(model, w) for w in model.elements if isinstance(w, Window))
        if c[3] > 0 and c[2] == a and abs(c[1] - y) < 0.05
    ]
    assert any(abs(c[0] - x) < 0.05 for c in above), (x, above)


# --- partitions snap to the grid (planner) ---------------------------------------------------


def _room(
    key: str, area: float, *, low: float | None = None, high: float | None = None
) -> RoomRequest:
    return RoomRequest(
        key=key,
        spec_key=key,
        spec_index=0,
        type=RoomType.BEDROOM,
        name=key,
        target_area=area,
        explicit_target=low is not None,
        min_area=9.0,
        min_width=2.4,
        zone=Zone.PRIVATE,
        level=None,
        area_low=low,
        area_high=high,
    )


STRIP = Strip("N", 0.0, 9.0, 0.0, 4.0, "north")


def _widths(lay: StripLayout | None) -> list[float]:
    assert lay is not None
    return [c.width for c in lay.columns]


def test_partitions_snap_to_the_grid_of_the_storey_below() -> None:
    units = [Unit(_room("a", 12.0)), Unit(_room("b", 12.0)), Unit(_room("c", 16.0))]
    free = layout_strip(STRIP, units, DEFAULT_CONFIG)
    assert free is not None
    cuts = facade_partitions(free)
    # Both partitions 0.4 m east: "a" grows, "b" slides, "c" (the widest) gives the width.
    grid = [0.0, round(cuts[0] + 0.4, 3), round(cuts[1] + 0.4, 3), 9.0]
    snapped = layout_strip(STRIP, units, DEFAULT_CONFIG, grid)
    assert snapped is not None
    assert facade_partitions(snapped) == grid[1:3]
    assert math.isclose(sum(_widths(snapped)), STRIP.length)


def test_a_partition_beyond_the_snap_reach_stays() -> None:
    units = [Unit(_room("a", 18.0)), Unit(_room("b", 18.0))]
    free = layout_strip(STRIP, units, DEFAULT_CONFIG)
    far = layout_strip(STRIP, units, DEFAULT_CONFIG, [0.0, 2.6, 9.0])  # 1.9 m away
    assert _widths(free) == _widths(far)


def test_a_snap_never_breaks_a_minimum_or_a_permitted_area() -> None:
    # "a" may not grow beyond 19 m²: the grid line that would need 20 m² is refused.
    units = [Unit(_room("a", 18.0, low=17.0, high=19.0)), Unit(_room("b", 18.0))]
    free = layout_strip(STRIP, units, DEFAULT_CONFIG)
    capped = layout_strip(STRIP, units, DEFAULT_CONFIG, [0.0, 5.0, 9.0])
    assert _widths(free) == _widths(capped)
    # Neither room may drop below its 2.4 m minimum width.
    tight = layout_strip(STRIP, units, DEFAULT_CONFIG, [0.0, 6.7, 9.0])
    assert all(w >= 2.4 for w in _widths(tight))


def test_facade_partitions_ignore_tucked_rooms() -> None:
    owner, tuck = _room("bed", 14.0), _room("ensuite", 4.0)
    lay = StripLayout(
        STRIP,
        [
            Column("tuck", tuck, 2.0, 2.0, owner=owner),
            Column("main", owner, 3.0, 4.0),
            Column("main", _room("other", 16.0), 4.0, 4.0),
        ],
    )
    assert facade_partitions(lay) == [5.0]
