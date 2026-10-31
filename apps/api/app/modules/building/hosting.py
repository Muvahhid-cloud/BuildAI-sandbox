"""Host-relative geometry of wall openings (Phase 3.5 K2.5, docs/building-model.md §4.1).

Doors and windows are stored in host-wall coordinates (`position.x` = offset of the opening's
start edge along the wall axis, `position.z` = sill), i.e. as (host, offset, width, sill,
height). This module holds the interval arithmetic on that representation. The geometric
checks use it to validate openings, and the layout engine uses the same functions to place
them, so the engine cannot choose a position the validator would reject.

Intervals are (start, end) offsets along a wall axis in meters, start <= end.
"""

from collections.abc import Iterable, Sequence

from app.modules.building.elements import Door, Window
from app.modules.building.geometry import Point
from app.modules.building.primitives import EPS

Interval = tuple[float, float]
Axis = tuple[Point, Point]


def opening_span(opening: Door | Window) -> Interval:
    """Along the host axis: [offset, offset + width]."""
    return opening.position.x, opening.position.x + opening.dimensions.width


def opening_rise(opening: Door | Window) -> Interval:
    """Vertically, from the host wall's base: [sill, sill + height]."""
    return opening.position.z, opening.position.z + opening.dimensions.height


def overlap(a: Interval, b: Interval) -> float:
    """Length of the overlap of two intervals (0 when they only touch or are apart)."""
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for lo, hi in sorted(intervals):
        if out and lo <= out[-1][1] + EPS:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def free_intervals(
    spans: Iterable[Interval], occupied: Iterable[Interval], gap: float = 0.0
) -> list[Interval]:
    """Parts of `spans` that keep at least `gap` from every occupied interval."""
    free = list(spans)
    for o0, o1 in sorted(occupied):
        nxt: list[Interval] = []
        for f0, f1 in free:
            if o1 + gap <= f0 or o0 - gap >= f1:
                nxt.append((f0, f1))
                continue
            if o0 - gap > f0:
                nxt.append((f0, o0 - gap))
            if o1 + gap < f1:
                nxt.append((o1 + gap, f1))
        free = nxt
    return free


def junction_zones(
    axis: Axis, body: Interval, others: Iterable[tuple[Axis, float]]
) -> list[Interval]:
    """Stretches of a wall's axis occupied by the bodies of other walls that meet it: an
    L-corner or T-junction (the other wall ends inside this wall's body) or a crossing. Each
    zone is the other wall's thickness around the meeting point, clipped to the wall. `body` is
    the wall's extent across its axis (v0, v1; +v = left face). Collinear and parallel walls
    create no zones. An opening inside a zone would cut into the other wall.
    """
    (sx, sy), (ex, ey) = axis
    length = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
    if length < EPS:
        return []
    ux, uy = (ex - sx) / length, (ey - sy) / length
    zones: list[Interval] = []

    def local(p: Point) -> tuple[float, float]:
        dx, dy = p[0] - sx, p[1] - sy
        return dx * ux + dy * uy, -dx * uy + dy * ux

    for (a, b), other_t in others:
        (au, av), (bu, bv) = local(a), local(b)
        if abs(av - bv) < EPS:  # parallel (incl. collinear)
            continue
        hits: list[float] = []
        for u, v in ((au, av), (bu, bv)):
            if body[0] - EPS <= v <= body[1] + EPS and -EPS <= u <= length + EPS:
                hits.append(u)
        if not hits and av * bv < 0:  # crossing: the other axis passes through this one
            u = au + (bu - au) * av / (av - bv)
            if -EPS <= u <= length + EPS:
                hits.append(u)
        for u in hits:
            lo, hi = max(0.0, u - other_t / 2), min(length, u + other_t / 2)
            if hi > lo:
                zones.append((lo, hi))
    return merge(zones)


def overlapping(intervals: Sequence[Interval], candidate: Interval) -> list[int]:
    """Indices of `intervals` that overlap `candidate` by more than EPS."""
    return [i for i, iv in enumerate(intervals) if overlap(iv, candidate) > EPS]
