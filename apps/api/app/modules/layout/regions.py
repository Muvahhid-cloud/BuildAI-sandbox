"""Steps 6-7 — turn a planned candidate into regions per level and derive the walls.

A region is a room (or a stair void) made of axis-aligned rectangles. Interior walls are derived
from region boundaries: wherever two different regions meet inside the footprint there is a
wall, unless that stretch is declared open (open-plan rooms, the entrance hall and corridor,
stair arrivals). Exterior walls are the footprint loop per level plus the garage enclosure.
"""

import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from app.modules.building.enums import RoomType, Zone
from app.modules.building.specification import BuildingSpecification
from app.modules.layout.config import LayoutConfig
from app.modules.layout.plan import (
    EPS,
    Candidate,
    Rect,
    Region,
    Segment,
    Skeleton,
    StairDesign,
    Strip,
    rnd,
    snap,
)
from app.modules.layout.program import Program, RoomRequest

DELTA = 1e-3


@dataclass
class LevelRegions:
    index: int
    regions: list[Region] = field(default_factory=list)
    open_edges: list[Segment] = field(default_factory=list)

    def get(self, key: str) -> Region | None:
        return next((r for r in self.regions if r.key == key), None)

    def at(self, x: float, y: float, *, inside_only: bool = True) -> Region | None:
        for r in self.regions:
            if (r.inside or not inside_only) and r.strictly_contains(x, y):
                return r
        return None


@dataclass(frozen=True)
class Attachment:
    kind: Literal["balcony", "terrace"]
    index: int
    level: int
    host: str  # region key of the room it opens from
    rect: Rect
    side: Literal["north", "south"]


@dataclass
class PlanLayout:
    skeleton: Skeleton
    stair: StairDesign | None
    levels: list[LevelRegions]
    garage: Rect | None
    attachments: list[Attachment]
    notes: list[str]


def _add(level: LevelRegions, region: Region) -> Region:
    existing = level.get(region.key)
    if existing is None:
        level.regions.append(region)
        return region
    existing.rects.extend(region.rects)
    return existing


def build_regions(
    cand: Candidate,
    program: Program,
    spec: BuildingSpecification,
    stair: StairDesign | None,
    config: LayoutConfig,
) -> PlanLayout:
    sk = cand.skeleton
    notes: list[str] = []
    levels = [LevelRegions(i) for i in range(sk.storeys)]
    corridor_y0, corridor_y1 = sk.Ds, rnd(sk.Ds + sk.C)

    for lv, lvl in enumerate(levels):
        layout = cand.levels[lv]
        # Corridor ends cut and given to rooms (L plans, V1.2): the corridor keeps the rest.
        cx0 = max([c.x1 for c in layout.cuts if c.x0 < EPS], default=0.0)
        cx1 = min([c.x0 for c in layout.cuts if c.x0 >= EPS], default=sk.W)
        corridor_rects = [Rect(cx0, corridor_y0, cx1, corridor_y1)]
        if sk.has_wing:  # the wing's gallery continues the corridor towards its end
            gx0, gx1 = sk.gallery_x
            wing = next((lay for lay in layout.strips if lay.strip.side == "wing"), None)
            end = wing.corridor_end if wing is not None else sk.depth_total
            if end > corridor_y1 + EPS:
                corridor_rects.append(Rect(gx0, corridor_y1, gx1, end))
        corridor = _add(
            lvl,
            Region(
                key=f"corridor_{lv}",
                kind="room",
                rects=corridor_rects,
                level=lv,
                name="Corridor" if lv == 0 else "Landing corridor",
                room_type=RoomType.CORRIDOR,
                zone=Zone.CIRCULATION,
            ),
        )
        # Empty street-side strips join the circulation (hall on the ground floor).
        for strip in layout.merged_strips:
            rect = Rect(strip.x0, strip.y0, strip.x1, strip.y1)
            if lv == 0:
                _add(lvl, _hall(lv, [rect]))
            else:
                corridor.rects.append(rect)
                notes.append(
                    f"Floor {lv + 1}: {rect.area:.1f} m² of the street side became landing "
                    "space (not enough rooms on that floor to fill it)"
                )
        if lv == 0:
            _add(lvl, _hall(lv, [Rect(sk.group_x0, 0.0, sk.group_x1, sk.Ds)]))
        elif stair is not None:
            _core_regions(lvl, sk, stair)

        for lay in layout.strips:
            strip = lay.strip
            u = strip.start  # position along the band
            for col in lay.columns:
                u1 = rnd(u + col.width)
                room = col.room
                if col.kind == "tuck" and col.owner is not None:
                    tuck, rest = _tuck_rects(strip, u, u1, col.depth)
                    _add(lvl, _room_region(room, lv, [tuck]))
                    _add(lvl, _room_region(col.owner, lv, [rest]))
                else:
                    _add(lvl, _room_region(room, lv, [_band_rect(strip, u, u1, 0.0, None)]))
                u = u1
            if lay.wrap_from > 0.0 and sk.has_wing:  # the last room takes the gallery's end
                gx0, gx1 = sk.gallery_x
                last = lay.columns[-1].room
                _add(lvl, _room_region(last, lv, [Rect(gx0, lay.corridor_end, gx1, u)]))
        by_key = program.by_key()
        for cut in layout.cuts:
            rect = Rect(cut.x0, corridor_y0, cut.x1, corridor_y1)
            _add(lvl, _room_region(by_key[cut.owner], lv, [rect]))

        hall = lvl.get(f"hall_{lv}")
        if hall is not None:
            lvl.open_edges += shared_edges(hall, corridor)

    # Open-plan pairs: open where they share an edge, or — facing each other across the
    # corridor — open onto the corridor over the stretch where they overlap.
    for a, b in program.open_plan:
        for lvl in levels:
            corridor_region = lvl.get(f"corridor_{lvl.index}")
            for ra in [lvl.get(r.key) for r in program.instances(a)]:
                for rb in [lvl.get(r.key) for r in program.instances(b)]:
                    if ra is None or rb is None:
                        continue
                    direct = shared_edges(ra, rb)
                    lvl.open_edges += direct
                    if direct or corridor_region is None:
                        continue
                    lvl.open_edges += across_corridor(ra, rb, corridor_region)

    garage = None
    if spec.features.garage is not None:
        garage = _garage(levels[0], sk, spec.features.garage.cars, config)
    attachments = _attachments(levels, sk, spec, config, notes)
    return PlanLayout(sk, stair, levels, garage, attachments, notes)


def _band_rect(strip: Strip, a0: float, a1: float, c0: float, c1: float | None) -> Rect:
    """Rectangle of a band between a0..a1 along it and c0..c1 across it, measured from the
    corridor edge (c1 None = to the facade). Band edges are used exactly where they apply."""
    if strip.axis == "x":
        lo, hi = strip.y0, strip.y1
    else:
        lo, hi = strip.x0, strip.x1
    if strip.corridor_low:
        b0 = lo if c0 == 0.0 else rnd(lo + c0)
        b1 = hi if c1 is None else rnd(lo + c1)
    else:
        b0 = lo if c1 is None else rnd(hi - c1)
        b1 = hi if c0 == 0.0 else rnd(hi - c0)
    return Rect(a0, b0, a1, b1) if strip.axis == "x" else Rect(b0, a0, b1, a1)


def _tuck_rects(strip: Strip, a0: float, a1: float, depth: float) -> tuple[Rect, Rect]:
    """A tucked service room against the corridor and its owner's facade-side remainder."""
    return _band_rect(strip, a0, a1, 0.0, depth), _band_rect(strip, a0, a1, depth, None)


def _hall(level: int, rects: list[Rect]) -> Region:
    return Region(
        key=f"hall_{level}",
        kind="room",
        rects=rects,
        level=level,
        name="Entrance hall",
        room_type=RoomType.ENTRANCE,
        zone=Zone.CIRCULATION,
    )


def _room_region(room: RoomRequest, level: int, rects: list[Rect]) -> Region:
    return Region(
        key=room.key,
        kind="room",
        rects=rects,
        level=level,
        name=room.name,
        room_type=room.type,
        zone=room.zone,
        request=room,
    )


def _core_regions(lvl: LevelRegions, sk: Skeleton, stair: StairDesign) -> None:
    """Stair lanes on an upper level: arrival void, departing staircase, landing."""
    lv = lvl.index
    ds = sk.Ds
    arrival = lv - 1
    ax0, ax1 = sk.lane(arrival)
    if arrival % 2 == 0:  # rises north, arrives at the corridor
        _add(lvl, Region(f"void_{lv}", "void", [Rect(ax0, 0.0, ax1, ds)], lv, "Stair void"))
        lvl.open_edges.append(Segment("h", ds, ax0, ax1))
    else:  # rises south, arrives at a landing on the street side
        top = rnd(ds - stair.run)
        _add(lvl, Region(f"void_{lv}", "void", [Rect(ax0, top, ax1, ds)], lv, "Stair void"))
        landing_rects = [Rect(ax0, 0.0, ax1, top)]
        free = [f for f in range(sk.lanes) if f not in (arrival, lv)]
        for f in free:
            fx0, fx1 = sk.lane(f)
            landing_rects.append(Rect(fx0, 0.0, fx1, ds))
            lvl.open_edges.append(Segment("h", ds, fx0, fx1))
        _add(
            lvl,
            Region(
                f"stair_{lv}",
                "room",
                landing_rects,
                lv,
                "Landing",
                RoomType.STAIRCASE,
                Zone.CIRCULATION,
            ),
        )
        lvl.open_edges.append(Segment("h", top, ax0, ax1))
    if lv <= sk.storeys - 2:  # departing flight (odd flights start at the corridor)
        dx0, dx1 = sk.lane(lv)
        _add(
            lvl,
            Region(
                f"stair_{lv}",
                "room",
                [Rect(dx0, 0.0, dx1, ds)],
                lv,
                "Staircase",
                RoomType.STAIRCASE,
                Zone.CIRCULATION,
            ),
        )
        lvl.open_edges.append(Segment("h", ds, dx0, dx1))


def _garage(level0: LevelRegions, sk: Skeleton, cars: int, config: LayoutConfig) -> Rect:
    width = rnd(cars * config.garage_width_per_car + config.garage_extra_width)
    depth = rnd(min(sk.D, max(config.garage_min_depth, sk.Ds + sk.C)))
    rect = (
        Rect(rnd(-width), 0.0, 0.0, depth)
        if sk.garage_side == "west"
        else Rect(sk.W, 0.0, rnd(sk.W + width), depth)
    )
    level0.regions.append(
        Region(
            "garage",
            "room",
            [rect],
            0,
            f"Garage ({cars} car{'s' if cars > 1 else ''})",
            RoomType.GARAGE,
            Zone.SERVICE,
            inside=False,
        )
    )
    return rect


GARDEN_HOSTS = (
    RoomType.LIVING,
    RoomType.OPEN_KITCHEN_LIVING,
    RoomType.DINING,
    RoomType.KITCHEN,
    RoomType.STUDY,
    RoomType.BEDROOM,
)
BALCONY_HOSTS = (RoomType.BEDROOM, RoomType.STUDY, RoomType.LIVING, RoomType.OPEN_KITCHEN_LIVING)


def facade_span(region: Region, side: Literal["north", "south"], sk: Skeleton) -> Rect | None:
    """The longest stretch of `region` along the north (y = D) or south (y = 0) facade."""
    y = sk.D if side == "north" else 0.0
    edges = sorted(
        (r.x0, r.x1) for r in region.rects if abs((r.y1 if side == "north" else r.y0) - y) < 1e-6
    )
    merged: list[list[float]] = []
    for a, b in edges:
        if merged and abs(merged[-1][1] - a) < 1e-6:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    if not merged:
        return None
    a, b = max(merged, key=lambda s: (s[1] - s[0], -s[0]))
    return Rect(a, y, b, y)


def _attachments(
    levels: list[LevelRegions],
    sk: Skeleton,
    spec: BuildingSpecification,
    config: LayoutConfig,
    notes: list[str],
) -> list[Attachment]:
    out: list[Attachment] = []
    used: set[str] = set()

    def pick(
        level: int,
        side: Literal["north", "south"],
        wanted: str | None,
        hosts: tuple[RoomType, ...],
        label: str,
    ) -> tuple[Region, Rect] | None:
        lvl = levels[level]
        options: list[tuple[int, float, str, Region, Rect]] = []
        for region in lvl.regions:
            if region.request is None or region.key in used:
                continue
            span = facade_span(region, side, sk)
            if span is None or span.w < 2.0:
                continue
            is_wanted = wanted is not None and region.request.spec_key == wanted
            rank = hosts.index(region.room_type) if region.room_type in hosts else len(hosts)
            if not is_wanted and rank == len(hosts):
                continue
            options.append((0 if is_wanted else 1 + rank, -span.w, region.key, region, span))
        if not options:
            notes.append(f"No room on floor {level + 1} can host the {label}; it was left out")
            return None
        options.sort(key=lambda o: o[:3])
        first = options[0]
        if wanted is not None and first[0] != 0:
            notes.append(
                f"The {label} could not open from {wanted!r} (not on the {side} facade of floor "
                f"{level + 1}); it opens from {first[3].name} instead"
            )
        used.add(first[2])
        return first[3], first[4]

    for i, balcony in enumerate(spec.features.balconies):
        side: Literal["north", "south"] = "north" if balcony.side == "garden" else "south"
        picked = pick(balcony.level, side, balcony.attached_to, BALCONY_HOSTS, "balcony")
        if picked is None:
            continue
        host, span = picked
        g = config.grid
        width = min(balcony.width_m or config.balcony_width, span.w - 0.6)
        x0 = snap((span.x0 + span.x1 - width) / 2, g)
        x1 = rnd(x0 + snap(width, g))
        depth = rnd(balcony.depth_m)
        y0, y1 = (sk.D, rnd(sk.D + depth)) if side == "north" else (rnd(-depth), 0.0)
        rect = Rect(x0, y0, x1, y1)
        out.append(Attachment("balcony", i, balcony.level, host.key, rect, side))
        levels[balcony.level].regions.append(
            Region(
                f"balcony_{i}",
                "room",
                [rect],
                balcony.level,
                "Balcony",
                RoomType.BALCONY,
                Zone.EXTERIOR,
                inside=False,
            )
        )
    terrace = spec.features.terrace
    if terrace is not None:
        picked = pick(0, "north", terrace.attached_to, GARDEN_HOSTS, "terrace")
        if picked is not None:
            host, span = picked
            width = terrace.width_m or span.w
            # Within the stretch of the main bar's garden facade its host is on (a wing stands
            # beside it: one stretch for an L, one on each side for a T).
            gx0, gx1 = next(
                (r for r in sk.garden_ranges if r[0] - EPS <= span.x0 and span.x1 <= r[1] + EPS),
                sk.garden_x,
            )
            half = config.exterior_wall_thickness / 2
            lo = gx0 + (half if gx0 > EPS else 0.0)
            hi = gx1 - (half if gx1 < sk.W - EPS else 0.0)
            x0 = max(lo, span.x0 + (span.w - width) / 2)
            x1 = min(hi, x0 + width)
            x0, x1 = snap(x0, config.grid), snap(x1, config.grid)
            rect = Rect(x0, sk.D, x1, rnd(sk.D + terrace.depth_m))
            out.append(Attachment("terrace", 0, 0, host.key, rect, "north"))
            levels[0].regions.append(
                Region(
                    "terrace",
                    "room",
                    [rect],
                    0,
                    "Terrace",
                    RoomType.TERRACE,
                    Zone.EXTERIOR,
                    inside=False,
                )
            )
    return out


CROSS_CORRIDOR_MIN = 1.5  # overlap needed for an open plan across the corridor


def across_corridor(a: Region, b: Region, corridor: Region) -> list[Segment]:
    """Corridor edges to open so rooms `a` and `b` on opposite sides form one open space."""
    ea = [e for e in shared_edges(a, corridor) if e.orientation == "h"]
    eb = [e for e in shared_edges(b, corridor) if e.orientation == "h"]
    out: list[Segment] = []
    for sa in ea:
        for sb in eb:
            if abs(sa.coord - sb.coord) < 1e-6:
                continue  # same side of the corridor
            lo, hi = max(sa.a0, sb.a0), min(sa.a1, sb.a1)
            if hi - lo >= CROSS_CORRIDOR_MIN - 1e-6:
                out += [Segment("h", sa.coord, lo, hi), Segment("h", sb.coord, lo, hi)]
    return out


def subtract_open(edges: list[Segment], open_edges: list[Segment]) -> tuple[list[Segment], float]:
    """Parts of `edges` not covered by open edges, and the total open length."""
    pieces: list[Segment] = []
    open_length = 0.0
    for e in edges:
        cuts = sorted(
            (max(o.a0, e.a0), min(o.a1, e.a1))
            for o in open_edges
            if o.orientation == e.orientation
            and abs(o.coord - e.coord) < 1e-6
            and min(o.a1, e.a1) - max(o.a0, e.a0) > 1e-6
        )
        cursor = e.a0
        for lo, hi in cuts:
            if lo > cursor + 1e-6:
                pieces.append(Segment(e.orientation, e.coord, cursor, lo))
            open_length += max(0.0, hi - max(lo, cursor))
            cursor = max(cursor, hi)
        if e.a1 > cursor + 1e-6:
            pieces.append(Segment(e.orientation, e.coord, cursor, e.a1))
    return pieces, open_length


def shared_edges(a: Region, b: Region) -> list[Segment]:
    """Boundary stretches where the rectangles of `a` and `b` touch."""
    out: list[Segment] = []
    for ra in a.rects:
        for rb in b.rects:
            for ya, yb in ((ra.y1, rb.y0), (ra.y0, rb.y1)):
                if abs(ya - yb) < 1e-6:
                    lo, hi = max(ra.x0, rb.x0), min(ra.x1, rb.x1)
                    if hi - lo > 1e-6:
                        out.append(Segment("h", ya, lo, hi))
            for xa, xb in ((ra.x1, rb.x0), (ra.x0, rb.x1)):
                if abs(xa - xb) < 1e-6:
                    lo, hi = max(ra.y0, rb.y0), min(ra.y1, rb.y1)
                    if hi - lo > 1e-6:
                        out.append(Segment("v", xa, lo, hi))
    return out


# --- walls --------------------------------------------------------------------------------------


@dataclass
class WallRun:
    orientation: Literal["h", "v"]
    coord: float
    a0: float
    a1: float
    # (region on the "low" side, region on the "high" side, length) per piece:
    # h: low = south (right face), high = north (left face); v: low = west (left), high = east.
    pieces: list[tuple[str, str, float]] = field(default_factory=list)


def derive_interior_walls(level: LevelRegions, width: float, depth: float) -> list[WallRun]:
    inside = [r for r in level.regions if r.inside]
    xs = sorted({rnd(v) for r in inside for rect in r.rects for v in (rect.x0, rect.x1)})
    ys = sorted({rnd(v) for r in inside for rect in r.rects for v in (rect.y0, rect.y1)})

    def open_(seg: Segment) -> bool:
        return any(o.covers(seg) for o in level.open_edges)

    def region_key(x: float, y: float) -> str | None:
        r = level.at(x, y)
        return r.key if r is not None else None

    pieces: dict[tuple[str, float], list[tuple[float, float, str, str]]] = defaultdict(list)
    for x in xs:
        if x <= 1e-6 or x >= width - 1e-6:
            continue
        for y0, y1 in itertools.pairwise(ys):
            ym = (y0 + y1) / 2
            lo, hi = region_key(x - DELTA, ym), region_key(x + DELTA, ym)
            if lo is None or hi is None or lo == hi or open_(Segment("v", x, y0, y1)):
                continue
            pieces[("v", x)].append((y0, y1, lo, hi))
    for y in ys:
        if y <= 1e-6 or y >= depth - 1e-6:
            continue
        for x0, x1 in itertools.pairwise(xs):
            xm = (x0 + x1) / 2
            lo, hi = region_key(xm, y - DELTA), region_key(xm, y + DELTA)
            if lo is None or hi is None or lo == hi or open_(Segment("h", y, x0, x1)):
                continue
            pieces[("h", y)].append((x0, x1, lo, hi))

    def merge(orientation: Literal["h", "v"], coord: float, splits: set[float]) -> list[WallRun]:
        runs: list[WallRun] = []
        for a0, a1, lo, hi in sorted(pieces[(orientation, coord)]):
            last = runs[-1] if runs else None
            if last is not None and abs(last.a1 - a0) < 1e-6 and rnd(a0) not in splits:
                last.a1 = a1
                last.pieces.append((lo, hi, a1 - a0))
            else:
                runs.append(WallRun(orientation, coord, a0, a1, [(lo, hi, a1 - a0)]))
        return runs

    horizontal = [run for (o, c) in sorted(pieces) if o == "h" for run in merge("h", c, set())]
    vertical: list[WallRun] = []
    for o, c in sorted(pieces):
        if o != "v":
            continue
        # Split vertical runs where a horizontal run passes straight through (X crossings).
        splits = {rnd(h.coord) for h in horizontal if h.a0 + 1e-6 < c < h.a1 - 1e-6}
        vertical += merge("v", c, splits)
    return horizontal + vertical
