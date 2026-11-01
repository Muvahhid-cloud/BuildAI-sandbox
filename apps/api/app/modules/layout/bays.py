"""Facade bay grid (V5, docs/3d-engine.md §16.15).

Every facade line of the house (its exterior walls on one line, on every storey) is divided into
equal bays whose width lies in `LayoutConfig.bay_min_m`..`bay_max_m`; window axes stand at the
bay centres. Pure arithmetic on plan coordinates (no I/O, no randomness): the same walls give
the same grid.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.modules.layout.config import LayoutConfig
from app.modules.layout.plan import Skeleton, envelope, rnd

EPS = 1e-6


@dataclass(frozen=True)
class Bays:
    """The bay grid of one facade line: `count` bays of `width` from `start` to `end`."""

    start: float
    end: float
    count: int

    @property
    def width(self) -> float:
        return (self.end - self.start) / self.count

    @property
    def axes(self) -> list[float]:
        """Plan coordinates of the bay centres, along the line, ascending (1 mm)."""
        return [rnd(self.start + (i + 0.5) * self.width) for i in range(self.count)]

    @property
    def lines(self) -> list[float]:
        """Bay boundaries including both ends (1 mm)."""
        return [rnd(self.start + i * self.width) for i in range(self.count + 1)]


def bay_count(length: float, config: LayoutConfig) -> int:
    """Number of bays for a facade of `length`: a bay width within the configured range,
    closest to its middle; outside the range the nearest fit (at least one bay)."""
    lo, hi = config.bay_min_m, config.bay_max_m
    mid = (lo + hi) / 2
    best: tuple[float, float, int] | None = None
    for n in range(1, max(1, int(length / max(lo, EPS))) + 2):
        b = length / n
        outside = max(lo - b, b - hi, 0.0)
        key = (round(outside, 6), round(abs(b - mid), 6), n)
        if best is None or key < best:
            best = key
    return best[2] if best is not None else 1


def bays_of(start: float, end: float, config: LayoutConfig) -> Bays:
    lo, hi = sorted((start, end))
    return Bays(lo, hi, bay_count(hi - lo, config))


def facade_lines(
    walls: Iterable[tuple[bool, float, float, float]], config: LayoutConfig
) -> dict[tuple[bool, float], Bays]:
    """Bay grid per facade line from exterior walls given as (horizontal, line coordinate,
    plan start, plan end); the line's extent is the union over all storeys."""
    extent: dict[tuple[bool, float], tuple[float, float]] = {}
    for horizontal, coord, a, b in walls:
        key = (horizontal, rnd(coord))
        lo, hi = sorted((a, b))
        if key in extent:
            lo, hi = min(lo, extent[key][0]), max(hi, extent[key][1])
        extent[key] = (lo, hi)
    return {k: bays_of(lo, hi, config) for k, (lo, hi) in sorted(extent.items())}


def skeleton_bays(sk: Skeleton, config: LayoutConfig) -> dict[tuple[bool, float], Bays]:
    """Bay grid of every facade line of a skeleton's envelope (the planner's view; the
    built walls give the same lines)."""
    walls = []
    for _, (x0, y0), (x1, y1), _roof in envelope(sk, pitched=False):
        horizontal = abs(y1 - y0) < EPS
        walls.append(
            (
                horizontal,
                y0 if horizontal else x0,
                x0 if horizontal else y0,
                x1 if horizontal else y1,
            )
        )
    return facade_lines(walls, config)
