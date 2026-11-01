"""Plain data structures shared by the planner (abstract plan) and the builder (elements).

Plan coordinates are level-plan meters on wall centerlines: x east, y north, street on the south
(y = 0). The house footprint is the rectangle [0, W] x [0, D] (topology "rect"), or that main
bar plus a wing on the garden side (single storey): at its west or east end (topology "l",
docs/3d-engine.md §16.10) or from its middle (topology "t", §16.12). The wing spans x in
`wing_x` and y in [D, D + wing_length]. An
attached garage sits outside the footprint on the ground floor, balconies and terraces outside
it on the garden or street side.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from app.modules.building.enums import RoomType, Zone
from app.modules.layout.program import RoomRequest

EPS = 1e-6


def rnd(v: float) -> float:
    """Round to 1 mm (all plan coordinates)."""
    return round(v, 3) + 0.0


def snap(v: float, grid: float) -> float:
    return rnd(round(v / grid) * grid)


def snap_up(v: float, grid: float) -> float:
    return rnd(math.ceil(v / grid - 1e-9) * grid)


def snap_down(v: float, grid: float) -> float:
    return rnd(math.floor(v / grid + 1e-9) * grid)


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.w * self.h

    def contains(self, x: float, y: float) -> bool:
        return self.x0 - EPS <= x <= self.x1 + EPS and self.y0 - EPS <= y <= self.y1 + EPS

    def strictly_contains(self, x: float, y: float) -> bool:
        return self.x0 + EPS < x < self.x1 - EPS and self.y0 + EPS < y < self.y1 - EPS


@dataclass(frozen=True)
class StairDesign:
    risers: int
    riser: float
    tread: float
    run: float
    width: float
    lane_width: float  # centerline width of one stair lane in the core


@dataclass(frozen=True)
class Skeleton:
    """Global dimensions shared by every level of a candidate."""

    W: float
    D: float
    Ds: float  # south (street) band depth
    C: float  # corridor band depth
    storeys: int
    core_x0: float  # stair core [core_x0, core_x0 + lanes * lane_width]
    lanes: int
    lane_width: float
    hall_x0: float  # ground-floor entrance hall part (without the core)
    hall_x1: float
    hall_side: Literal["west", "east"]  # side of the hall part relative to the core
    garage_side: Literal["west", "east"] | None
    # L / T topology (single storey): a wing of `wing_depth` rooms plus a gallery corridor (C)
    # beside them, reaching `wing_length` beyond the main bar's garden facade. L: the wing at
    # the `wing_side` end, its rooms on the outer side. T: the wing starts at x = `wing_x0`
    # (both main-bar ends stay free), its rooms on its `wing_side` half.
    topology: Literal["rect", "l", "t"] = "rect"
    wing_side: Literal["west", "east"] | None = None
    wing_depth: float = 0.0
    wing_length: float = 0.0
    wing_x0: float = 0.0  # T only

    @property
    def Dn(self) -> float:  # noqa: N802 - plan dimension name
        return rnd(self.D - self.Ds - self.C)

    @property
    def is_l(self) -> bool:
        return self.topology == "l"

    @property
    def has_wing(self) -> bool:
        """L or T: a wing beyond the main bar's garden facade."""
        return self.topology in ("l", "t")

    @property
    def wing_width(self) -> float:
        """Wing rooms + gallery corridor (x extent of the wing)."""
        return rnd(self.wing_depth + self.C) if self.has_wing else 0.0

    @property
    def depth_total(self) -> float:
        return rnd(self.D + self.wing_length) if self.has_wing else self.D

    @property
    def footprint_area(self) -> float:
        """Area enclosed by the exterior wall centerlines of one storey."""
        return self.W * self.D + self.wing_width * self.wing_length

    @property
    def wing_x(self) -> tuple[float, float]:
        """x-range of the wing (rooms + gallery)."""
        if self.topology == "t":
            return self.wing_x0, rnd(self.wing_x0 + self.wing_width)
        if self.wing_side == "west":
            return 0.0, self.wing_width
        return rnd(self.W - self.wing_width), self.W

    @property
    def wing_rooms_x(self) -> tuple[float, float]:
        """x-range of the wing's room band (L: the outer side; T: the `wing_side` half)."""
        x0, x1 = self.wing_x
        if self.wing_side == "west":
            return x0, rnd(x0 + self.wing_depth)
        return rnd(x1 - self.wing_depth), x1

    @property
    def gallery_x(self) -> tuple[float, float]:
        """x-range of the wing's corridor (beside its rooms; L: the inner, garden side)."""
        x0, x1 = self.wing_x
        if self.wing_side == "west":
            return rnd(x0 + self.wing_depth), x1
        return x0, rnd(x1 - self.wing_depth)

    @property
    def garden_ranges(self) -> list[tuple[float, float]]:
        """x-ranges over which the main bar's north (garden) wall is a facade, west first:
        rect one, L one (beside the wing), T two (either side of the wing)."""
        if not self.has_wing:
            return [(0.0, self.W)]
        x0, x1 = self.wing_x
        return [r for r in ((0.0, x0), (x1, self.W)) if r[1] - r[0] > EPS]

    @property
    def garden_x(self) -> tuple[float, float]:
        """The (longest) x-range of the main bar's garden facade."""
        return max(self.garden_ranges, key=lambda r: (r[1] - r[0], -r[0]))

    @property
    def core_x1(self) -> float:
        return rnd(self.core_x0 + self.lanes * self.lane_width)

    @property
    def group_x0(self) -> float:  # hall part + core
        return min(self.core_x0, self.hall_x0)

    @property
    def group_x1(self) -> float:
        return max(self.core_x1, self.hall_x1)

    def lane(self, flight: int) -> tuple[float, float]:
        """Centerline x-range of the lane used by `flight` (0 = ground -> first floor).

        Flight 0 takes the lane farthest from the hall part so its open side faces the hall.
        """
        order = list(range(self.lanes))
        slot = order.index(flight)
        if self.hall_side == "west":  # hall | lane k-1 ... lane 0 | (east)
            slot = self.lanes - 1 - slot
        x0 = rnd(self.core_x0 + slot * self.lane_width)
        return x0, rnd(x0 + self.lane_width)


Side = Literal["north", "south", "wing"]


@dataclass(frozen=True)
class Strip:
    """A band of rooms laid side by side along `axis`, each spanning the band's depth from the
    corridor to the facade. Bands along x: north (corridor at y0) and south (corridor at y1);
    the L wing's band runs along y with the gallery corridor at its inner x edge."""

    name: Literal["N", "N2", "SL", "SR", "WG"]  # N2: the T's second garden band
    x0: float
    x1: float
    y0: float
    y1: float
    side: Side  # facade side of the strip
    axis: Literal["x", "y"] = "x"  # direction the rooms are laid along
    corridor_low: bool = True  # the corridor is on the low-coordinate edge across the band
    # Width of the corridor beside the band that the band's last room may wrap across (the L
    # wing's gallery, V1.2): that corridor then ends a door's width into the last room.
    end_wrap_depth: float = 0.0

    @property
    def length(self) -> float:
        return rnd(self.x1 - self.x0) if self.axis == "x" else rnd(self.y1 - self.y0)

    @property
    def depth(self) -> float:
        return rnd(self.y1 - self.y0) if self.axis == "x" else rnd(self.x1 - self.x0)

    @property
    def start(self) -> float:
        """Plan coordinate where the first room of the band starts (along the axis)."""
        return self.x0 if self.axis == "x" else self.y0


ColumnKind = Literal["main", "tuck", "full"]


@dataclass
class Column:
    kind: ColumnKind
    room: RoomRequest
    width: float
    depth: float  # tucks: depth from the corridor edge; others: the strip depth
    owner: RoomRequest | None = None  # tucks: the room that takes the facade-side remainder


@dataclass
class StripLayout:
    strip: Strip
    columns: list[Column]
    # > 0: the last column's room wraps across the corridor beside the band
    # (strip.end_wrap_depth) from this distance after its start; the corridor stops there, so
    # the room's door sits on that stretch (docs/3d-engine.md §16.10).
    wrap_from: float = 0.0
    # The ordered units the band was laid out from (planner.Unit; V5 re-lays the chosen
    # candidate's bands on the facade bays from them). Not part of the plan's geometry.
    units: tuple[Any, ...] = ()

    @property
    def corridor_end(self) -> float:
        """Plan coordinate (along the band) where the corridor beside the band ends."""
        if self.wrap_from <= 0.0:
            return rnd(self.strip.start + self.strip.length)
        return rnd(self.strip.start + sum(c.width for c in self.columns[:-1]) + self.wrap_from)


@dataclass(frozen=True)
class CorridorCut:
    """A dead end of the main corridor, [x0, x1] x [Ds, Ds + C], given to the room `owner`
    (L plans, V1.2, docs/3d-engine.md §16.10). The corridor still reaches every door; `joins`
    are the two rooms that now share a wall where the corridor used to separate them."""

    x0: float
    x1: float
    owner: str
    joins: tuple[str, str]

    @property
    def length(self) -> float:
        return rnd(self.x1 - self.x0)


@dataclass
class LevelLayout:
    index: int
    strips: list[StripLayout]
    merged_strips: list[Strip] = field(default_factory=list)  # empty strips given to circulation
    cuts: list[CorridorCut] = field(default_factory=list)  # corridor dead ends given to rooms


@dataclass
class Candidate:
    order: int
    skeleton: Skeleton
    levels: list[LevelLayout]
    score: float
    areas: dict[str, float]  # room key -> area


RegionKind = Literal["room", "void"]


@dataclass
class Region:
    key: str  # semantic suffix: the room element's semantic key is f"room:{key}"
    kind: RegionKind
    rects: list[Rect]
    level: int
    name: str
    room_type: RoomType | None = None
    zone: Zone | None = None
    request: RoomRequest | None = None
    inside: bool = True  # inside the house footprint (interior walls are derived for these)

    @property
    def area(self) -> float:
        return sum(r.area for r in self.rects)

    def contains(self, x: float, y: float) -> bool:
        return any(r.contains(x, y) for r in self.rects)

    def strictly_contains(self, x: float, y: float) -> bool:
        return any(r.strictly_contains(x, y) for r in self.rects)


@dataclass(frozen=True)
class Segment:
    """Axis-aligned plan segment: horizontal (y = const) or vertical (x = const)."""

    orientation: Literal["h", "v"]
    coord: float
    a0: float
    a1: float

    @property
    def length(self) -> float:
        return self.a1 - self.a0

    def covers(self, other: "Segment") -> bool:
        return (
            self.orientation == other.orientation
            and abs(self.coord - other.coord) < 1e-4
            and self.a0 - 1e-4 <= other.a0
            and other.a1 <= self.a1 + 1e-4
        )


def lane_faces(
    sk: Skeleton, flight: int, exterior: float, interior: float
) -> tuple[float, float, float]:
    """Wall faces bounding the lane of `flight` and the x of the flight's centre line between
    them (Phase 3.5 K2.5). A lane on the facade is bounded there by the exterior wall; other
    lane sides by interior walls. Returns (west face, east face, centre)."""
    x0, x1 = sk.lane(flight)
    t0 = exterior if abs(x0) < EPS else interior
    t1 = exterior if abs(x1 - sk.W) < EPS else interior
    # (x0 + t0/2 + x1 - t1/2) / 2, written so that a symmetric lane gives exactly its middle.
    return x0 + t0 / 2, x1 - t1 / 2, (x0 + x1) / 2 + (t0 - t1) / 4


def envelope(
    sk: Skeleton, pitched: bool
) -> list[tuple[str, tuple[float, float], tuple[float, float], str]]:
    """Exterior wall loop of one storey, counter-clockwise: (key suffix, start, end, roof).

    Rectangle: S, E, N, W. L (docs/3d-engine.md §16.10): the main bar's walls keep their keys
    (S, E, N = the garden wall beside the wing, W/E = the outer wall below the wing) and the
    wing adds `wing:*` walls; the outer side is split where the wing starts so each wall
    belongs to one volume and supports one roof (a pitched L has a main and a wing roof).
    T (§16.12): S, E, then the garden wall east of the wing (N:E), the wing (stem) walls,
    the garden wall west of it (N:W), W - eight walls, two inside corners."""
    W, D = sk.W, sk.D  # noqa: N806 - plan dimension names, as on Skeleton
    if not sk.has_wing:
        corners = [(0.0, 0.0), (W, 0.0), (W, D), (0.0, D)]
        return [
            (side, corners[i], corners[(i + 1) % 4], "roof:main") for i, side in enumerate("SENW")
        ]
    wing_roof = "roof:wing" if pitched else "roof:main"
    top = sk.depth_total
    x0, x1 = sk.wing_x
    if sk.topology == "t":
        return [
            ("S", (0.0, 0.0), (W, 0.0), "roof:main"),
            ("E", (W, 0.0), (W, D), "roof:main"),
            ("N:E", (W, D), (x1, D), "roof:main"),
            ("wing:E", (x1, D), (x1, top), wing_roof),
            ("wing:N", (x1, top), (x0, top), wing_roof),
            ("wing:W", (x0, top), (x0, D), wing_roof),
            ("N:W", (x0, D), (0.0, D), "roof:main"),
            ("W", (0.0, D), (0.0, 0.0), "roof:main"),
        ]
    if sk.wing_side == "west":
        return [
            ("S", (0.0, 0.0), (W, 0.0), "roof:main"),
            ("E", (W, 0.0), (W, D), "roof:main"),
            ("N", (W, D), (x1, D), "roof:main"),
            ("wing:E", (x1, D), (x1, top), wing_roof),
            ("wing:N", (x1, top), (0.0, top), wing_roof),
            ("wing:W", (0.0, top), (0.0, D), wing_roof),
            ("W", (0.0, D), (0.0, 0.0), "roof:main"),
        ]
    return [
        ("S", (0.0, 0.0), (W, 0.0), "roof:main"),
        ("E", (W, 0.0), (W, D), "roof:main"),
        ("wing:E", (W, D), (W, top), wing_roof),
        ("wing:N", (W, top), (x0, top), wing_roof),
        ("wing:W", (x0, top), (x0, D), wing_roof),
        ("N", (x0, D), (0.0, D), "roof:main"),
        ("W", (0.0, D), (0.0, 0.0), "roof:main"),
    ]
